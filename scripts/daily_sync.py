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
                              cache=cache, verbose=args.verbose,
                              only_unit=getattr(args, "unit", None))
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
            # N7: the spreadsheet is a master list → omit investigators (not yet baptized); they're
            # tracked in-app under Being-Taught, not in the flat sheet.
            sheet_rows = [d for d in dicts if d.get("kind") != "investigator"]
            summary = SheetsSync(sheet_id).sync(sheet_rows, preserve_units=failed_units)
            result["sheets"] = summary
            logger.info("sheets[%s]: %s", sheet_id, summary)
            _sync_ward_sheets(client, dicts)  # #5b: per-ward sheets (ward-only data + ward recipients)
    if args.supabase:
        from backend import db, sync as bsync
        conn = db.connect()
        try:
            failed_unit_numbers = access.get("_run_stats", {}).get("failed_unit_numbers", [])
            result["supabase"] = bsync.sync_stake(
                client, dicts, conn, failed_unit_numbers=failed_unit_numbers,
                only_unit=getattr(args, "unit", None))
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
                    "field_staleness": db.field_staleness_summary(conn, result["supabase"]["stake_id"]),
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


def _service_account_email() -> str | None:
    """The Sheets service account's email — to share an OAuth-Drive sheet with it so it can write."""
    try:
        import json
        from sheets_sync.service import _service_account_file
        return json.load(open(_service_account_file(), encoding="utf-8")).get("client_email")
    except Exception:  # noqa: BLE001
        return None


