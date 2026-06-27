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
    # The stake/ward identity. Prefer the live LCR user_context (it also carries positions/roles for
    # role provisioning); but once the delegated LCR session has aged out, fall back to the structure
    # the Member Tools /api/v5/sync payload provides (ctx_override) so the data sync still completes —
    # the covenant-path bulk data came from that same 45-day token regardless of the LCR session.
    try:
        ctx = client.user_context()
    except Exception as exc:  # noqa: BLE001
        if ctx_override is None:
            raise
        logger.warning("user_context via LCR unavailable (%s) — using the Member Tools unit structure",
                       str(exc)[:120])
        ctx = ctx_override

    # DATA-INTEGRITY GUARD — a delegated credential must only ever sync the stake it is REGISTERED
    # for (expected_stake_unit). It can resolve to the WRONG stake two ways, both refused here BEFORE
    # any write so one stake's members are never stamped with another stake's id:
    #   1. Ward-beneath-stake (Green Level Ward, 2026-06-13): a WARD/BRANCH leader's Member Tools
    #      token returns the PARENT stake as its org root while exposing data for only their unit, so
    #      ctx_override names the parent stake. Unchecked, the sync upserts that one ward's members
    #      onto the WHOLE stake and reconciles every other ward away (Raleigh 93 -> 7).
    #   2. Cross-stake (Springville-as-Raleigh, 2026-06-25): the token's real stake is an ENTIRELY
    #      DIFFERENT stake than the registered one (an operator's own Springville Utah token enrolled
    #      as the Raleigh stake). The daily Raleigh job then pulls Springville's members and writes
    #      them under Raleigh's stake_id. The original guard missed this because the registered stake
    #      is NOT a child of the token's stake.
    # The data's true stake is the Member Tools org root (the bulk covenant-path data came from that
    # 45-day token); fall back to the resolved context when there is no MT override (legacy live-LCR
    # scrape). If it is not the registered stake, REFUSE. The operator's own self-sync passes no
    # expected unit, so the guard stays inert there (their MT root IS their stake).
    if expected_stake_unit is not None:
        synced_unit = (ctx_override.unit_number if ctx_override is not None
                       else getattr(ctx, "unit_number", None))
        if synced_unit is not None and synced_unit != expected_stake_unit:
            raise CredentialScopeMismatch(expected_stake_unit, synced_unit)
    # DATA-vs-IDENTITY guard (2026-06-27): the check above compares the resolved IDENTITY (the LCR
    # session, or the Member Tools `units` tree when present) against the registered stake — but the
    # member DATA comes from a SEPARATE source (the Member Tools /api/v5/sync token), and the two can
    # disagree. When the token returned the operator's HOME stake's roster while the live LCR session
    # still resolved to the registered stake (and the payload carried no `units` tree, so ctx_override
    # was None), the check above saw identity == registered and passed, and another stake's members got
    # stamped with this stake's id (Springville-under-Raleigh, 2026-06-27 — the recurrence of the
    # 2026-06-25 leak). Validate the MEMBERS' OWN units against the stake we are about to write them
    # under, so neither a missing `unit_context` nor a wrong-but-registered session can blind it.
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
    # stake-level KPIs for the viewer's KPIs tab (never fail the data sync over them)
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
        if not by_unit:
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
    # rebuild access roles from current callings (no manual role assignment)
    try:
        from backend.roles import provision_roles
        roles = provision_roles(conn, client, stake_id, unit_id_by_name)
    except Exception as exc:  # noqa: BLE001 — never fail the data sync over role provisioning
        logger.warning("role provisioning skipped for stake %s: %s", stake_id, exc)
        roles = None
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
