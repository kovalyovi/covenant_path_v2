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

  auto       — (default) run the self baseline THEN delegated for the other stakes. With
               --no-self-baseline (or env DELEGATED_ONLY=1) it skips the self pass and syncs
               EVERY stake — including the operator's own — via its delegated credential (#79).

  python scripts/daily_sync.py --with-profile --sheets --supabase
  python scripts/daily_sync.py --mode self --no-supabase
  python scripts/daily_sync.py --no-self-baseline --supabase   # delegated-only cutover (#79)

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
    # Mark the stake "running" before the long scrape so the app can show a syncing banner
    # (and a brand-new stake gets a row immediately). Best-effort — never block the sync.
    if args.supabase:
        try:
            from backend import db as _db
            ctx = client.user_context()
            _c = _db.connect()
            _sid = _db.upsert_stake(_c, ctx.unit_number, ctx.unit_name)
            _db.set_sync_state(_c, _sid, "running")
            _c.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not mark sync running: %s", exc)
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
        # Per-stake spreadsheet (#1/#2): each stake writes to its OWN sheet, shared read-only with
        # its leadership. Falls back to the configured --spreadsheet-id if a per-stake sheet can't
        # be created (e.g. Drive API not yet enabled).
        sheet_id = _resolve_stake_sheet(client, args)
        if not sheet_id:
            logger.info("no per-stake sheet for this stake; skipping Sheets (Supabase still synced)")
        else:
            # preserve_units keeps failed units' existing rows (Sheets is a full-replace);
            # Supabase upserts are non-destructive so stale rows simply persist there.
            summary = SheetsSync(sheet_id).sync(dicts, preserve_units=failed_units)
            result["sheets"] = summary
            logger.info("sheets[%s]: %s", sheet_id, summary)
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


def run_self(args) -> int | None:
    """Sync the LCR_LOGIN account's own stake. Returns that stake's unit number (so the
    delegated pass can skip it and avoid a double sync)."""
    from lcr_client import okta_login
    logger.info("daily_sync mode=self: minting session via okta_login")
    okta_login.login()
    args._allow_master = True  # only the operator's own stake may fall back to the master sheet (#3)
    res = _sync_one(args)
    print(f"[+] self sync: {res['members']} members "
          f"(sheets={'ok' if res['sheets'] else 'off'}, supabase={'ok' if res['supabase'] else 'off'})")
    return (res.get("supabase") or {}).get("stake_unit")


def _resolve_stake_sheet(client, args) -> str:
    """Per-stake spreadsheet id: reuse the stored one, else create + share it read-only with the
    stake's leadership (user_roles emails) + the credential provider, and store it. Falls back to
    the configured --spreadsheet-id (the shared master) when Supabase isn't configured or the Drive
    API can't create a sheet — so the sync never fails over a sheet problem."""
    if not os.getenv("SUPABASE_DB_URL"):
        return args.spreadsheet_id
    try:
        from backend import db
        from sheets_sync import service as sheets_service
        ctx = client.user_context()
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("select id, spreadsheet_id, spreadsheet_shared from stakes "
                            "where unit_number=%s", (ctx.unit_number,))
                row = cur.fetchone()
            stake_id = row[0] if row else db.upsert_stake(conn, ctx.unit_number, ctx.unit_name)
            sid = row[1] if row else None
            shared = set(row[2] or []) if row and row[2] else set()
            with conn.cursor() as cur:
                cur.execute("select distinct lower(email) from user_roles "
                            "where stake_id=%s and email is not null", (stake_id,))
                emails = {r[0] for r in cur.fetchall()}
                cur.execute("select lower(principal_email) from stake_credentials "
                            "where stake_id=%s and principal_email is not null", (stake_id,))
                emails |= {r[0] for r in cur.fetchall()}
            if not sid:
                sid = sheets_service.create_and_share_spreadsheet(
                    f"Covenant Path — {ctx.unit_name}", sorted(emails))
                with conn.cursor() as cur:
                    cur.execute("update stakes set spreadsheet_id=%s, spreadsheet_shared=%s where id=%s",
                                (sid, sorted(emails), stake_id))
                conn.commit()
                logger.info("created per-stake spreadsheet for %s (%s): %s",
                            ctx.unit_name, ctx.unit_number, sid)
            elif emails - shared:
                sheets_service.share_spreadsheet(sid, sorted(emails - shared))
                with conn.cursor() as cur:
                    cur.execute("update stakes set spreadsheet_shared=%s where id=%s",
                                (sorted(emails), stake_id))
                conn.commit()
            return sid
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — never fail the sync over the sheet target
        # The master sheet is reserved for the OPERATOR's own stake (#3: don't mingle other stakes
        # into it). Only the self path sets _allow_master; a delegated stake with no own sheet skips
        # Sheets entirely (Supabase still gets its data) rather than writing into the master.
        if getattr(args, "_allow_master", False):
            logger.warning("per-stake sheet unavailable (%s); using the operator's master sheet", exc)
            return args.spreadsheet_id
        logger.warning("per-stake sheet unavailable (%s); skipping Sheets for this stake "
                       "(master is reserved for the operator's stake)", exc)
        return ""