def _sync_ward_sheets(client, dicts) -> None:
    """#5b: when sheet generation is enabled for a stake, also maintain a SEPARATE spreadsheet per
    ward/branch — that ward's data only, shared with the ward's leadership + assigned missionaries
    PLUS the stake-level recipients (stake leaders see every ward). Recipients are recomputed from
    current callings each run and reconciled (add new + REVOKE released, with notifications). Fully
    guarded — a sheet problem must never affect the Supabase sync."""
    if not os.getenv("SUPABASE_DB_URL"):
        return
    try:
        import psycopg2.extras
        from backend import db, sheet_access
        from sheets_sync import service as sheets_service
        from sheets_sync.service import SheetsSync
        ctx = client.user_context()
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("select id, sheets_enabled, ward_spreadsheets, missionaries "
                            "from stakes where unit_number=%s", (ctx.unit_number,))
                row = cur.fetchone()
                if not (row and row[1]):  # no stake row / sheets disabled → nothing to do
                    return
                stake_id, ward_sheets, missionaries = row[0], (row[2] or {}), (row[3] or {})
                cur.execute("""select lower(ur.email), ur.calling_name, ur.role, ur.unit_id, u.name
                               from user_roles ur left join units u on u.id = ur.unit_id
                               where ur.stake_id=%s and ur.email is not null""", (stake_id,))
                role_rows = [{"email": r[0], "calling_name": r[1], "role": r[2],
                              "unit_id": r[3], "unit_name": r[4]} for r in cur.fetchall()]
            rec = sheet_access.compute_recipients(role_rows, missionaries)
            baptized = [d for d in dicts if d.get("kind") != "investigator"]
            updated = dict(ward_sheets)
            for unit_id, emails in rec["wards"].items():
                if not emails:
                    continue
                ward_name = rec["ward_names"].get(unit_id) or unit_id
                ward_members = [d for d in baptized
                                if (d.get("unit") or d.get("unit_name")) == ward_name]
                wsid = ward_sheets.get(unit_id)
                try:
                    if not wsid:
                        wsid = sheets_service.create_and_share_spreadsheet(
                            f"Covenant Path — {ward_name}", sorted(emails), notify=True)
                        updated[unit_id] = wsid
                    else:
                        sheets_service.reconcile_viewers(wsid, emails, notify=True)
                    SheetsSync(wsid).sync(ward_members)
                except Exception as exc:  # noqa: BLE001 — one ward's sheet never blocks the rest
                    logger.warning("ward sheet for %s (%s) failed: %s", ward_name, unit_id, exc)
            if updated != ward_sheets:
                with conn.cursor() as cur:
                    cur.execute("update stakes set ward_spreadsheets=%s where id=%s",
                                (psycopg2.extras.Json(updated), stake_id))
                conn.commit()
            logger.info("ward sheets maintained for %s: %d ward(s)", ctx.unit_name, len(rec["wards"]))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ward sheets skipped: %s", exc)


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
                cur.execute("select id, spreadsheet_id, spreadsheet_shared, gdrive_token, "
                            "gdrive_file_id, sheets_enabled from stakes where unit_number=%s",
                            (ctx.unit_number,))
                row = cur.fetchone()
            # #5b: sheet generation is opt-in per stake (Settings toggle, default off — leaders
            # consent). Disabled → create/maintain nothing (the data already lives in the app).
            if not (row and row[5]):
                logger.info("sheets disabled for %s (%s); skipping Sheets", ctx.unit_name, ctx.unit_number)
                return None
            stake_id = row[0]
            sid = row[1]
            shared = set(row[2] or []) if row[2] else set()
            gdrive_token = row[3]
            gdrive_file_id = row[4]
            with conn.cursor() as cur:
                # #5: compute sheet recipients from CURRENT callings (not "anyone with a role"): the
                # stake sheet (all units' data) goes only to stake-level leadership. Recomputed every
                # run, so a released leader / rotated missionary / calling that lost access drops off
                # (reconcile_viewers removes them below).
                cur.execute("""select lower(ur.email), ur.calling_name, ur.role, ur.unit_id, u.name
                               from user_roles ur left join units u on u.id = ur.unit_id
                               where ur.stake_id=%s and ur.email is not null""", (stake_id,))
                role_rows = [{"email": r[0], "calling_name": r[1], "role": r[2],
                              "unit_id": r[3], "unit_name": r[4]} for r in cur.fetchall()]
                cur.execute("select lower(principal_email) from stake_credentials "
                            "where stake_id=%s and principal_email is not null", (stake_id,))
                provider_emails = {r[0] for r in cur.fetchall()}
                cur.execute("select missionaries from stakes where id=%s", (stake_id,))
                mrow = cur.fetchone()
            from backend import sheet_access
            recipients = sheet_access.compute_recipients(
                role_rows, mrow[0] if mrow and mrow[0] else {})
            # The stake sheet holds ALL units' data. Full per-ward ISOLATION needs a separate sheet
            # per ward in the stake's OAuth Drive (the service account can't create files — 0 storage,
            # the documented M7 reason); that's the next step. For now share the stake sheet with all
            # sheet-eligible leadership (stake + ward + assigned missionaries) — NOT the old "anyone
            # with any role" — so nobody loses access, and reconcile_viewers still REVOKES anyone no
            # longer eligible (released leaders, rotated missionaries, ward clerks who used to slip in).
            emails = set(recipients["stake"]) | provider_emails
            for _ward_emails in recipients["wards"].values():
                emails |= _ward_emails
            # M7: a stake that connected Google Drive OWNS its sheet in the leader's Drive — the
            # service account can't create files (0 storage), so OAuth provides the create + the SA
            # (shared in) writes the data. Takes precedence over the service-account/master paths.
            if gdrive_token:
                from backend.auth_broker import google_oauth
                from sheets_sync import oauth_drive
                try:
                    access = google_oauth.access_token_for(gdrive_token)
                    fid = oauth_drive.ensure_sheet(
                        access, f"Covenant Path — {ctx.unit_name}", _service_account_email(),
                        sorted(emails), gdrive_file_id)
                    if fid != gdrive_file_id:
                        with conn.cursor() as cur:
                            cur.execute("update stakes set gdrive_file_id=%s where id=%s", (fid, stake_id))
                        conn.commit()
                    logger.info("using OAuth-Drive sheet for %s (%s): %s", ctx.unit_name,
                                ctx.unit_number, fid)
                    return fid
                except Exception as exc:  # noqa: BLE001 — stale/revoked Drive token: nudge a reconnect
                    # Flag the connection as needing attention (clear gdrive_connected_at; KEEP the
                    # token) so the app's Sync-settings Drive section shows "Connect" again and the
                    # leader knows to reconnect — then fall through to the service-account/master
                    # path so this run's Sheets write still happens (Supabase is unaffected regardless).
                    logger.warning("OAuth-Drive token for %s (%s) failed (%s); flagging reconnect, "
                                   "falling back to service-account sheet", ctx.unit_name,
                                   ctx.unit_number, exc)
                    try:
                        with conn.cursor() as cur:
                            cur.execute("update stakes set gdrive_connected_at=null where id=%s",
                                        (stake_id,))
                        conn.commit()
                    except Exception:  # noqa: BLE001
                        conn.rollback()
            if not sid:
                sid = sheets_service.create_and_share_spreadsheet(
                    f"Covenant Path — {ctx.unit_name}", sorted(emails), notify=True)
                with conn.cursor() as cur:
                    cur.execute("update stakes set spreadsheet_id=%s, spreadsheet_shared=%s where id=%s",
                                (sid, sorted(emails), stake_id))
                conn.commit()
                logger.info("created per-stake spreadsheet for %s (%s): %s",
                            ctx.unit_name, ctx.unit_number, sid)
            elif set(emails) != shared:
                # #5: reconcile to EXACTLY the current stake recipients — add new leaders (notified),
                # REMOVE released ones (replaces the old add-only share, which never revoked).
                sheets_service.reconcile_viewers(sid, emails, notify=True)
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
    # #10: periodically re-verify the authorizing leader's calling STILL grants covenant-path access —
    # this runs every sync, so a released/reassigned leader's stored credential is caught and revoked
    # (the app then shows "sync paused — re-enroll" and stops trusting a now-ineligible session).
    _revoke_if_ineligible(st)
    res = _sync_one(args)
    print(f"[+] {st['name']} ({st['unit_number']}): {res['members']} members synced")


