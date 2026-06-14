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
from backend.sync import CredentialScopeMismatch  # data-integrity guard (ward-as-stake refusal)

logger = get_logger()
TEST_SPREADSHEET_ID = "1JD9EC_SafClaY8cOcRzi5ZI4fUnjOxa-xXJA0lxgJaA"


def _stake_unit_for_token(client) -> int | None:
    """The stake's unit number, used to key its stored Member Tools token. Reads user-context with a
    short retry (that endpoint is occasionally flaky). None if unreadable → we then mint a fresh token
    rather than look one up."""
    import time as _t
    for i in range(3):
        try:
            return client.user_context().unit_number
        except Exception as exc:  # noqa: BLE001
            logger.warning("user-context for token key failed (try %d): %s", i + 1, exc)
            if i < 2:
                _t.sleep(2 * (i + 1))
    return None


# --- Member Tools refresh token: Supabase-persisted (migration 0049) FIRST, local file store as a
#     dev fallback. Persisting to Supabase is what makes the 45-day token survive the CI runners. ----

class _TokenStoreUnavailable(RuntimeError):
    """The Member Tools token store could not be READ (DB error) — distinct from 'no token stored'.
    The caller must SKIP this run (retry next) rather than mint off a possibly-dead Okta session, which
    on failure would falsely flag the stake needs-reauth (#0 fix F5)."""


def _membertools_token(stake_unit: int | None) -> dict:
    """{refresh_token, minted_at} for a stake — Supabase first (persists across CI), else the local
    file store. Returns {} only when the store is READABLE but empty. Raises _TokenStoreUnavailable
    when the DB read FAILS *and* the file store has nothing either — so a transient DB hiccup can't
    masquerade as 'no token' and trigger a false re-mint / needs-reauth flag (#0 fix F5)."""
    if not stake_unit:
        return {}
    db_errored = False
    try:
        from backend import credentials, db
        conn = db.connect()
        try:
            sid = credentials.stake_id_for_unit(conn, stake_unit)
            tok = credentials.get_membertools_refresh(conn, sid) if sid else None
            if tok:
                return tok
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — DB hiccup: try the file store, but REMEMBER it failed
        db_errored = True
        logger.warning("Member Tools token DB read FAILED for stake %s: %s", stake_unit, exc)
    try:
        from lcr_client import token_store
        ft = token_store.get_membertools_token(stake_unit) or {}
    except Exception:  # noqa: BLE001
        ft = {}
    if ft:
        return ft
    if db_errored:
        raise _TokenStoreUnavailable(
            f"stake {stake_unit}: Member Tools token store unreadable (DB error) — skipping this run "
            f"to avoid a false re-mint")
    return {}


def _save_membertools_token(stake_unit: int, refresh_token: str) -> None:
    """Persist a freshly-minted Member Tools refresh token to BOTH Supabase (durable, CI-surviving)
    and the local file store (dev). Best-effort each."""
    try:
        from backend import credentials, db
        conn = db.connect()
        try:
            sid = credentials.stake_id_for_unit(conn, stake_unit)
            if sid:
                credentials.save_membertools_refresh(conn, sid, refresh_token)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Member Tools token DB save skipped for stake %s: %s", stake_unit, exc)
    try:
        from lcr_client import token_store
        token_store.save_membertools_token(stake_unit, refresh_token)
    except Exception:  # noqa: BLE001
        pass


