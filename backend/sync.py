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
    Two shapes, both refused by sync_stake BEFORE any write (the caller revokes/flags the credential
    and skips it — not a red-fail):
      • its registered unit is a WARD/BRANCH beneath the stake the token can see (Green Level Ward,
        2026-06-13), or
      • the token's real stake is an ENTIRELY DIFFERENT stake than the registered one (an operator's
        own Springville Utah token enrolled as the Raleigh stake, 2026-06-25).
    Either way a mis-scoped credential must never sync, let alone overwrite, the registered stake —
    otherwise one stake's members get stamped with another stake's id.
    """

    def __init__(self, expected_unit: int, stake_unit: int):
        self.expected_unit = expected_unit
        self.stake_unit = stake_unit
        super().__init__(
            f"credential registered for stake unit {expected_unit} resolved to a different stake "
            f"({stake_unit}); a mis-scoped credential cannot sync the registered stake")


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
