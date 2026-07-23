"""
Sync a covenant-path report into Supabase (stakes / units / members).

Stake + unit identity come from the live LCR session (user-context); member rows
come from the report (JSON or a fresh --scrape). Everything is upserted idempotently
keyed by (stake_id, person_uuid), so re-running is safe and `members.updated_at`
reflects the last change (which the daily job uses for incremental skipping).

  python -m backend.sync                 # upsert output/covenant_path_stake.json
  python -m backend.sync --scrape --with-profile
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend import db
from lcr_client import LcrClient
from lcr_client.logging_setup import get_logger

logger = get_logger()
REPORT_JSON = Path(__file__).resolve().parent.parent / "output" / "covenant_path_stake.json"


class CredentialScopeMismatch(Exception):
    """A delegated credential resolved to a DIFFERENT stake than the one it is registered for.
    THREE shapes, all refused by sync_stake BEFORE any write (the caller revokes/flags the credential
    and skips it — not a red-fail):
      • its registered unit is a WARD/BRANCH beneath the stake the token can see (Green Level Ward,
        2026-06-13), or
      • the token's real stake is an ENTIRELY DIFFERENT stake than the registered one, detected from
        the Member Tools payload's `units` tree (an operator's own Springville Utah token enrolled as
        the Raleigh stake, 2026-06-25), or
      • the MEMBER ROWS themselves belong to a different stake than the one we are about to write them
        under — even though the session/identity resolved to the registered stake. This is the leak the
        first two checks missed: a live "Raleigh" LCR session (stake identity) + a Member Tools token
        that returned the operator's home "Springville" roster (member data), with NO `units` tree in
        the payload, wrote 34 Springville members under Raleigh's stake_id (2026-06-27). Keyed off the
        members' OWN units, so a missing `unit_context` can't blind it.
    Either way a mis-scoped credential must never sync, let alone overwrite, the registered stake —
    otherwise one stake's members get stamped with another stake's id.
    """

    def __init__(self, expected_unit, stake_unit, reason: str | None = None):
        self.expected_unit = expected_unit
        self.stake_unit = stake_unit
        self.reason = reason
        super().__init__(reason or (
            f"credential registered for stake unit {expected_unit} resolved to a different stake "
            f"({stake_unit}); a mis-scoped credential cannot sync the registered stake"))


def _norm_unit_name(name) -> str | None:
    """Normalize a unit name for comparison — collapse internal whitespace + casefold — so a Member
    Tools 'Springville  9th Ward' (double space) and an LCR 'Springville 9th Ward' compare equal."""
    if not name:
        return None
    return " ".join(str(name).split()).casefold()


def _resolve_unit_stake(conn, unit_number) -> int | None:
    """Best-effort: the STAKE unit number that owns a given ward/branch unit number, from the unit
    registry. Used only to label the refusal ('member data belongs to stake N'); never required —
    returns None on any error / unknown unit (e.g. a brand-new unit, or the unit-test's fake conn)."""
    if not unit_number:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("select s.unit_number from units u join stakes s on s.id = u.stake_id "
                        "where u.unit_number = %s limit 1", (int(unit_number),))
            row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception:  # noqa: BLE001 — labeling is cosmetic; a fake/closed conn must not crash the guard
        return None


def _assert_members_belong_to_stake(ctx, members, expected_stake_unit, conn=None) -> None:
    """Refuse before any write if the MEMBER ROWS belong to a different stake than `ctx` (the stake we
    are about to write them under). This closes the hole the unit-number/`expected_stake_unit` guard
    left: when the Member Tools payload carries no `units` tree, `ctx_override` is None and the old
    guard fell back to the live session's stake — which, for an operator who is a leader in the
    registered stake but whose Member Tools token returns their HOME stake's roster, equals the
    registered stake — so foreign member data slipped straight through (Springville-under-Raleigh,
    2026-06-25 and 2026-06-27).

    A member is 'foreign' when its unit (by NUMBER — formatting-immune — else normalized name) is not
    one of this stake's own units. We refuse only when EVERY identifiable member is foreign — i.e. the
    payload is wholesale another stake's roster. A handful of moved-ward orphans always leave overlap
    with the stake's units, so this never trips on them."""
    if not members:
        return
    stake_nums = {u.unit_number for u in (getattr(ctx, "child_units", None) or [])
                  if getattr(u, "unit_number", None)}
    stake_names = {_norm_unit_name(u.name) for u in (getattr(ctx, "child_units", None) or [])
                   if getattr(u, "name", None)}
    if not (stake_nums or stake_names):
        return  # this stake's own units are unknown this run → can't judge; the id-based guard stands
    # Prefer unit NUMBERS when both sides have them (immune to name formatting); else normalized names.
    use_numbers = bool(stake_nums) and any(m.get("unit_number") for m in members)
    member_keys: set = set()
    foreign: set = set()
    foreign_sample_number = None
    for m in members:
        if use_numbers:
            key = m.get("unit_number")
            if not key:
                continue
            member_keys.add(key)
            if key not in stake_nums:
                foreign.add(key)
                foreign_sample_number = foreign_sample_number or key
        else:
            key = _norm_unit_name(m.get("unit") or m.get("unit_name"))
            if not key:
                continue
            member_keys.add(key)
            if key not in stake_names:
                foreign.add(key)
    if not member_keys or foreign != member_keys:
        return  # at least one member belongs to this stake → not a wholesale foreign roster
    target = getattr(ctx, "unit_number", None)
    data_stake = _resolve_unit_stake(conn, foreign_sample_number) if use_numbers else None
    raise CredentialScopeMismatch(
        expected_stake_unit if expected_stake_unit is not None else target,
        data_stake if data_stake is not None else (foreign_sample_number or 0),
        reason=(f"member rows belong to a different stake than {expected_stake_unit or target} — every "
                f"member's unit is foreign to it"
                + (f" (their units roll up to stake {data_stake})" if data_stake else "")
                + "; the Member Tools token returned another stake's roster, refusing before any write"))


def _load_members(scrape: bool, with_profile: bool) -> list[dict]:
    if scrape:
        from dataclasses import asdict
        from covenant_path.report import build_stake_report
        return [asdict(r) for r in build_stake_report(LcrClient(), with_profile=with_profile)]
    if not REPORT_JSON.exists():
        raise SystemExit(f"No report at {REPORT_JSON}; run with --scrape or generate it first.")
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


def kpi_subtree(dash: dict) -> dict:
    """Pick the stake KPIs the viewer's KPIs tab shows from /api/dashboard/data."""
    cp = dash.get("covenantPathProgressWidgetDto") or {}
    att = dash.get("attendanceWidgetDto") or {}
    rec = dash.get("templeRecommendWidgetDto") or {}
    minw = dash.get("ministeringInterviewWidgetDto") or {}

    def months(key):
        return [{"month": m.get("monthLabel"), "attended": m.get("attended"),
                 "potential": m.get("potential")} for m in (att.get(key) or [])]

    return {
        "newMemberCount": cp.get("newMemberCount"),
        "peopleBeingTaught": cp.get("peopleBeingTaughtCount"),
        "sacramentByMonth": months("sacramentMeetingAttendance"),
        "classQuorumByMonth": months("classAndQuorumAttendance"),
        "templeRecommend": {
            "endowedActual": rec.get("endowedWithRecommendActual"),
            "endowedTotal": rec.get("endowedWithRecommendTotal"),
            "youthActual": rec.get("youthWithRecommendActual"),
            "youthTotal": rec.get("youthWithRecommendTotal"),
        },
        "ministering": {
            "brotherInterviewed": minw.get("brotherCompanionshipsInterviewed"),
            "brotherTotal": minw.get("brotherCompanionshipsTotal"),
            "sisterInterviewed": minw.get("sisterCompanionshipsInterviewed"),
            "sisterTotal": minw.get("sisterCompanionshipsTotal"),
        },
    }


def sync_stake(client: LcrClient, members: list[dict], conn,
               failed_unit_numbers=None, only_unit=None, access=None, ctx_override=None,
               expected_stake_unit=None) -> dict:
    # ---- Resolve the stake IDENTITY (stake_id + units) the members are written under ----------------
    # The member DATA comes from the Member Tools /api/v5/sync token (keyed by `expected_stake_unit` for
    # a delegated stake). The live LCR `user_context()` is a SEPARATE signal that can resolve to a
    # DIFFERENT stake — and did: a delegated stake whose dead LCR session got re-established as the
    # OPERATOR's session (which a disabled-MFA operator login now does headlessly) makes user_context()
    # return the OPERATOR's stake. The old code PREFERRED that live ctx for the write identity, so the
    # Springville job pulled Springville's 34 members (correctly, from Springville's own token) but
    # stamped them with RALEIGH's stake_id (2026-06-27, root cause of the recurring leak). The identity
    # must be the MEMBER DATA's OWN stake — NEVER a foreign live session.
    live_ctx = None
    try:
        live_ctx = client.user_context()
    except Exception as exc:  # noqa: BLE001
        if ctx_override is None:
            raise
        logger.warning("user_context via LCR unavailable (%s) — using the Member Tools unit structure",
                       str(exc)[:120])
    # For a delegated sync the data's stake IS `expected_stake_unit` (the Member Tools token is keyed by
    # it). Choose the identity whose stake matches it; the Member Tools payload context (`ctx_override`)
    # is the data's own structure, so prefer it. A live session that resolved to a DIFFERENT stake never
    # becomes the write identity.
    if expected_stake_unit is not None:
        ctx = next((c for c in (ctx_override, live_ctx)
                    if c is not None and getattr(c, "unit_number", None) == expected_stake_unit), None)
        if ctx is None:
            # Neither source is the registered stake. Prefer the Member Tools payload's own stake (what we
            # actually fetched) so the guards below report the TRUE mismatch and revoke the RIGHT
            # credential; never fall back to a foreign live session as the identity.
            ctx = ctx_override if ctx_override is not None else live_ctx
    else:
        # Operator self-sync (no registered unit): the data's stake is the Member Tools payload's, and the
        # live session is the operator's own (they agree). Prefer the payload when present.
        ctx = ctx_override if ctx_override is not None else live_ctx
    if ctx is None:
        raise RuntimeError("sync_stake: no stake identity (no live user_context and no Member Tools "
                           "unit context)")
    # The live LCR session may be trusted for its LCR-only EXTRAS (role provisioning, KPIs, the live
    # missionary fallback) ONLY when it is actually THIS stake's session — not a foreign/operator one.
    live_session_matches = (live_ctx is not None
                            and getattr(live_ctx, "unit_number", None) == ctx.unit_number)
    if live_ctx is not None and not live_session_matches:
        logger.warning("sync_stake: live LCR session is stake %s but the member data is stake %s — "
                       "IGNORING the foreign session for identity AND LCR extras, writing under the "
                       "data's own stake (operator-session contamination guard, 2026-06-27)",
                       getattr(live_ctx, "unit_number", None), ctx.unit_number)

    # REGISTERED-stake guard — the resolved identity must be the credential's registered stake. The
    # resolution above already picks a matching source when one exists; this REFUSES (before any write;
    # caller revokes + skips) only when NEITHER the Member Tools payload NOR the live session is the
    # registered stake — a genuinely mis-scoped credential:
    #   1. Ward-beneath-stake (Green Level Ward, 2026-06-13): the token's org root is the PARENT stake.
    #   2. Wholly-different stake (Springville-as-Raleigh, 2026-06-25): the token's stake isn't registered.
    if expected_stake_unit is not None and ctx.unit_number is not None \
            and ctx.unit_number != expected_stake_unit:
        raise CredentialScopeMismatch(expected_stake_unit, ctx.unit_number)
    # DATA-vs-IDENTITY guard (2026-06-27): validate the MEMBERS' OWN units against the stake we are about
    # to write them under — defense in depth for any path where data and identity could still diverge
    # (a missing `unit_context`, a wrong-but-registered session). Keyed off the rows themselves.
    _assert_members_belong_to_stake(ctx, members, expected_stake_unit, conn)
    # Stake identity is keyed by unit_number (stable), so a stake RENAME just updates stakes.name —
    # never a duplicate. Units are upserted by unit_number too: a renamed ward updates its name, a
    # ward that moved stakes updates its stake_id, and a person who changed wards gets their unit_id +
    # unit_name refreshed on member upsert. (#2)
    stake_id = db.upsert_stake(conn, ctx.unit_number, ctx.unit_name)
    unit_id_by_number: dict[int, str] = {}
    unit_id_by_name: dict[str, str] = {}
    current_unit_numbers: list[int] = []
    for u in ctx.child_units:
        if u.unit_number:
            uid = db.upsert_unit(conn, stake_id, u.unit_number, u.name, u.type)
            unit_id_by_number[u.unit_number] = uid
            current_unit_numbers.append(u.unit_number)
            if u.name:
                unit_id_by_name[u.name] = uid
    # #12: per-unit leadership roster on units.staffing, from the bulk household directory (session-
    # independent). Best-effort — never fails the data sync. RLS-scoped per unit by units_select (stake
    # leaders see every unit; a ward leader sees only their own), so no app-side filtering is needed.
    staffing = (access or {}).get("_run_stats", {}).get("staffing_by_unit") or {}
    if staffing and unit_id_by_number:
        for unum, uid in unit_id_by_number.items():
            try:
                db.update_unit_staffing(conn, uid, staffing.get(unum) or staffing.get(int(unum)) or [])
            except Exception as exc:  # noqa: BLE001
                logger.warning("staffing write skipped for unit %s: %s", unum, exc)
    # Restructuring: drop units that are no longer children of this stake. Gated on a non-empty
    # current list so a failed user_context can never wipe the stake's units (#2).
    if current_unit_numbers:
        removed = db.prune_units(conn, stake_id, current_unit_numbers)
        if removed:
            logger.info("pruned %d departed unit(s) from stake %s (%s)",
                        removed, ctx.unit_name, ctx.unit_number)
    written = db.upsert_members(conn, stake_id, members, unit_id_by_number, unit_id_by_name)
    # Adopt any PENDING partner notes (recorded on a person before/while they were absent from the sync)
    # now that their member row exists — they inherit this stake's scope and become visible to leaders.
    try:
        adopted = db.adopt_orphan_notes(conn, stake_id)
        if adopted:
            logger.info("adopted %d pending note(s) into stake %s (%s)",
                        adopted, ctx.unit_name, ctx.unit_number)
    except Exception as exc:  # noqa: BLE001 — never fail the data sync over note adoption
        logger.warning("note adoption skipped for stake %s: %s", stake_id, exc)
    # Auto-merge manually-added people the sync now has a REAL record for (exact name within the same
    # unit): preserve their notes onto the real member, soft-mark the manual row merged.
    try:
        auto_merged = db.merge_manual_members(conn, stake_id)
        if auto_merged:
            logger.info("auto-merged %d manual person(s) into synced records for stake %s (%s)",
                        auto_merged, ctx.unit_name, ctx.unit_number)
    except Exception as exc:  # noqa: BLE001 — never fail the data sync over the manual-merge convenience
        logger.warning("manual-member merge skipped for stake %s: %s", stake_id, exc)
    # Reconcile departed people (hard-delete): anyone no longer in LCR for a unit that scraped
    # cleanly this run has left the stake (moved out / record removed / deceased) → remove them.
    # Units that FAILED to scrape are excluded so a transient LCR failure never wipes a roster.
    failed = {int(n) for n in (failed_unit_numbers or ())}
    if only_unit is not None:
        # OPS single-unit refetch: the report covers ONLY this ward — reconcile just it, and leave
        # stake-wide orphans alone (a targeted refetch must never touch other wards' members).
        keep_numbers = {int(only_unit)} - failed
        include_orphans = False
    else:
        keep_numbers = set(unit_id_by_number) - failed
        include_orphans = True
    keep_unit_ids = [unit_id_by_number[n] for n in keep_numbers if n in unit_id_by_number]
    present_uuids = [m.get("person_uuid") for m in members if m.get("person_uuid")]
    # DEGRADED-RUN guard: when any unit failed this run, LCR is visibly unhealthy — and its 500s can
    # also degrade the "successful" units' rosters (thinner-but-200 responses). A burst of departures
    # in that state is far more likely bad data than 10 real same-day moves (2026-06-09: 10 'departed'
    # while 2 units were 500-ing). Defer deletions to the next CLEAN run; small churn (≤3) still flows.
    removed_people = 0
    candidates = db.count_reconcile_candidates(conn, stake_id, present_uuids, keep_unit_ids, include_orphans)
    if failed and candidates > 3:
        logger.warning("reconcile DEFERRED for stake %s: %d would-be removals during a DEGRADED run "
                       "(%d failed unit(s)) — preserving members until a clean run",
                       ctx.unit_number, candidates, len(failed))
        try:
            db.insert_diagnostics(conn, stake_id, "reconcile_deferred",
                                  {"candidates": candidates, "failed_units": sorted(failed)})
        except Exception:  # noqa: BLE001
            pass
    elif candidates:
        removed_people = db.reconcile_members(conn, stake_id, present_uuids, keep_unit_ids, include_orphans)
        logger.info("reconciled %d departed member(s) from stake %s (%s)",
                    removed_people, ctx.unit_name, ctx.unit_number)
    # stake-level KPIs for the viewer's KPIs tab (never fail the data sync over them). LCR-session-bound:
    # skip when the live session is foreign/dead — a foreign (operator) session would fetch the WRONG
    # stake's KPIs and store them here.
    if live_session_matches:
        try:
            db.update_stake_kpis(conn, stake_id, kpi_subtree(client.dashboard_data()))
        except Exception as exc:  # noqa: BLE001
            logger.warning("KPI dashboard fetch skipped for stake %s: %s", stake_id, exc)
    # full-time missionaries per ward (#3a) — PREFER the session-independent bulk COMPANIONSHIPS
    # (missionariesAssigned) so the roster refreshes every sync even with a dead LCR session; fall back
    # to the live /mlt action only when the bulk roster is empty (e.g. the legacy one-work path).
    try:
        num_to_name = {c.unit_number: c.name for c in ctx.child_units if c.unit_number}
        bulk = (access or {}).get("_run_stats", {}).get("missionaries_by_unit") or {}
        by_unit: dict[str, list] = {}
        for unum, comps in bulk.items():
            name = num_to_name.get(int(unum)) or num_to_name.get(unum)
            if name:
                by_unit[name] = comps
        if not by_unit and live_session_matches:  # live /mlt fallback only on THIS stake's own session
            from lcr_client.missionaries import fetch_unit_missionaries
            for u in ctx.child_units:
                if u.unit_number and u.type in ("WARD", "BRANCH"):
                    ms = fetch_unit_missionaries(client.session, u.unit_number)
                    if ms:
                        by_unit[u.name] = ms
        db.update_stake_missionaries(conn, stake_id, by_unit)
        logger.info("missionaries: %d units with companionships (source=%s)",
                    len(by_unit), "bulk" if bulk else "mlt")
    except Exception as exc:  # noqa: BLE001 — never fail the data sync over the roster
        logger.warning("missionary roster skipped for stake %s: %s", stake_id, exc)
    # rebuild access roles from current callings (no manual role assignment). LCR-session-bound: a
    # foreign/dead session must NOT provision roles — a foreign (operator) session would clone the WRONG
    # stake's callings onto this stake_id (the role half of the 2026-06-27 contamination). Skip → the
    # last-good roles persist; the next sync on this stake's own session refreshes them.
    roles = None
    if live_session_matches:
        try:
            from backend.roles import provision_roles
            roles = provision_roles(conn, client, stake_id, unit_id_by_name)
        except Exception as exc:  # noqa: BLE001 — never fail the data sync over role provisioning
            logger.warning("role provisioning skipped for stake %s: %s", stake_id, exc)
            roles = None
    else:
        logger.info("role provisioning skipped for stake %s — live LCR session isn't this stake's "
                    "(foreign/dead); keeping last-good roles", stake_id)
    # Calling → access-level catalog (feedback #1): seed the hardcoded baseline, then refresh from
    # the access matrix the REPORT PHASE already evaluated (passed in — no re-fetch; a late re-fetch
    # at the end of a 45-min run hit a degraded page and threw 'NoneType is not subscriptable').
    try:
        from backend import access_levels
        access_levels.seed_baseline(conn)
        if access and access.get("features"):
            access_levels.persist_catalog(conn, access["features"])
    except Exception as exc:  # noqa: BLE001 — never fail the data sync over the catalog
        logger.warning("access catalog skipped for stake %s: %s", stake_id, exc)
    db.touch_stake_synced(conn, stake_id)
    db.set_sync_state(conn, stake_id, "done")
    return {"stake": ctx.unit_name, "stake_unit": ctx.unit_number, "stake_id": stake_id,
            "units": len(unit_id_by_number), "members_written": written,
            "members_removed": removed_people, "roles": roles}


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync covenant-path report to Supabase")
    ap.add_argument("--scrape", action="store_true", help="run the report instead of loading JSON")
    ap.add_argument("--with-profile", action="store_true")
    args = ap.parse_args()

    members = _load_members(args.scrape, args.with_profile)
    client = LcrClient()
    conn = db.connect()
    try:
        summary = sync_stake(client, members, conn)
    finally:
        conn.close()
    print(f"[+] synced {summary['members_written']} members across {summary['units']} units "
          f"-> {summary['stake']} ({summary['stake_unit']})")
    logger.info("supabase sync: %s", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
