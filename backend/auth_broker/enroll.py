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
from backend.auth_broker import identity_cache

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
    """The stake's current NON-REVOKED credential — coverage + access_rank — or None when there's no
    credential at all (or it's revoked). Drives `can_enroll` (offer to SET UP sync) and `can_improve`.

    A STALE-but-present credential is NOT None here — re-authorization is surfaced by the dashboard
    "re-authorize" BANNER (from enrollment_status state='stale'), NOT the "set up sync" prompt, so a
    healthy/enrolled stake never wrongly shows "isn't set up yet".

    BUG FIXED (2026-06-09): PostgREST returns a to-one embedded resource as a JSON OBJECT, not a list.
    `for c in {dict}` iterates the KEYS (strings) → `c.get(...)` raised 'str has no attribute get' → the
    except returned None → can_enroll was True on EVERY login (the long-standing 'always prompted to set
    up sync even though my credential is stored' bug). Normalize the embed to a list."""
    try:
        sb = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/stakes", headers=sb,
            params={"select": "id,stake_credentials(coverage,access_rank,revoked)",
                    "unit_number": f"eq.{unit_number}", "limit": "1"}, timeout=30)
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            return None
        cred = _first_usable_credential(rows[0].get("stake_credentials"))
        if not cred:
            return None
        return {"coverage": cred.get("coverage") or {}, "access_rank": cred.get("access_rank")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("stored-credential lookup skipped: %s", exc)
        return None


def _first_usable_credential(embed) -> dict | None:
    """The first NON-REVOKED credential from a PostgREST embed that may be a single object (to-one
    relationship), a list, or None. Shared so the dict-vs-list normalization lives in one place."""
    creds = embed if isinstance(embed, list) else ([embed] if isinstance(embed, dict) else [])
    return next((c for c in creds if isinstance(c, dict) and not c.get("revoked")), None)


def _bind_identity_email(identity: dict) -> None:
    """Stamp this login's VERIFIED email onto the person's calling-provisioned user_roles rows
    (matched by lcr_person_uuid == auth/me churchCMISUUID — probe-verified to be the same uuid).

    This is the missing link that made provisioned leaders (e.g. every high councilor) see an
    EMPTY app: their stake-wide rows exist nightly, but RLS matches by auth_id (never the LCR
    uuid) or by email (NULL since the member-list enrichment endpoint died). One Church login
    binds them forever — afterwards plain Google/OTP sign-ins with the same address match too.

    Runs on EVERY login and is idempotent: re-stamping heals a leader provisioned AFTER their
    first login and follows a verified email change (latest Church login wins). Only rows with
    a lcr_person_uuid are touchable — invite/manual grants (NULL uuid) can't be hit by the
    predicate. Best-effort: never raises, a failure just leaves the binding for the next login."""
    email = (identity.get("email") or "").lower()
    person_uuid = identity.get("cmis_uuid") or ""
    if not (email and person_uuid and SUPABASE_URL and SERVICE_KEY):
        return
    import uuid as _uuid
    try:
        _uuid.UUID(person_uuid)  # sanity: only ever a uuid in the REST predicate
    except ValueError:
        logger.info("identity bind skipped: cmis_uuid not a uuid")
        return
    try:
        r = requests.patch(
            f"{SUPABASE_URL}/rest/v1/user_roles",
            headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                     "Content-Type": "application/json", "Prefer": "return=representation"},
            params={"lcr_person_uuid": f"eq.{person_uuid}", "select": "role"},
            json={"email": email}, timeout=8)
        if r.status_code < 300:
            bound = len(r.json()) if r.text else 0
            if bound:
                logger.info("identity bind: verified email stamped onto %d role row(s)", bound)
        else:
            logger.warning("identity bind failed (%s): %s", r.status_code, r.text[:160])
    except Exception as exc:  # noqa: BLE001 — binding must never break a login
        logger.warning("identity bind skipped: %s", exc)


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
                 request_id=None, duration_ms=None, phase=None) -> None:
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
                  "outcome": outcome, "error": error, "request_id": request_id,
                  "duration_ms": duration_ms, "phase": phase},
            timeout=15)
    except Exception as exc:  # noqa: BLE001
        logger.warning("login audit write skipped (non-fatal): %s", exc)