def _membertools_access_token(client, stake_unit: int | None) -> str | None:
    """Get a Member Tools /api/v5/sync bearer for this stake, preferring the 45-day refresh token
    (no Okta session needed) over a fresh mint:
      1. a stored refresh token (Supabase, then file) → membertools.refresh() — the steady state;
      2. on a 45-day-wall RefreshTokenExpired, clear it and fall through;
      3. else mint off the LIVE Okta session (only works on a fresh login / right after enroll), and
         PERSIST the new 45-day refresh token so step 1 carries the next 45 days.
    Extracted so the refresh-vs-mint decision is unit-testable in isolation."""
    from lcr_client import membertools
    stored = _membertools_token(stake_unit)
    if stored.get("refresh_token"):
        # STEADY STATE: renew the bearer off the stored 45-day token — NO Okta session, NO login, NO
        # fallback. This is the path a healthy enrolled stake takes every day.
        logger.info("stake %s: renewing the Member Tools bearer off the stored 45-day refresh token "
                    "(no Okta session needed)", stake_unit)
        try:
            renewed = membertools.refresh(stored["refresh_token"])
            access = renewed.get("access_token")
            if access:
                # Rotation-safe (#0 fix F2): Okta keeps the SAME refresh token here (rotation off), but
                # if it ever hands back a NEW one the old token is now dead — persist the new one or the
                # NEXT run gets invalid_grant and falsely flags needs-reauth. _save_membertools_token →
                # save_membertools_refresh preserves the original membertools_minted_at 45-day clock.
                rotated = renewed.get("refresh_token")
                if rotated and rotated != stored["refresh_token"] and stake_unit:
                    _save_membertools_token(stake_unit, rotated)
                    logger.info("stake %s: Member Tools refresh token ROTATED — re-persisted (45-day "
                                "clock preserved)", stake_unit)
                logger.info("stake %s: Member Tools bearer renewed from the stored token", stake_unit)
                return access
            logger.error("stake %s: Member Tools refresh returned no access token — the stored token "
                         "may be malformed; will try a fresh mint off the live session", stake_unit)
        except membertools.RefreshTokenExpired:
            logger.warning("stake %s: the stored Member Tools token hit the 45-day wall (RefreshToken"
                           "Expired) — clearing it and minting fresh off the live session (this needs a "
                           "fresh login/re-auth; a delegated session that can't SSO will need re-auth)",
                           stake_unit)
            _clear_membertools_token(stake_unit)  # 45-day wall → re-mint below
    else:
        logger.info("stake %s: no stored Member Tools token — minting fresh off the live Okta session "
                    "(expected only right after enroll / on the operator's own fresh login)", stake_unit)
    tok = membertools.mint_from_okta_session(client.session.session)  # raises MemberToolsError if dead
    if stake_unit and tok.get("refresh_token"):
        _save_membertools_token(stake_unit, tok["refresh_token"])
        logger.info("stake %s: minted + persisted a fresh Member Tools 45-day token", stake_unit)
    return tok.get("access_token")


def _clear_membertools_token(stake_unit: int) -> None:
    """Drop an expired (45-day wall) Member Tools refresh token from both stores so we re-mint."""
    try:
        from backend import credentials, db
        conn = db.connect()
        try:
            sid = credentials.stake_id_for_unit(conn, stake_unit)
            if sid:
                credentials.clear_membertools_refresh(conn, sid)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Member Tools token DB clear skipped for stake %s: %s", stake_unit, exc)
    try:
        from lcr_client import token_store
        token_store.clear_membertools_token(stake_unit)
    except Exception:  # noqa: BLE001
        pass