def _mint_and_sync(args, st: dict) -> None:
    """Mint ONE stake's LCR session from its stored credential and sync it. Raises on failure
    (the caller decides whether one bad stake stops the run). Isolated per stake — no other
    stake's data is touched."""
    args._allow_master = False  # a delegated stake never writes into the operator's master sheet (#3)
    from backend import credentials, db
    from lcr_client import okta_login
    conn = db.connect()
    try:
        cred = credentials.get_credential(conn, st["stake_id"])
    finally:
        conn.close()
    if not cred or cred.get("revoked"):
        raise RuntimeError("no active credential for this stake")
    session = okta_login.session_from_cookies(cred["cookies"])
    # Three-tier session renewal: (1) stored LCR appSession (outlives Okta), (2) Okta re-SSO,
    # (3) OAuth refresh_token → silent SSO. Only fail once all three are exhausted.
    try:
        okta_login.verify_session(session)
    except Exception:  # noqa: BLE001
        try:
            okta_login.establish_lcr_session(session)
            okta_login.verify_session(session)
        except Exception:  # noqa: BLE001
            if not okta_login.try_refresh_session(session, cred.get("refresh_token")):
                raise
    okta_login.write_storage_state(session, okta_login.DEFAULT_STORAGE_STATE)
    res = _sync_one(args)
    print(f"[+] {st['name']} ({st['unit_number']}): {res['members']} members synced")


def list_stake_units() -> list[int]:
    """Credentialed stake unit numbers — the CI matrix fans out one isolated job per entry."""
    from backend import credentials, db
    conn = db.connect()
    try:
        return [s["unit_number"] for s in credentials.list_active_stakes(conn) if s.get("unit_number")]
    finally:
        conn.close()


def run_one_stake(args, unit: int) -> int:
    """Sync exactly ONE stake by unit number — the per-stake isolated job. Uses that stake's
    delegated credential; falls back to self (LCR_LOGIN) only if this is the operator's own stake
    and it has no stored credential."""
    from backend import credentials, db, observability as obs
    args.supabase = True
    args._correlation_id = obs.new_correlation_id()  # ties this stake's events end-to-end
    conn = db.connect()
    try:
        st = next((s for s in credentials.list_active_stakes(conn) if s.get("unit_number") == unit), None)
    finally:
        conn.close()
    if st:
        try:
            with obs.span("sync.stake", correlation_id=args._correlation_id, stake=unit):
                _mint_and_sync(args, st)
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.error("stake %s delegated sync failed: %s", unit, exc)
            # Self-heal: if the operator account (LCR_LOGIN) is available and this is THEIR stake, a
            # stale delegated credential shouldn't strand the stake — log in fresh and sync. We only
            # claim recovery if the self pass actually synced the requested unit (so a non-operator
            # stake's failure isn't masked by syncing the operator's own stake instead).
            if os.getenv("LCR_LOGIN"):
                try:
                    from lcr_client import okta_login
                    logger.info("attempting self-baseline (LCR_LOGIN) recovery for stake %s", unit)
                    okta_login.login()
                    args._allow_master = True
                    recovered = (_sync_one(args).get("supabase") or {}).get("stake_unit")
                    if recovered == unit:
                        logger.info("stake %s recovered via the self baseline", unit)
                        return 0
                    logger.warning("self baseline synced %s, not %s — delegated credential is stale",
                                   recovered, unit)
                except Exception as exc2:  # noqa: BLE001
                    logger.error("self-baseline recovery also failed: %s", exc2)
            print(f"[!] stake {unit} failed (re-authorize may be needed): {exc}")
            return 1
        finally:
            obs.flush()
    logger.info("no delegated credential for unit %s; falling back to self (LCR_LOGIN)", unit)
    from lcr_client import okta_login
    okta_login.login()
    args._allow_master = True  # operator's own stake → may use the master sheet (#3)
    self_unit = (_sync_one(args).get("supabase") or {}).get("stake_unit")
    if self_unit != unit:
        logger.warning("self stake is %s, not the requested %s", self_unit, unit)
    return 0


def run_delegated(args, skip_unit: int | None = None) -> int:
    """Multi-stake (legacy single-process path): sync every onboarded stake in one run. The CI
    matrix now prefers one isolated --stake job per stake; this remains for local/manual use.
    One bad stake doesn't stop the others. [skip_unit] avoids double-syncing the self pass's stake."""
    from backend import credentials, db
    args.supabase = True
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
        if skip_unit is not None and st.get("unit_number") == skip_unit:
            logger.info("delegated: skipping %s (already synced by self baseline)", st.get("name"))
            continue
        try:
            _mint_and_sync(args, st)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            logger.error("stake %s (%s) sync failed: %s", st.get("name"), st.get("unit_number"), exc)
            print(f"[!] {st.get('name')} failed (re-authorize may be needed): {exc}")
    return 1 if failures else 0


