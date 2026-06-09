"""
Delegated stake onboarding (#51): persist a leader's captured LCR session as their stake's
credential so the daily sync can keep that stake current.

Reuses the proven client parsing — LcrClient.user_context() for the stake, and
covenant_path_access() for what the session can pull (coverage) — encrypts the session with
envelope encryption (credentials._encrypt_envelope), and stores it via the SECURITY DEFINER
enroll_stake_credential RPC (so the service-role broker writes the RLS-locked tables without
broad grants). The caller guards every call — a failure here must never break login.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _client_from_cookies(cookies: list[dict]):
    """Build an LcrClient from captured cookies (no auto-login, no shared state file)."""
    from lcr_client import LcrClient
    from lcr_client.auth import LcrSession
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    p = Path(path)
    p.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    try:
        session = LcrSession(storage_state_path=p, auto_login=False)  # loads cookies into memory
    finally:
        p.unlink(missing_ok=True)  # cookies are in-memory now; don't leave the file around
    return LcrClient(session=session)


def _stored_credential_summary(unit_number: int) -> dict | None:
    """The stake's current USABLE credential (non-revoked AND not currently failing) — coverage +
    access_rank, or None. None means "no usable credential" → the caller offers enrollment.

    A STALE credential (last_failed_at set — its delegated session died and the daily sync is failing)
    counts as NOT usable, so the provider (or any authorized leader) is OFFERED re-enrollment instead of
    being stuck: the credential looks "active/non-revoked" but can't actually sync. This was the
    "re-logged in but nothing changed" bug — the app never offered re-auth for a stale-but-active cred."""
    try:
        sb = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/stakes", headers=sb,
            params={"select": "id,stake_credentials(coverage,access_rank,revoked,last_failed_at)",
                    "unit_number": f"eq.{unit_number}", "limit": "1"}, timeout=30)
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return None
        cred = next((c for c in (rows[0].get("stake_credentials") or [])
                     if not c.get("revoked") and not c.get("last_failed_at")), None)
        if not cred:
            return None
        return {"coverage": cred.get("coverage") or {}, "access_rank": cred.get("access_rank")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("stored-credential lookup skipped: %s", exc)
        return None


def _role_scope(email) -> str:
    """What this sign-in will ACTUALLY see — their user_roles scope, the way RLS resolves it (by
    email). Flags the two failure modes: 'none' = logged in but sees an empty app (under-visibility,
    e.g. a leader whose role row never got their email); an unexpected stake = over-visibility."""
    if not (email and SUPABASE_URL and SERVICE_KEY):
        return "unknown"
    try:
        from collections import Counter
        r = requests.get(f"{SUPABASE_URL}/rest/v1/user_roles",
                         headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"},
                         params={"email": f"eq.{email.lower()}", "select": "role"}, timeout=15)
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return "none"
        c = Counter(row.get("role") for row in rows)
        return ", ".join(f"{k}×{v}" for k, v in sorted(c.items()))
    except Exception:  # noqa: BLE001
        return "unknown"


def _audit_login(email, name, ctx, access, authorized, rank, outcome, error=None,
                 request_id=None) -> None:
    """Best-effort login-audit row (who / stake / callings / access / outcome) for admin debugging
    via the login_audit table (migration 0033, admin-only RLS). NEVER raises — observability must
    never affect the login that just happened."""
    if not (SUPABASE_URL and SERVICE_KEY):
        return
    try:
        auth_str = ("allowed" if authorized is True
                    else "blocked" if authorized is False else "undetermined")
        requests.post(
            f"{SUPABASE_URL}/rest/v1/login_audit",
            headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
            json={"email": ((email or "").lower() or None), "name": name,
                  "stake_unit": getattr(ctx, "unit_number", None),
                  "stake_name": getattr(ctx, "unit_name", None),
                  "callings": [p.get("name") for p in (access.get("runner_positions") or [])],
                  "authorized": auth_str, "access_rank": rank,
                  "can_pull_all": bool(access.get("can_pull_all")),
                  "role_scope": _role_scope(email),
                  "outcome": outcome, "error": error, "request_id": request_id},
            timeout=15)
    except Exception as exc:  # noqa: BLE001
        logger.warning("login audit write skipped (non-fatal): %s", exc)


def evaluate_and_maybe_store(cookies: list[dict], identity: dict, store: bool) -> dict:
    """The single login-time entry point. ALWAYS evaluates the captured session's covenant-path
    access — so the no-access gate (N2) and the higher-access "you can improve the sync" offer work
    on every Church login — but STORES the encrypted credential (and kicks off the first sync) ONLY
    when `store` is true, i.e. the leader EXPLICITLY authorized it. Signing in no longer captures a
    credential as a side effect; that now requires deliberate consent. Raises on hard failure (caller
    guards). Returns {stake, unit_number, authorized, access_rank, complete, missing, can_improve,
    stored[, initial_sync]}."""
    if not (SUPABASE_URL and SERVICE_KEY):
        raise RuntimeError("supabase not configured (SUPABASE_URL / SERVICE_ROLE_KEY)")
    import time as _time
    from lcr_client.access import covenant_path_access
    from backend import credentials, onboarding
    from backend.roles import _calling_always_allowed

    t0 = _time.monotonic()
    client = _client_from_cookies(cookies)
    ctx = client.user_context()
    logger.info("login eval: user_context %.1fs (unit=%s)", _time.monotonic() - t0, ctx.unit_number)

    # FAST PATH (the ">1 minute to sign in" fix): the full covenant_path_access scrape below hits
    # dozens of LCR endpoints and routinely took 30-60s+ on every Church login. It only EARNS that
    # cost when its output is used: enrolling (store=True, need coverage/rank) or when the stake has
    # no USABLE credential (need the authorized gate + the can_enroll/can_improve offers). A routine
    # sign-in to an already-synced stake skips it: RLS is the real data gate (a no-role member just
    # sees an empty app), and _revoke_if_ineligible re-verifies callings on every daily sync anyway.
    active_fast = _stored_credential_summary(ctx.unit_number)
    if not store and active_fast is not None:
        logger.info("login eval: FAST path (usable credential on file) %.1fs total", _time.monotonic() - t0)
        _audit_login(identity.get("email"), identity.get("name"), ctx, {}, True, None,
                     "allowed", None)
        return {"stake": ctx.unit_name, "unit_number": ctx.unit_number,
                "authorized": True, "access_rank": None, "complete": None, "missing": [],
                "can_improve": False, "can_enroll": False, "stored": False, "fast": True}

    t1 = _time.monotonic()
    access = covenant_path_access(client)  # best-effort name enrichment is internally guarded
    logger.info("login eval: access scrape %.1fs", _time.monotonic() - t1)
    coverage = onboarding.coverage_of(access)
    rank = onboarding.access_rank(access)

    # N2: does this login's calling grant ANY covenant-path data access? can_pull_all or >=1 granted
    # feature, OR a stake-stewardship calling (the always-allowed safety net mirrors backend/roles.py,
    # so a clerk/high-councilor with an incomplete LCR menu matrix is NOT false-blocked). A member
    # with no such calling is told at login they can't use the app (authorized:False blocks the client
    # pre-session). We deliberately err toward allowing (only block on a clear "no access").
    positions = access.get("runner_positions") or []
    has_access = (bool(access.get("can_pull_all")) or rank > 0
                  or any(_calling_always_allowed(p.get("name")) for p in positions))
    # Err toward allowing — N2 is a UX nicety; RLS is the real data gate, so a leader we let through
    # with no roles just sees an EMPTY app, never anyone else's data. Only block on a CLEAR no-access:
    # we positively read the runner's callings and none grant access. An EMPTY positions probe (LCR
    # user-context hiccup / unexpected shape) is NOT a clear no-access → return None so the client lets
    # them through, instead of false-blocking a legitimate leader (e.g. a stake president whose
    # positions didn't resolve). This was hard-blocking real stake presidents.
    authorized = True if has_access else (False if positions else None)

    # Higher-access transfer offer: when the stake ALREADY has a credential that's insufficient
    # (incomplete or lower access) and THIS session would strictly improve it, tell the client so it
    # can offer this leader to take over the sync. (The enroll RPC enforces the same rule on write,
    # so authorizing actually replaces the weaker credential.)
    active = _stored_credential_summary(ctx.unit_number)
    can_improve = bool(authorized and active is not None
                       and onboarding.should_take_over(active, access))
    # can_enroll: this authorized leader could set up sync for a stake that has NO usable credential
    # yet (none stored, or the only one is revoked → _stored_credential_summary returns None). The
    # client uses this to OFFER enrollment AFTER login (consent moved off the login form, #8) — never
    # shown when the stake already has a sufficient credential.
    can_enroll = bool(authorized and active is None)

    base = {"stake": ctx.unit_name, "unit_number": ctx.unit_number,
            "authorized": authorized, "access_rank": rank,
            "complete": coverage["complete"], "missing": coverage["missing"],
            "can_improve": can_improve, "can_enroll": can_enroll, "stored": False}

    def _audit(outcome: str, error: str | None = None) -> None:
        _audit_login(identity.get("email"), identity.get("name"), ctx, access, authorized, rank,
                     outcome, error)

    if authorized is not True:
        reason = ("clearly lacks covenant-path access" if authorized is False
                  else "access UNDETERMINED (no positions read) — allowing through")
        logger.info("login %s (rank=%s unit=%s callings=%s); not enrolling",
                    reason, rank, ctx.unit_number, [p.get("name") for p in positions])
        _audit("blocked" if authorized is False else "undetermined")
        return base
    if not store:
        logger.info("authorized login for %s (%s) without sync consent — not storing credential",
                    ctx.unit_name, ctx.unit_number)
        _audit("allowed")
        return base

    # Explicit consent → store the credential. The RPC keeps "most-elevated-wins-if-incomplete".
    role_ids = sorted({p["id"] for p in positions if isinstance(p.get("id"), int)})
    blob = credentials._encrypt_envelope(
        json.dumps({"cookies": cookies, "refresh_token": identity.get("refresh_token")}).encode("utf-8"))
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/enroll_stake_credential",
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Content-Type": "application/json"},
        json={
            "p_unit_number": ctx.unit_number,
            "p_stake_name": ctx.unit_name,
            "p_principal_name": identity.get("name") or identity.get("email"),
            "p_principal_email": (identity.get("email") or "").lower(),
            "p_granting_role_ids": role_ids,
            "p_credential_enc": blob,
            "p_coverage": coverage,
            "p_access_rank": rank,
            "p_expires_at": None,
            # cadence visibility: a credential WITH a refresh token self-renews (re-auth rare);
            # without one it dies with its Okta session (~days). The blob is encrypted, so record
            # the boolean at enroll time.
            "p_has_refresh_token": bool(identity.get("refresh_token")),
        },
        timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"enroll RPC failed ({r.status_code}): {r.text[:160]}")
    logger.info("enrolled stake %s (%s): coverage_complete=%s rank=%s",
                ctx.unit_name, ctx.unit_number, coverage["complete"], rank)
    initial_sync = _kickoff_initial_sync(ctx.unit_number)
    base["stored"] = True
    base["initial_sync"] = initial_sync
    _notify_enrolled(identity, ctx, coverage, initial_sync)
    _audit("enrolled")
    return base


def persist(cookies: list[dict], identity: dict) -> dict:
    """Back-compat shim: enroll WITH consent (always stores). Prefer evaluate_and_maybe_store."""
    return evaluate_and_maybe_store(cookies, identity, store=True)


def _notify_enrolled(identity: dict, ctx, coverage: dict, initial_sync: bool) -> None:
    """Email the leader confirming their stake's daily sync is now set up (the "then notify them"
    step). Best-effort — a notification problem must never affect the enrollment that just succeeded."""
    email = (identity.get("email") or "").strip()
    if not email:
        return
    try:
        from backend.auth_broker import admin
        name = identity.get("name") or "there"
        cov_line = ("Your access can pull the full covenant-path dataset."
                    if coverage.get("complete")
                    else "Some fields need a leader with broader access — the app shows who to ask, "
                         "and a leader with more access can take over the sync.")
        sync_line = ("The first sync is running now — your stake's data will appear in a few minutes."
                     if initial_sync else "Your stake will refresh on the daily schedule.")
        html = (f"<p>Hi {name},</p>"
                f"<p>You authorized <b>Covenant Path</b> to keep <b>{ctx.unit_name}</b> synced daily "
                f"using your Church (LCR) session. It is encrypted server-side — your password is "
                f"never stored — and you can pause or revoke it anytime in the app under "
                f"<b>Settings → Sync settings</b>.</p>"
                f"<p>{cov_line} {sync_line}</p>")
        admin._send_email(email, f"Covenant Path — daily sync enabled for {ctx.unit_name}", html)
        logger.info("sent enroll confirmation to %s", email)
    except Exception as exc:  # noqa: BLE001
        logger.warning("enroll notification skipped (non-fatal): %s", exc)


def _kickoff_initial_sync(unit_number: int) -> bool:
    """For a brand-new stake (no data scraped yet), mark it 'running' and dispatch the
    daily-sync workflow so the leader doesn't wait for the next scheduled run. The app then
    shows the "setting up your stake" syncing state until the run lands. Best-effort: if
    GitHub isn't configured or the stake already has data, this is a no-op."""
    from datetime import datetime, timezone
    try:
        from backend.auth_broker import admin
        if not admin.github_configured():
            return False
        sb = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
        r = requests.get(f"{SUPABASE_URL}/rest/v1/stakes", headers=sb,
                         params={"select": "id", "unit_number": f"eq.{unit_number}", "limit": "1"},
                         timeout=30)
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return False
        stake_id = rows[0]["id"]
        if (admin._count_where("members", {"stake_id": f"eq.{stake_id}"}) or 0) > 0:
            return False  # already has data — the daily run keeps it fresh
        requests.patch(f"{SUPABASE_URL}/rest/v1/stakes",
                       headers={**sb, "Content-Type": "application/json", "Prefer": "return=minimal"},
                       params={"id": f"eq.{stake_id}"},
                       json={"sync_state": "running",
                             "sync_started_at": datetime.now(timezone.utc).isoformat()},
                       timeout=30)
        # PER-STAKE: scope the kickoff to THIS stake only (the `stake` input → prepare `--only`).
        # Without it the dispatch fanned out the whole matrix, so one leader's enroll re-synced every
        # other stake too (the "my father's sync hit my stake" bug).
        admin.dispatch("daily-sync.yml", inputs={"targets": "supabase", "stake": str(unit_number)})
        logger.info("kicked off initial sync for new stake unit=%s (scoped --stake %s)",
                    unit_number, unit_number)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("initial-sync kickoff skipped (non-fatal): %s", exc)
        return False