def _sync_one(args) -> dict:
    """Report + export + optional Sheets/Supabase for the CURRENT session/stake."""
    from lcr_client import LcrClient, metrics
    from lcr_client.access import covenant_path_access
    from covenant_path.profile_cache import ProfileCache
    from covenant_path.report import build_stake_report, export

    metrics.reset()  # isolate this stake's request metrics for the diagnostics row
    # auto_login=False: the daily sync's session is the stored delegated credential (or the operator's
    # fresh login) — it must NEVER fall back to a fresh okta_login.login() on a 401. That headless
    # login is MFA-blocked now (2026-06-12), and a recoverable LCR-session expiry must NOT turn into a
    # hard failure: the covenant-path CORE comes from the Member Tools 45-day token, and the LCR-only
    # extras (KPIs, missionaries, the eligibility re-check) degrade gracefully (best-effort) instead.
    client = LcrClient(auto_login=False)
    # Mark the stake "running" before the long scrape so the app can show a syncing banner
    # (and a brand-new stake gets a row immediately). Best-effort — never block the sync.
    # Also compute the STALE-FIRST unit order (oldest data first) so the report refreshes the
    # most-stale wards first — a mid-run one-work outage then leaves the LEAST-stale units unfinished.
    unit_order: list[int] | None = None
    if args.supabase:
        try:
            from backend import db as _db
            ctx = client.user_context()
            _c = _db.connect()
            _sid = _db.upsert_stake(_c, ctx.unit_number, ctx.unit_name)
            _db.set_sync_state(_c, _sid, "running")
            try:
                unit_order = _db.stale_first_units(_c, _sid) or None
            except Exception as exc:  # noqa: BLE001 — ordering is best-effort, never block the sync
                logger.warning("stale-first ordering skipped: %s", exc)
            _c.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not mark sync running: %s", exc)
    # The access matrix (callings → features) needs the LCR session; best-effort so a dead session
    # doesn't sink the run — the covenant-path data comes from Member Tools regardless. An empty
    # access just means coverage/feature gates fall back to sentinels (data still syncs).
    try:
        access = covenant_path_access(client)
    except Exception as exc:  # noqa: BLE001
        logger.warning("access matrix skipped (LCR session unavailable — syncing via Member Tools): %s", exc)
        access = {}
    cache = ProfileCache(max_age_days=args.cache_max_age_days, enabled=not args.no_cache)
    # The covenant-path data now comes ONLY from the RELIABLE Member Tools bulk API (one /api/v5/sync
    # replaces the fragile /api/report/one-work/* fan-out). The legacy one-work path is DEPRECATED — it
    # is never run automatically; it remains reachable ONLY via --unit (ops single-ward refetch) or
    # --no-membertools (debug escape hatch). On a Member Tools outage the run is SKIPPED (the
    # non-destructive upsert preserves last-good data; it retries next run) rather than falling back to
    # the fragile cluster. Token: a stored 45-day refresh token, else a silent mint off the live Okta
    # session (a fresh login — CI / re-auth). (docs/SYNC_PACING_PLAN + project_membertools_bulk_api)
    if getattr(args, "unit", None) or getattr(args, "no_membertools", False):
        rows = build_stake_report(client, with_profile=args.with_profile, access=access,
                                  cache=cache, verbose=args.verbose,
                                  only_unit=getattr(args, "unit", None), unit_order=unit_order)
        cp_source = "one-work-legacy"
    else:
        from covenant_path.report import build_membertools_report
        # Prefer the unit number the caller already knows (the delegated stake's credential record) —
        # the Member Tools 45-day token is keyed by it, and deriving it from user_context (LCR) would
        # fail once the LCR session dies, stranding a stake that HAS a valid token. Fall back to the
        # LCR-derived unit only when the caller didn't supply one (the operator's own self-sync).
        stake_unit = getattr(args, "_stake_unit", None) or _stake_unit_for_token(client)
        access_token = _membertools_access_token(client, stake_unit)
        args._mt_access_token = access_token  # for the /api/v5/sync/files bundle photo pass (#11)
        rows, mt_stats = build_membertools_report(
            client, access_token=access_token, with_profile=args.with_profile,
            access=access, cache=cache, verbose=args.verbose)
        # The stake/ward structure from the payload — lets the Supabase sync run with NO live LCR
        # session (it dies within days; the 45-day token outlives it). Stash it off _run_stats so it
        # isn't written to the diagnostics row.
        args._mt_unit_context = mt_stats.pop("unit_context", None)
        access.setdefault("_run_stats", {}).update(mt_stats)
        cp_source = "membertools"
        logger.info("covenant-path via Member Tools (/api/v5/sync): %d members", len(rows))
    access.setdefault("_run_stats", {})["covenant_path_source"] = cp_source
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
                only_unit=getattr(args, "unit", None), access=access,
                ctx_override=getattr(args, "_mt_unit_context", None),
                # The unit number this credential is REGISTERED for (the delegated stake's record, or
                # the operator's own). sync_stake refuses to write if this turns out to be a ward/branch
                # beneath the stake the session can see — see CredentialScopeMismatch.
                expected_stake_unit=getattr(args, "_stake_unit", None))
            if args.photos:
                from backend import photos as photopipe
                s = result["supabase"]
                at = getattr(args, "_mt_access_token", None)
                if at:
                    # Member + missionary avatars from the /api/v5/sync/files bundle — no LCR session,
                    # no cmisId (#11). The missionary photo URLs ride back for the roster (best-effort).
                    pres = photopipe.sync_photos_from_bundle(conn, s["stake_id"], s["stake_unit"], at)
                    result["photos"] = pres["stats"]
                    try:
                        db.attach_missionary_photos(conn, s["stake_id"], pres["missionary_urls"])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("missionary photo attach skipped: %s", exc)
                else:
                    result["photos"] = photopipe.sync_photos_for_stake(client, conn, s["stake_id"], s["stake_unit"])
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
    args._stake_unit = st.get("unit_number")  # known from the credential record — the MT token key
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
    # Three-tier LCR-session renewal: (1) stored LCR appSession (outlives Okta), (2) Okta re-SSO,
    # (3) OAuth refresh_token → silent SSO. If ALL fail, the LCR session is dead and can't be renewed
    # headlessly (MFA) — but the covenant-path CORE comes from the Member Tools 45-day token, which
    # outlives the LCR session. So when a token exists, sync via it (LCR-only extras best-effort)
    # instead of stranding the stake; only a stake with NO token genuinely needs a re-authorization.
    try:
        okta_login.verify_session(session)
    except Exception:  # noqa: BLE001
        try:
            okta_login.establish_lcr_session(session)
            okta_login.verify_session(session)
        except Exception as renew_exc:  # noqa: BLE001
            if not okta_login.try_refresh_session(session, cred.get("refresh_token")):
                if not _membertools_token(st.get("unit_number")).get("refresh_token"):
                    # Dead LCR session AND no Member Tools token → nothing can sync headlessly. Raise a
                    # CLEARLY-classifiable error so run_one_stake treats it as the expected "leader must
                    # re-authorize" state (non-failing, flagged for the ops table) rather than a red
                    # infra failure. Re-auth must be with a PASSWORD (the OTP/IDX lane can't mint).
                    raise RuntimeError(
                        "LCR session expired and no Member Tools sync token — needs re-authorization "
                        "(sign in with a Church password to mint a fresh 45-day token)") from renew_exc
                logger.warning("stake %s: LCR session expired and can't renew headlessly — syncing "
                               "the covenant-path core via the Member Tools 45-day token (LCR-only "
                               "extras best-effort; a re-auth refreshes them)", st.get("unit_number"))
    okta_login.write_storage_state(session, okta_login.DEFAULT_STORAGE_STATE)
    # #10: periodically re-verify the authorizing leader's calling STILL grants covenant-path access —
    # this runs every sync, so a released/reassigned leader's stored credential is caught and revoked
    # (the app then shows "sync paused — re-enroll" and stops trusting a now-ineligible session).
    _revoke_if_ineligible(st)
    res = _sync_one(args)
    _mark_succeeded(st["stake_id"])  # healthy sync → clear any prior failing/stale state (alert edge)
    _maybe_age_alert(st)             # B8: nudge the provider BEFORE an aging session dies
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
        access = covenant_path_access(LcrClient(auto_login=False))  # storage_state just written; no MFA-blocked relogin
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