def _revoke_if_ineligible(st: dict) -> None:
    """#10: confirm the stored credential's calling can still see covenant-path data; revoke it if not.

    CONSERVATIVE: only revoke when we successfully READ the runner's callings AND none of them grant
    access (and it's not a stake-stewardship always-allowed calling). If we can't read the callings
    (transient/auth hiccup), we do NOT revoke — a false revoke would needlessly strand a good stake.
    Raises after revoking so the run skips syncing with the ineligible session."""
    from lcr_client import LcrClient
    from lcr_client.access import covenant_path_access
    from backend import credentials, db, onboarding
    from backend.roles import _calling_always_allowed
    try:
        access = covenant_path_access(LcrClient())  # reads the storage_state just written for this stake
        positions = access.get("runner_positions") or []
        if not positions:
            return  # couldn't determine callings → never revoke on an inconclusive read
        authorized = (bool(access.get("can_pull_all")) or onboarding.access_rank(access) > 0
                      or any(_calling_always_allowed(p.get("name")) for p in positions))
        if authorized:
            return
    except Exception as exc:  # noqa: BLE001 — an eligibility-check error must not revoke or stop the run
        logger.warning("eligibility re-check skipped for %s (%s): %s",
                       st.get("name"), st.get("unit_number"), exc)
        return
    # Definitive: callings were read and none grant access → revoke + stop.
    conn = db.connect()
    try:
        credentials.revoke(conn, st["stake_id"], reason="authorizing calling no longer grants covenant-path access")
    finally:
        conn.close()
    logger.warning("revoked credential for stake %s (%s): authorizing calling lost covenant-path access",
                   st.get("name"), st.get("unit_number"))
    raise RuntimeError("authorizing leader no longer has covenant-path access; credential revoked")


def _stake_schedules(conn) -> dict[str, dict]:
    """stake_id -> {hour, paused} from stake_settings (in-app schedule, migration 0030). Best-effort:
    a missing row / missing table / any error means "default" (7:00 ET, not paused) so the sync never
    breaks over the schedule feature."""
    out: dict[str, dict] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("select stake_id, sync_hour_et, sync_paused from stake_settings")
            for sid, hour, paused in cur.fetchall():
                out[str(sid)] = {"hour": hour if hour is not None else 7, "paused": bool(paused)}
    except Exception as exc:  # noqa: BLE001 — schedule is optional; default everyone on failure
        logger.warning("stake schedule read skipped (using 7:00 ET default): %s", exc)
        conn.rollback()
    return out


