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
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from lcr_client.logging_setup import get_logger

logger = get_logger()
TEST_SPREADSHEET_ID = "1JD9EC_SafClaY8cOcRzi5ZI4fUnjOxa-xXJA0lxgJaA"


def _sync_one(args) -> dict:
    """Report + export + optional Sheets/Supabase for the CURRENT session/stake."""
    from lcr_client import LcrClient, metrics
    from lcr_client.access import covenant_path_access
    from covenant_path.profile_cache import ProfileCache
    from covenant_path.report import build_stake_report, export

    metrics.reset()  # isolate this stake's request metrics for the diagnostics row
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
            if args.photos:
                from backend import photos as photopipe
                s = result["supabase"]
                result["photos"] = photopipe.sync_photos_for_stake(
                    client, conn, s["stake_id"], s["stake_unit"])
                logger.info("photos: %s", result["photos"])
            # persist a diagnostics row: run stats + field parity + request metrics
            try:
                from lcr_client import metrics
                from covenant_path.report import _field_coverage
                db.insert_diagnostics(conn, result["supabase"]["stake_id"], "sync", {
                    "run_stats": access.get("_run_stats"),
                    "field_coverage": _field_coverage(dicts),
                    "requests": metrics.snapshot(),
                    "members": len(dicts),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("diagnostics write skipped: %s", exc)
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
    """Multi-stake: pull each onboarded stake's encrypted session from Supabase,
    re-mint its LCR session, and sync. One bad stake doesn't stop the others."""
    from backend import credentials, db
    from lcr_client import okta_login

    args.supabase = True  # delegated mode targets the central store
    conn = db.connect()
    try:
        stakes = credentials.list_active_stakes(conn)
    finally:
        conn.close()
    if not stakes:
        logger.warning("no active stake credentials in Supabase; onboard a stake first")
        return 0

    failures = 0
    for st in stakes:
        try:
            conn = db.connect()
            cred = credentials.get_credential(conn, st["stake_id"])
            conn.close()
            if not cred or cred.get("revoked"):
                continue
            session = okta_login.session_from_cookies(cred["cookies"])
            okta_login.establish_lcr_session(session)   # re-mint LCR cookies from Okta session
            okta_login.verify_session(session)
            okta_login.write_storage_state(session, okta_login.DEFAULT_STORAGE_STATE)
            res = _sync_one(args)
            print(f"[+] {st['name']} ({st['unit_number']}): {res['members']} members synced")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.error("stake %s (%s) sync failed: %s", st.get("name"), st.get("unit_number"), exc)
            print(f"[!] {st.get('name')} failed (re-authorize may be needed): {exc}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Daily covenant-path sync")
    ap.add_argument("--mode", choices=["self", "delegated", "auto"], default="auto")
    ap.add_argument("--with-profile", action="store_true", default=True)
    ap.add_argument("--no-profile", dest="with_profile", action="store_false")
    ap.add_argument("--sheets", action="store_true", help="push to Google Sheets")
    ap.add_argument("--supabase", action="store_true", help="push to Supabase")
    ap.add_argument("--photos", action="store_true",
                    help="also fetch member avatars into Supabase Storage (requires --supabase)")
    ap.add_argument("--spreadsheet-id", default=TEST_SPREADSHEET_ID)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--cache-max-age-days", type=float, default=7.0)
    ap.add_argument("--email", action="store_true",
                    help="after sync, send pending power-user invitations + daily digests (Resend)")
    ap.add_argument("--quiet", dest="verbose", action="store_false", default=True)
    args = ap.parse_args()

    mode = args.mode
    if mode == "auto":
        mode = "self"
        if os.getenv("SUPABASE_DB_URL"):
            try:
                from backend import credentials, db
                conn = db.connect()
                has = bool(credentials.list_active_stakes(conn))
                conn.close()
                mode = "delegated" if has else "self"
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not check Supabase credentials, defaulting to self: %s", exc)
    logger.info("daily_sync starting (mode=%s, sheets=%s, supabase=%s)",
                mode, args.sheets, args.supabase)
    rc = run_delegated(args) if mode == "delegated" else run_self(args)

    if args.email and os.getenv("SUPABASE_DB_URL"):
        from backend import db, mailer
        conn = db.connect()
        try:
            inv = mailer.send_pending_invitations(conn)
            dig = mailer.send_digests(conn)
            print(f"[email] sent {inv} invitations, {dig} digests")
        finally:
            conn.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