def _revoke_scope_mismatch(unit, exc) -> None:
    """A credential registered for a WARD/BRANCH that is actually a sub-unit of a real stake: revoke it
    so the daily sync stops trying to use it (a ward-scoped credential must never sync a stake), record
    a diagnostics breadcrumb, and emit an event. The ward's leader still sees their unit via their
    provisioned ward_leader RLS role — no credential needed. Best-effort: never changes the run's exit
    status. (Auto-heals any legacy ward-as-stake credential; new ones are blocked at enroll.)"""
    if not unit:
        return
    try:
        from backend import credentials, db, observability as obs
        conn = db.connect()
        try:
            sid = credentials.stake_id_for_unit(conn, unit)
            if sid:
                credentials.revoke(conn, sid, reason=f"scope mismatch — {exc}")
                db.insert_diagnostics(conn, sid, "scope_mismatch",
                                      {"unit": unit, "stake_unit": getattr(exc, "stake_unit", None),
                                       "reason": str(exc)[:300]})
        finally:
            conn.close()
        obs.event("sync.stake.scope_mismatch", level="warning", stake=int(unit),
                  status="revoked", message=str(exc)[:200])
        obs.flush()
        logger.warning("stake %s revoked — ward-scoped credential cannot sync a stake (%s)", unit, exc)
    except Exception as e:  # noqa: BLE001
        logger.warning("scope-mismatch revoke skipped (non-fatal): %s", e)


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
        except CredentialScopeMismatch as exc:
            # A WARD/BRANCH-level credential that resolves to its PARENT stake (the Green Level Ward
            # incident). It must never sync — revoke it so it stops trying, and clear it from the ops
            # surface. The ward's leader still sees their unit via their provisioned ward_leader role.
            logger.error("stake %s: credential scope mismatch — %s", unit, exc)
            _revoke_scope_mismatch(unit, exc)
            print(f"[i] stake {unit}: ward-scoped credential revoked (cannot sync a stake) — its "
                  f"leader keeps their ward view via RLS")
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.error("stake %s delegated sync failed: %s", unit, exc)
            # A stake whose LCR session is dead AND has no Member Tools token genuinely needs the LEADER
            # to re-authorize — that's an EXPECTED, leader-actionable state, not an infrastructure
            # failure. Don't red-fail the workflow on it (or the daily run goes red every hour until the
            # leader acts); flag it stale so it surfaces in the ops table + the app banner + a
            # once-per-streak email, and exit cleanly. Real failures (LCR/Member Tools outage, a bug)
            # still fall through to the alert + non-zero exit below.
            if _is_needs_reauth(exc):
                _flag_needs_reauth(unit, str(exc))
                print(f"[i] stake {unit} needs re-authorization (session expired, no sync token) — "
                      f"flagged for the leader, not failed")
                return 0
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
                            _mark_succeeded(st["stake_id"])  # operator's own stake is fresh; clear stale
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


