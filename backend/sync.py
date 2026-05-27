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


def sync_stake(client: LcrClient, members: list[dict], conn) -> dict:
    ctx = client.user_context()
    stake_id = db.upsert_stake(conn, ctx.unit_number, ctx.unit_name)
    unit_id_by_number: dict[int, str] = {}
    unit_id_by_name: dict[str, str] = {}
    for u in ctx.child_units:
        if u.unit_number:
            uid = db.upsert_unit(conn, stake_id, u.unit_number, u.name, u.type)
            unit_id_by_number[u.unit_number] = uid
            if u.name:
                unit_id_by_name[u.name] = uid
    written = db.upsert_members(conn, stake_id, members, unit_id_by_number, unit_id_by_name)
    # rebuild access roles from current callings (no manual role assignment)
    try:
        from backend.roles import provision_roles
        roles = provision_roles(conn, client, stake_id, unit_id_by_name)
    except Exception as exc:  # noqa: BLE001 — never fail the data sync over role provisioning
        logger.warning("role provisioning skipped for stake %s: %s", stake_id, exc)
        roles = None
    db.touch_stake_synced(conn, stake_id)
    return {"stake": ctx.unit_name, "stake_unit": ctx.unit_number, "stake_id": stake_id,
            "units": len(unit_id_by_number), "members_written": written, "roles": roles}


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