def _et_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def _stake_last_synced(conn) -> dict[str, object]:
    """stake_id -> last successful sync time (stakes.last_synced_at, a tz-aware timestamptz, or
    None). Best-effort: any error means "treat everyone as never-synced" so a read problem can
    only ever cause an extra sync, never a missed one."""
    out: dict[str, object] = {}
    try:
        with conn.cursor() as cur:
            cur.execute("select id, last_synced_at from stakes")
            for sid, ts in cur.fetchall():
                out[str(sid)] = ts
    except Exception as exc:  # noqa: BLE001
        logger.warning("last-synced read skipped (treating all as due): %s", exc)
        conn.rollback()
    return out


def _due_today(now, hour: int, last_synced) -> bool:
    """Is a stake due to sync? True once the ET wall clock reaches its configured `hour` and it
    hasn't already synced since that hour opened *today*.

    This replaces an exact `now.hour == configured_hour` match, which was fragile: GitHub
    frequently DELAYS scheduled cron dispatch (observed 10–50 min, worst at the top of the hour),
    so the one fire that matched the hour often arrived after the old :00–:05 gate and the whole
    day was skipped. With a due-window check, *whichever* hourly fire actually lands at/after the
    window picks the stake up, a fire that slips across the hour boundary still counts, and
    last_synced_at keeps it to exactly one run/day (a failed run simply stays due and retries)."""
    if now.hour < hour:
        return False
    window_open = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if last_synced is None:
        return True
    ls = last_synced
    if getattr(ls, "tzinfo", None) is None:  # a naive timestamp → assume the ET wall clock
        ls = ls.replace(tzinfo=now.tzinfo)
    return ls < window_open


def list_stake_units() -> list[int]:
    """Credentialed stake unit numbers the CI matrix should sync RIGHT NOW. Honors each stake's
    in-app schedule (stake_settings.sync_hour_et / sync_paused, migration 0030):
      • a scheduled run emits a stake once it is DUE — i.e. the current ET hour has reached the
        stake's configured hour (default 7) and it hasn't synced since that hour today (see
        _due_today) — skipping paused stakes. This tolerates GitHub's variable cron-dispatch delay;
      • the Thursday 8:20-ET pre-meeting pulse and any manual workflow_dispatch emit every active,
        non-paused stake regardless of hour.
    Defaults preserve today's behavior (7:00 ET) for stakes with no settings row."""
    from backend import credentials, db
    conn = db.connect()
    try:
        stakes = [s for s in credentials.list_active_stakes(conn) if s.get("unit_number")]
        sched = _stake_schedules(conn)
        scheduled = os.getenv("GITHUB_EVENT_NAME") == "schedule"
        if not scheduled:
            # manual run: every non-paused stake (the operator explicitly asked for it)
            return [s["unit_number"] for s in stakes if not sched.get(str(s["stake_id"]), {}).get("paused")]
        try:
            now = _et_now()
        except Exception as exc:  # noqa: BLE001 — no tzdata? don't strand the daily sync: run all non-paused
            logger.warning("ET time lookup failed (%s); emitting all non-paused stakes", exc)
            return [s["unit_number"] for s in stakes
                    if not sched.get(str(s["stake_id"]), {}).get("paused")]
        # Thursday 8:20-ET pre-meeting pulse: everyone active (not paused), regardless of last sync.
        thursday_pulse = now.weekday() == 3 and now.hour == 8 and 15 <= now.minute <= 30
        last = _stake_last_synced(conn)
        out = []
        for s in stakes:
            cfg = sched.get(str(s["stake_id"]), {})
            if cfg.get("paused"):
                continue
            if thursday_pulse:
                out.append(s["unit_number"])
                continue
            hour = cfg.get("hour", 7)
            if _due_today(now, hour, last.get(str(s["stake_id"]))):
                out.append(s["unit_number"])
        return out
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
                    from lcr_client import LcrClient, okta_login
                    logger.info("attempting self-baseline (LCR_LOGIN) recovery for stake %s", unit)
                    okta_login.login()
                    # The self baseline can ONLY sync the operator's OWN stake, so first check (one
                    # cheap user-context request) whether the requested stake is the operator's —
                    # otherwise skip the full scrape entirely instead of wasting ~8 min scraping the
                    # wrong stake before noticing (the stake-2155451 case in the logs).
                    op_unit = LcrClient().user_context().unit_number
                    if op_unit == unit:
                        args._allow_master = True
                        recovered = (_sync_one(args).get("supabase") or {}).get("stake_unit")
                        if recovered == unit:
                            logger.info("stake %s recovered via the self baseline", unit)
                            return 0
                    else:
                        logger.warning("self-baseline can't recover stake %s (operator account is %s) — "
                                       "delegated credential is stale; re-authorization needed", unit, op_unit)
                except Exception as exc2:  # noqa: BLE001
                    logger.error("self-baseline recovery also failed: %s", exc2)
            _alert_sync_failure(unit, str(exc))
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