def evaluate_and_maybe_store(cookies: list[dict], identity: dict, store: bool, *,
                             request_id: str | None = None, t_start: float | None = None) -> dict:
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

    def _elapsed_ms() -> int:
        """ms since the REQUEST started (t_start from the API handler) — what login_audit records."""
        return int((_time.monotonic() - (t_start if t_start is not None else t0)) * 1000)

    # Bind FIRST (one indexed UPDATE, both lanes): the audit's role_scope below then reports
    # what this login will actually see post-bind, not the pre-bind 'none'.
    _bind_identity_email(identity)

    # ZERO-LCR FAST LANE: a cached-identity repeat login already knows its unit; when that stake has
    # a usable credential on file, authorization needs only this DB check (RLS is the real data
    # gate, same trust as the credential-on-file fast path below). No LcrClient, no user_context —
    # a routine repeat sign-in stops depending on LCR weather entirely.
    if not store and identity.get("cached") and identity.get("unit_number"):
        from types import SimpleNamespace
        active_fast = _stored_credential_summary(identity["unit_number"])
        if active_fast is not None:
            logger.info("login eval: FAST-LANE (cached identity + usable credential) %.2fs",
                        _time.monotonic() - t0)
            ctx_shim = SimpleNamespace(unit_number=identity["unit_number"],
                                       unit_name=identity.get("stake_name"))
            _audit_login(identity.get("email"), identity.get("name"), ctx_shim, {}, True, None,
                         "allowed", None, request_id=request_id,
                         duration_ms=_elapsed_ms(), phase="fast-lane")
            return {"stake": identity.get("stake_name"), "unit_number": identity["unit_number"],
                    "authorized": True, "access_rank": None, "complete": None, "missing": [],
                    "can_improve": False, "can_enroll": False, "stored": False, "fast": True}
        # No usable credential for the cached unit → the full eval below (it establishes LCR itself).

    client = _client_from_cookies(cookies)
    try:
        ctx = client.user_context()
    except Exception:  # noqa: BLE001
        # Fast-lane cookies carry only the Okta session (no LCR SSO yet) — establish it, retry once.
        from lcr_client.okta_login import establish_lcr_session, session_from_cookies
        s = session_from_cookies(cookies)
        establish_lcr_session(s)
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/"}
                   for c in s.cookies]
        client = _client_from_cookies(cookies)
        ctx = client.user_context()
    logger.info("login eval: user_context %.1fs (unit=%s)", _time.monotonic() - t0, ctx.unit_number)
    # Record the unit now — this is what makes this user's NEXT login zero-LCR.
    identity_cache.set_unit(identity.get("login_username") or identity.get("username") or "",
                            identity, ctx.unit_number, ctx.unit_name)

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
                     "allowed", None, request_id=request_id, duration_ms=_elapsed_ms(), phase="fast")
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
                     outcome, error, request_id=request_id, duration_ms=_elapsed_ms(), phase="full")

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


# --- background identity refresh (ADR-009 amendment: B) ----------------------------------------

# Per-username throttle: a login burst (autofill retries, back-to-back e2e runs) triggers ONE
# refresh, not one per login. In-process state is fine — the broker is a single instance, and a
# restart just means one extra refresh.
_REFRESH_TTL_S = 600.0
_REFRESH_AT: dict[str, float] = {}


def _refresh_due(username: str) -> bool:
    """Consume the per-username refresh slot (True = caller should refresh now)."""
    import time as _time
    now = _time.monotonic()
    if len(_REFRESH_AT) > 256:  # opportunistic prune — the map must not grow unbounded
        cutoff = now - _REFRESH_TTL_S
        for k in [k for k, v in _REFRESH_AT.items() if v < cutoff]:
            _REFRESH_AT.pop(k, None)
    last = _REFRESH_AT.get(username)
    if last is not None and now - last < _REFRESH_TTL_S:
        return False
    _REFRESH_AT[username] = now
    return True


def refresh_cached_identity(cookies: list[dict], login_username: str) -> None:
    """Background refresh of a cached-lane login's church_identities row — email/name (the
    changed-email case) AND unit/stake (the moved-stakes case, which the old stale-only refresher
    missed: unit comes from user_context, not /api/auth/me). Runs AFTER the login has already
    answered, on the broker's dedicated refresh pool; throttled per username; never raises."""
    from backend import observability as obs
    key = (login_username or "").strip().lower()
    if not key or not _refresh_due(key):
        return
    import time as _time
    t0 = _time.monotonic()
    try:
        from backend.auth_broker import okta_flow
        from lcr_client.okta_login import session_from_cookies
        s = session_from_cookies(cookies)
        ident = okta_flow._identity(s, "bg-refresh")  # establishes LCR + reads /api/auth/me
        ident["login_username"] = login_username
        ctx = _client_from_cookies(okta_flow.serialize_cookies(s)).user_context()
        identity_cache.put(login_username or ident.get("username") or "", ident,
                           unit_number=ctx.unit_number, stake_name=ctx.unit_name)
        obs.event("identity.refresh", status="ok",
                  duration_ms=round((_time.monotonic() - t0) * 1000, 1))
        logger.info("identity cache refreshed for login=%s (%.1fs, unit=%s)",
                    key, _time.monotonic() - t0, ctx.unit_number)
    except Exception as exc:  # noqa: BLE001 — must never matter to the login that spawned it
        obs.event("identity.refresh", status="error", message=str(exc)[:200])
        logger.info("identity cache refresh skipped: %s", exc)


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