def _mark_succeeded(stake_id) -> None:
    """Clear a credential's failing/stale state after a healthy sync (guarded — never blocks the run)."""
    try:
        from backend import credentials, db
        conn = db.connect()
        try:
            credentials.mark_succeeded(conn, stake_id)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("mark_succeeded skipped: %s", exc)


def _maybe_age_alert(st: dict) -> None:
    """B8 credential longevity: a session WITHOUT a refresh token cannot self-renew — it dies with
    its Okta session, and until now the provider only heard AFTER the sync started failing. After a
    HEALTHY sync (so we know it still works), nudge the provider once per credential generation when
    the session is older than CP_CREDENTIAL_AGE_ALERT_DAYS (default 21; 0 disables) so they
    re-authorize at their convenience instead of discovering a dead sync. Fully guarded — alerting
    must never affect the run."""
    # Default 40: the Member Tools token lasts 45 days from (re-)enroll (which also bumps the
    # credential's updated_at), so nudging at ~day 40 leaves a ~5-day window to re-authorize via the
    # emailed /reauth link before the sync would pause. 0 disables.
    try:
        days = int(os.environ.get("CP_CREDENTIAL_AGE_ALERT_DAYS", "40"))
    except ValueError:
        days = 40
    if days <= 0:
        return
    try:
        from backend import credentials, db, mailer
        conn = db.connect()
        try:
            if not credentials.claim_age_notification(conn, st["stake_id"], days):
                return
            provider = credentials.provider_email(conn, st["stake_id"])
            sender = mailer.stake_from(conn, st["stake_id"])
        finally:
            conn.close()
        if not provider:
            return
        name = st.get("name") or st.get("unit_number")
        reauth_url = os.environ.get("APP_URL", "https://app.membercovenantpath.org").rstrip("/") + "/reauth"
        mailer.send_email(
            provider,
            f"Covenant Path — re-authorize the {name} sync when convenient",
            (f"<p>The daily sync for <b>{name}</b> is still working, but the Church session backing "
             f"it is over <b>{days} days</b> old and will expire soon — when it does, the sync pauses "
             f"until you re-authorize.</p>"
             f'<p style="margin:18px 0"><a href="{reauth_url}" '
             f'style="background:#7c5cff;color:#fff;padding:11px 20px;border-radius:8px;'
             f'text-decoration:none;font-weight:600">Re-authorize the {name} sync</a></p>'
             f"<p>It takes under a minute — sign in once on the Church page (one verification code) "
             f"and the sync keeps running for another ~45 days. You'll get this nudge at most once "
             f"per stored session. (You can also do it in the app → <b>Sync settings → "
             f"Re-authorize daily sync</b>.)</p>"),
            sender)
        logger.info("aging-credential nudge sent for %s (older than %dd) with the reauth deep link",
                    name, days)
    except Exception as exc:  # noqa: BLE001
        logger.debug("age alert skipped: %s", exc)