def _alert_sync_failure(unit, reason: str) -> None:
    """Sync-failure alert: make a failed/stale stake VISIBLE (app + admin console + Axiom) so it gets
    re-authorized instead of silently going stale. Sets the stake's sync_state='error', records a
    diagnostic, emits an Axiom event, and best-effort emails the owner. Fully guarded — alerting must
    never change the run's exit status."""
    if not unit:
        return
    try:
        from backend import db, observability as obs
        stake_name = str(unit)
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("update stakes set sync_state='error' where unit_number=%s "
                            "returning id, name", (unit,))
                row = cur.fetchone()
            conn.commit()
            if row:
                stake_name = row[1] or stake_name
                db.insert_diagnostics(conn, row[0], "sync_error", {"unit": unit, "reason": reason[:400]})
        finally:
            conn.close()
        obs.event("sync.stake.failed", level="error", stake=int(unit), status="error", message=reason[:200])
        obs.flush()
        logger.error("SYNC ALERT: stake %s (%s) failed — %s", unit, stake_name, reason[:160])
        _email_owner_failure(stake_name, unit, reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sync-failure alert skipped (non-fatal): %s", exc)


def _email_owner_failure(stake_name: str, unit, reason: str) -> None:
    """Best-effort owner email about a failed stake sync. No-op if email isn't configured on the
    runner (set OWNER_EMAIL/REMINDER_OWNER + SMTP/RESEND on the sync job to enable)."""
    to = os.environ.get("OWNER_EMAIL") or os.environ.get("REMINDER_OWNER")
    if not to:
        return
    try:
        from backend.auth_broker import admin
        html = (f"<p>Daily sync <b>failed</b> for <b>{stake_name}</b> (unit {unit}).</p>"
                f"<p>Most likely the stake's delegated Church session expired — a leader must sign in "
                f"again with sync enabled to re-authorize it. Logged reason:</p>"
                f"<pre style='white-space:pre-wrap'>{reason[:500]}</pre>")
        admin._send_email(to, f"Covenant Path — sync failed for {stake_name}", html)
        logger.info("sync-failure email sent to owner")
    except Exception as exc:  # noqa: BLE001
        logger.debug("sync-failure email skipped: %s", exc)


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
            _alert_sync_failure(st.get("unit_number"), str(exc))
            print(f"[!] {st.get('name')} failed (re-authorize may be needed): {exc}")
    return 1 if failures else 0


def _should_run_now() -> tuple[bool, str]:
    """Top-level prepare gate. The workflow fires an hourly cron; `list_stake_units()` then decides
    WHICH stakes are actually due (per their in-app schedule + last_synced_at).

    We used to also reject a run here unless its ET wall-clock minute was :00–:05. That was the bug
    behind "the sync keeps skipping": GitHub routinely delays scheduled dispatch (observed 10–50 min
    past the hour, since the top of the hour is the most congested cron slot), so nearly every real
    scheduled fire landed outside the window and emitted an empty matrix — the daily sync effectively
    never ran on schedule. The per-stake due-window check in list_stake_units() is delay-robust, so
    this gate no longer filters on the minute: a scheduled fire always proceeds to the due check.
    Manual workflow_dispatch always runs."""
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return True, "manual run"
    try:
        now = _et_now()
        return True, f"scheduled fire {now:%a %H:%M %Z} (per-stake due check decides who runs)"
    except Exception as exc:  # noqa: BLE001  — never let a tz lookup block the daily sync
        return True, f"scheduled fire (tz lookup failed: {exc}); running anyway"


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
    ap.add_argument("--unit", type=int, metavar="UNIT", default=None,
                    help="with --stake, re-pull only this ONE ward/branch (OPS per-unit refetch, #19)")
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
