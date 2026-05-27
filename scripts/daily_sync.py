"""
Daily sync orchestrator — the entrypoint the GitHub Actions cron runs.

For each stake it: ensures an LCR session, builds the access-aware covenant-path
report (with the incremental cache), then optionally pushes to Google Sheets and/or
Supabase. Two modes:

  self       — use this account's own LCR credentials (LCR_LOGIN/LCR_PASSWORD via the
               headless okta_login). One stake = the runner's stake.
  delegated  — iterate the encrypted per-stake grants (token_store); mint each stake's
               session (delegated_login), which re-verifies the authorizing leader's
               calling and auto-revokes on change. Many stakes.

  default mode = delegated if any grants exist, else self.

  python scripts/daily_sync.py --with-profile --sheets --supabase
  python scripts/daily_sync.py --mode self --no-supabase

Each feature is independent and lazily imported, so the job runs with whatever
secrets are configured (e.g. Sheets-only until Supabase creds land).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from lcr_client.logging_setup import get_logger

logger = get_logger()
TEST_SPREADSHEET_ID = "1JD9EC_SafClaY8cOcRzi5ZI4fUnjOxa-xXJA0lxgJaA"


def _sync_one(args) -> dict:
    """Report + export + optional Sheets/Supabase for the CURRENT session/stake."""
    from lcr_client import LcrClient
    from lcr_client.access import covenant_path_access
    from covenant_path.profile_cache import ProfileCache
    from covenant_path.report import build_stake_report, export

    client = LcrClient()
    access = covenant_path_access(client)
    cache = ProfileCache(max_age_days=args.cache_max_age_days, enabled=not args.no_cache)
    rows = build_stake_report(client, with_profile=args.with_profile, access=access,
                              cache=cache, verbose=args.verbose)
    dicts = [asdict(r) for r in rows]
    export(rows, access=access, with_profile=args.with_profile)
    failed_units = set(access.get("_run_stats", {}).get("failed_units", []))
    if failed_units:
        logger.warning("units that failed to scrape (rows preserved in Sheets): %s", failed_units)
    result = {"members": len(dicts), "failed_units": sorted(failed_units),
              "sheets": None, "supabase": None}

    if args.sheets:
        from sheets_sync.service import SheetsSync
        # preserve_units keeps failed units' existing rows (Sheets is a full-replace);
        # Supabase upserts are non-destructive so stale rows simply persist there.
        summary = SheetsSync(args.spreadsheet_id).sync(dicts, preserve_units=failed_units)
        result["sheets"] = summary
        logger.info("sheets: %s", summary)
    if args.supabase:
        from backend import db, sync as bsync
        conn = db.connect()
        try:
            result["supabase"] = bsync.sync_stake(client, dicts, conn)
        finally:
            conn.close()
        logger.info("supabase: %s", result["supabase"])
    return result


def run_self(args) -> int:
    from lcr_client import okta_login
    logger.info("daily_sync mode=self: minting session via okta_login")
    okta_login.login()
    res = _sync_one(args)
    print(f"[+] self sync: {res['members']} members "
          f"(sheets={'ok' if res['sheets'] else 'off'}, supabase={'ok' if res['supabase'] else 'off'})")
    return 0


def run_delegated(args) -> int:
    from lcr_client import delegated_login, token_store
    grants = [g for g in token_store.list_grants() if not g.get("revoked")]
    if not grants:
        logger.warning("no delegated grants; nothing to sync (onboard a stake first)")
        return 0
    failures = 0
    for g in grants:
        stake = g["stake_unit"]
        try:
            delegated_login.mint_session(stake)   # re-verifies calling, auto-revokes on change
            res = _sync_one(args)
            print(f"[+] stake {stake} ({g.get('stake_name')}): {res['members']} members")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.error("stake %s sync failed: %s", stake, exc)
            print(f"[!] stake {stake} failed: {exc}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily covenant-path sync")
    ap.add_argument("--mode", choices=["self", "delegated", "auto"], default="auto")
    ap.add_argument("--with-profile", action="store_true", default=True)
    ap.add_argument("--no-profile", dest="with_profile", action="store_false")
    ap.add_argument("--sheets", action="store_true", help="push to Google Sheets")
    ap.add_argument("--supabase", action="store_true", help="push to Supabase")
    ap.add_argument("--spreadsheet-id", default=TEST_SPREADSHEET_ID)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--cache-max-age-days", type=float, default=7.0)
    ap.add_argument("--quiet", dest="verbose", action="store_false", default=True)
    args = ap.parse_args()

    mode = args.mode
    if mode == "auto":
        from lcr_client import token_store
        mode = "delegated" if [g for g in token_store.list_grants() if not g.get("revoked")] else "self"
    logger.info("daily_sync starting (mode=%s, sheets=%s, supabase=%s)",
                mode, args.sheets, args.supabase)
    return run_delegated(args) if mode == "delegated" else run_self(args)


if __name__ == "__main__":
    sys.exit(main())