_NEEDS_REAUTH_SIGNALS = (
    "login_required",            # silent Member Tools authorize had no live Okta session
    "okta session not live",
    "landed back on okta",       # SSO bounced to the Okta login page (session dead)
    "no active credential",      # the stored credential was revoked / cleared
    "select-authenticator",      # a headless renew hit an MFA challenge (can't continue unattended)
    "needs re-authorization",
)


def _is_needs_reauth(exc) -> bool:
    """True when a stake's sync failure is the EXPECTED 'a leader must re-authorize' state — the LCR
    session is dead AND there's no Member Tools token, so nothing can be synced headlessly. These are
    NOT infrastructure failures: they don't red-fail the daily workflow, they flag the stake for the
    leader (ops table + app banner + a once-per-streak email). Anything else (an LCR/Member Tools
    outage, a code bug) IS a real failure and still red-fails."""
    msg = str(exc).lower()
    return any(s in msg for s in _NEEDS_REAUTH_SIGNALS)


def _flag_needs_reauth(unit, reason: str) -> None:
    """A stake whose Church session expired with no sync token: flag it stale so the ops enrolled-stakes
    table + the app re-auth banner show it, and email the LEADER (provider) ONCE per streak with the
    re-authorize path — but do NOT red-alert the operator or fail the workflow. It's waiting on the
    leader, not broken. Fully guarded — flagging must never change the run's exit status."""
    if not unit:
        return
    try:
        from backend import credentials, db, observability as obs
        stake_name = str(unit)
        notify = False
        provider = None
        msg = (reason[:300] + " — a leader must re-authorize with their Church PASSWORD (Sync settings → "
               "Re-authorize) to mint a fresh 45-day sync token.")
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                # A distinct sync_state (not 'error') so the ops table reads it as "waiting on the leader"
                # rather than a broken sync. The app only special-cases 'running', so this is inert there.
                cur.execute("update stakes set sync_state='needs_reauth' where unit_number=%s "
                            "returning id, name", (unit,))
                row = cur.fetchone()
            conn.commit()
            if row:
                stake_id, stake_name = row[0], (row[1] or stake_name)
                db.insert_diagnostics(conn, stake_id, "needs_reauth", {"unit": unit, "reason": reason[:400]})
                credentials.mark_failed(conn, stake_id, msg)                  # stale → app banner + ops table
                notify = credentials.claim_stale_notification(conn, stake_id)  # no-spam: once per streak
                provider = credentials.provider_email(conn, stake_id)
        finally:
            conn.close()
        obs.event("sync.stake.needs_reauth", level="warning", stake=int(unit),
                  status="needs_reauth", message=reason[:200])
        obs.flush()
        logger.warning("stake %s (%s) needs re-authorization — flagged for the leader (not failed)",
                       unit, stake_name)
        if notify and provider:  # success->failure edge only
            _email_provider_failure(provider, stake_name, unit, msg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("needs-reauth flag skipped (non-fatal): %s", exc)


def _alert_sync_failure(unit, reason: str) -> None:
    """Sync-failure alert: make a failed/stale stake VISIBLE (app banner + admin console + Axiom) and
    FLAG its credential stale (drives the re-authorize banner + the enroll takeover). Emails the owner
    AND the credential's provider ONCE per failure streak — not every run (claim_stale_notification).
    Fully guarded — alerting must never change the run's exit status."""
    if not unit:
        return
    try:
        from backend import credentials, db, observability as obs
        stake_name = str(unit)
        notify = False
        provider = None
        conn = db.connect()
        try:
            with conn.cursor() as cur:
                cur.execute("update stakes set sync_state='error' where unit_number=%s "
                            "returning id, name", (unit,))
                row = cur.fetchone()
            conn.commit()
            if row:
                stake_id, stake_name = row[0], (row[1] or stake_name)
                db.insert_diagnostics(conn, stake_id, "sync_error", {"unit": unit, "reason": reason[:400]})
                credentials.mark_failed(conn, stake_id, reason)               # flag stale (banner + takeover)
                notify = credentials.claim_stale_notification(conn, stake_id)  # no-spam: once per streak
                provider = credentials.provider_email(conn, stake_id)
        finally:
            conn.close()
        obs.event("sync.stake.failed", level="error", stake=int(unit), status="error", message=reason[:200])
        obs.flush()
        logger.error("SYNC ALERT: stake %s (%s) failed — %s", unit, stake_name, reason[:160])
        if notify:  # success->failure edge only
            _email_owner_failure(stake_name, unit, reason)
            if provider:
                _email_provider_failure(provider, stake_name, unit, reason)
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


def _email_provider_failure(to: str, stake_name: str, unit, reason: str) -> None:
    """Tell the credential's PROVIDER (the leader who authorized it) — in plain terms — that their
    stake's sync stopped, with a one-tap path back into the app to re-authorize. Best-effort; sent at
    most once per failure streak (the caller gates on claim_stale_notification)."""
    app_url = (os.environ.get("APP_URL") or "").rstrip("/")
    try:
        from backend.auth_broker import admin
        link = (f'<p style="margin:18px 0"><a href="{app_url}" '
                f'style="background:#3949ab;color:#fff;padding:10px 18px;border-radius:8px;'
                f'text-decoration:none">Open Covenant Path → re-authorize</a></p>') if app_url else ""
        html = (f"<p>Hi,</p>"
                f"<p>The daily sync for <b>{stake_name}</b> has <b>paused</b> — the Church (LCR) session "
                f"that keeps it updated has expired, so your members' data is frozen at the last good "
                f"sync.</p>"
                f"<p><b>To fix it:</b> sign in to Covenant Path again with sync enabled. That re-authorizes "
                f"the session (your password is never stored) and the data resumes within minutes — you "
                f"can also kick off a sync right away from <b>Settings → Sync settings</b>.</p>"
                f"{link}"
                f"<p style='color:#888;font-size:12px'>Technical detail: {reason[:300]}</p>")
        admin._send_email(to, f"Covenant Path — action needed: sync paused for {stake_name}", html)
        logger.info("stale-credential email sent to provider")
    except Exception as exc:  # noqa: BLE001
        logger.debug("provider stale email skipped: %s", exc)


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
        except CredentialScopeMismatch as exc:
            # Ward-scoped credential masquerading as a stake — revoke + skip (not a failure).
            logger.error("stake %s (%s): credential scope mismatch — %s",
                         st.get("name"), st.get("unit_number"), exc)
            _revoke_scope_mismatch(st.get("unit_number"), exc)
            print(f"[i] {st.get('name')}: ward-scoped credential revoked (cannot sync a stake)")
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
    ap.add_argument("--no-membertools", action="store_true",
                    help="skip the Member Tools bulk API; force the legacy one-work fan-out")
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