def _should_run_now() -> tuple[bool, str]:
    """Scheduled runs proceed only at the intended ET times (7:00 daily, 8:20 Thursday), so
    DST shifts never move the run off its morning slot. Manual workflow_dispatch always runs.

    The workflow fires candidate UTC crons for both EST and EDT; this gate keeps the one that
    lands on the right ET wall-clock time and skips the duplicate.
    """
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return True, "manual run"
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception as exc:  # noqa: BLE001  — never let a tz lookup block the daily sync
        return True, f"tz lookup failed ({exc}); running anyway"
    if now.hour == 7:
        return True, f"daily 7:00 ET ({now:%a %H:%M %Z})"
    if now.weekday() == 3 and now.hour == 8 and 15 <= now.minute <= 30:
        return True, f"Thursday 8:20 ET ({now:%a %H:%M %Z})"
    return False, f"off-target ET time ({now:%a %H:%M %Z})"


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
    ap.add_argument("--no-self-baseline", dest="self_baseline", action="store_false", default=True,
                    help="auto mode: skip the LCR_LOGIN self pass and sync EVERY stake (including "
                         "the operator's own) via its delegated credential. Use after migrating "
                         "your own stake to delegated (#79). Env DELEGATED_ONLY=1 has the same effect.")
    ap.add_argument("--stake", type=int, metavar="UNIT",
                    help="sync exactly ONE stake by unit number — the per-stake isolated CI job")
    ap.add_argument("--list-stakes", action="store_true",
                    help="print a JSON array of credentialed stake unit numbers (for the CI matrix) "
                         "and exit; honors the schedule gate (prints [] off-target)")
    ap.add_argument("--only", type=int, metavar="UNIT", default=None,
                    help="with --list-stakes, emit only this stake's unit (the OPS per-stake dispatch)")
    ap.add_argument("--quiet", dest="verbose", action="store_false", default=True)
    args = ap.parse_args()
    # Env switch mirrors --no-self-baseline so the GitHub workflow can flip the cutover without
    # editing the command line (set repo variable DELEGATED_ONLY=1).
    if os.getenv("DELEGATED_ONLY", "").lower() in ("1", "true", "yes"):
        args.self_baseline = False

    run_ok, why = _should_run_now()
    logger.info("schedule gate: %s", why)

    # The CI matrix's prepare step: emit the stakes to sync (empty off the scheduled window so no
    # per-stake jobs spawn). A manual workflow_dispatch always lists.
    if args.list_stakes:
        import json
        stakes = list_stake_units() if run_ok else []
        if args.only is not None:  # OPS per-stake dispatch: emit just this one (if credentialed)
            stakes = [u for u in stakes if u == args.only]
        print(json.dumps(stakes))
        return 0

    if not run_ok:
        print(f"[skip] schedule gate: {why}")
        return 0

    # A single isolated per-stake job (the matrix entry). Runs unconditionally — the prepare step
    # already applied the schedule gate when it chose to emit this stake.
    if args.stake:
        logger.info("daily_sync starting (single stake %s)", args.stake)
        return run_one_stake(args, args.stake)

    mode = args.mode
    if mode == "auto":
        # Two shapes of auto mode:
        #  • self_baseline (default, Decision B): run the LCR_LOGIN self pass for the operator's
        #    stake + shared self-healing (calling cache / action-id repair), THEN delegated for the
        #    other enrolled stakes (skipping the operator's so it isn't synced twice).
        #  • delegated-only (--no-self-baseline / DELEGATED_ONLY=1, the #79 cutover): the operator
        #    migrated their own stake to a delegated credential, so EVERY stake — including theirs —
        #    syncs via its credential. Self-healing still happens during those delegated scrapes
        #    (it's shared global state). LCR_LOGIN is no longer required (kept only as a manual
        #    fallback: unset the flag to restore the self baseline).
        logger.info("daily_sync starting (mode=auto: %s)",
                    "delegated-only" if not args.self_baseline else "self baseline + delegated")
        self_unit = None
        if args.self_baseline:
            try:
                self_unit = run_self(args)
            except Exception as exc:  # noqa: BLE001 — a self failure must not stop delegated stakes
                logger.error("self baseline sync failed: %s", exc)
        rc = 0
        if os.getenv("SUPABASE_DB_URL"):
            try:
                from backend import credentials, db
                conn = db.connect()
                has = bool(credentials.list_active_stakes(conn))
                conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not check Supabase credentials: %s", exc)
                has = False
            if has:
                rc = run_delegated(args, skip_unit=self_unit)  # skip_unit is None in delegated-only
            elif not args.self_baseline:
                logger.warning("delegated-only set but no active credentials — nothing was synced")
    elif mode == "delegated":
        logger.info("daily_sync starting (mode=delegated)")
        rc = run_delegated(args)
    else:
        logger.info("daily_sync starting (mode=self)")
        run_self(args)
        rc = 0

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
