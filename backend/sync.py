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
               failed_unit_numbers=None, only_unit=None, access=None, ctx_override=None) -> dict:
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
    # full-time missionaries assigned to each ward/branch (#29) — one cheap action per unit
    try:
        from lcr_client.missionaries import fetch_unit_missionaries
        by_unit: dict[str, list] = {}
        for u in ctx.child_units:
            if u.unit_number and u.type in ("WARD", "BRANCH"):
                ms = fetch_unit_missionaries(client.session, u.unit_number)
                if ms:
                    by_unit[u.name] = ms
        db.update_stake_missionaries(conn, stake_id, by_unit)
        logger.info("missionaries: %d units with assignments", len(by_unit))
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
