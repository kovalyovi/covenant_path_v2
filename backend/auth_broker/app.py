"""
Auth-broker API (FastAPI) — "Sign in with your Church account" for web + native.

Flow: the app posts Church username/password (or a native-captured session); the broker
authenticates server-side (okta_flow, MFA-aware), then mints a Supabase session OTP that
the app verifies to get an RLS-scoped session. No password is stored; nothing secret is
logged. Each request gets a short id for troubleshooting.

Run locally:  uvicorn backend.auth_broker.app:app --reload --port 8787
Deploy: any container host (Render/Fly free tier). Set env: SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, ALLOWED_ORIGINS. (No CP_TOKEN_KEY — the broker does live login
and stores nothing encrypted; that key is only for the daily-sync credential vault.)
"""

from __future__ import annotations

import os
import secrets
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from lcr_client.logging_setup import get_logger
from backend.auth_broker import (
    admin, email_relay, google_oauth, okta_flow, ratelimit, session_mint)

logger = get_logger()
app = FastAPI(title="Covenant Path — Church login broker")

# Starlette does NOT glob `allow_origins` (it's exact-match), so subdomains and *.pages.dev
# must go through `allow_origin_regex`. The regex covers our custom domain (any subdomain),
# Cloudflare Pages (production + preview deploys), and local dev — so the app works whether
# served from app.membercovenantpath.org or covenant-path-app.pages.dev. ALLOWED_ORIGINS env
# can still add extra exact origins.
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_origin_regex = os.environ.get(
    "ALLOWED_ORIGIN_REGEX",
    r"https://([a-z0-9-]+\.)*membercovenantpath\.org"
    # BACKEND-07: pin to THIS project's Cloudflare Pages site (prod + preview subdomains), not all
    # of *.pages.dev (which would trust any attacker's Pages deploy). Env override corrects the slug.
    r"|https://([a-z0-9-]+\.)?covenant-path-app\.pages\.dev"
    r"|http://localhost(:[0-9]+)?"
    r"|http://127\.0\.0\.1(:[0-9]+)?")
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_origin_regex=_origin_regex,
                   allow_methods=["*"], allow_headers=["*"], allow_credentials=False)
logger.info("CORS: exact=%s regex=%s", _origins, _origin_regex)


class PasswordReq(BaseModel):
    username: str
    password: str
    enroll: bool = False  # leader consented to store their session for ongoing stake sync


class FactorReq(BaseModel):
    login_id: str
    factor_id: str


class MfaReq(BaseModel):
    login_id: str
    code: str
    enroll: bool = False


class SessionReq(BaseModel):
    cookies: list[dict]
    enroll: bool = False


class DispatchReq(BaseModel):
    workflow: str = "daily-sync.yml"
    inputs: dict | None = None  # workflow_dispatch inputs (e.g. {"targets":"supabase","photos":"true"})


def _rid() -> str:
    return secrets.token_hex(4)


def require_admin(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: the caller must present a Supabase access token belonging to
    an app_admin. Returns the admin email; 403 if not an admin, 503 if misconfigured."""
    try:
        return admin.verify_admin(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


def require_user(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: any signed-in app user (verified Supabase token). Returns email."""
    try:
        return admin.verify_user(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


import concurrent.futures as _futures

# Background evaluator for the time-budgeted login eval (threads keep running past the budget so
# the audit row + staleness offers still land; only the RESPONSE stops waiting).
_EVAL_POOL = _futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="login-eval")
# Small-fast-task pool (session mint, telemetry flush) — SEPARATE from _EVAL_POOL on purpose:
# long background access-evals can occupy every eval worker, and the mint must never queue
# behind them (it's on the response's critical path).
_FAST_POOL = _futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="login-fast")
# Identity-refresh pool: ONE worker on purpose — refreshes serialize so a bad-LCR (90s) refresh
# can never crowd the eval/mint pools, and enroll's per-username throttle dedupes login bursts.
_REFRESH_POOL = _futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ident-refresh")
# "Login must be under 5 seconds": how long a NON-consent login waits for its access evaluation
# before answering without it (the dashboard re-derives offers from /auth/enrollment-status).
_EVAL_BUDGET_S = float(os.environ.get("LOGIN_EVAL_BUDGET_SECONDS", "4"))
# First (uncached) logins additionally wait — up to this — for a user_context-only calling gate, so
# a no-calling member is blocked IN THE RESPONSE (the full eval's verdict defers past the budget on
# a cold login). On timeout (LCR slow) the login proceeds; the background eval still audits. Repeat
# logins skip this entirely (they take the zero-LCR cached fast block).
_GATE_BUDGET_S = float(os.environ.get("LOGIN_GATE_BUDGET_SECONDS", "12"))


def _login_eval(res: dict, store: bool, rid: str, t0: float | None = None) -> dict | None:
    """Evaluate the captured session on a Church login and STORE the credential only when the leader
    consented (`store`). Consent stays SYNCHRONOUS (the leader just asked for setup — the client shows
    progress and allows 95s). A plain sign-in waits at most _EVAL_BUDGET_S: the fast lanes (cached
    identity / usable credential on file) answer well within it; a full first-eval continues in the
    BACKGROUND (audit still written) while the user gets their session immediately — the dashboard
    surfaces any enroll/re-auth offer from /auth/enrollment-status instead. Always guarded — never
    breaks the login itself."""
    if not res.get("cookies"):
        return None
    from backend.auth_broker import enroll
    ident = res.get("identity") or {}
    if not store and ident.get("cached"):
        # EVERY cached login refreshes its identity row OFF the login path (throttled per user in
        # enroll), so an email or stake change is healed by the user's NEXT login — not a 7-day
        # TTL (ADR-009 amendment: B). Submitted BEFORE the fast calling-gate below so a member who
        # was blocked but has since been CALLED to a position re-fetches user_context and heals their
        # has_calling flag (otherwise a cached False would lock them out permanently).
        _REFRESH_POOL.submit(enroll.refresh_cached_identity, res.get("cookies") or [],
                             ident.get("login_username") or "")
    # FAST CALLING-GATE (zero LCR, in-budget): a prior login positively determined this account has
    # no calling and cached has_calling=False (migration 0044), which the cached-identity lane now
    # carries on `ident`. The full eval reaches the same block, but only AFTER a cold user_context
    # (~30s here) — far past _EVAL_BUDGET_S — so it deferred to the background and the block landed
    # too late: the response went out with no verdict and the client minted a session (the "no
    # calling but still signed in / saw the set-up-sync prompt" report). Decide synchronously here so
    # authorized:false is in the RESPONSE. RLS already gates data; this makes the client refuse the
    # session. A consent flow (store) is never auto-blocked; the eval re-verifies on a real attempt.
    # The background refresh above keeps this self-healing if the member is later called.
    if not store and ident.get("has_calling") is False:
        from types import SimpleNamespace
        ctx = SimpleNamespace(unit_number=ident.get("unit_number"), unit_name=ident.get("stake_name"))
        _FAST_POOL.submit(enroll._audit_login, ident.get("email"), ident.get("name"), ctx, {},
                          False, None, "blocked", None, request_id=rid,
                          duration_ms=int((time.monotonic() - (t0 or time.monotonic())) * 1000),
                          phase="gate-cached")
        logger.info("[req %s] login eval: FAST calling-gate block (cached has_calling=False, zero LCR)", rid)
        return {"authorized": False, "stake": ident.get("stake_name"),
                "unit_number": ident.get("unit_number"), "complete": None, "missing": [],
                "can_improve": False, "can_enroll": False, "stored": False}
    # FIRST-LOGIN SYNCHRONOUS CALLING GATE: an uncached login has no cached has_calling flag, so the
    # zero-LCR fast block above can't apply and the full eval's verdict would land after the budget
    # (deferred) — letting a no-calling member in once. Run a user_context-ONLY gate synchronously
    # (one LCR call, not the dozens of the access scrape) so a clear "no calling" is blocked in the
    # RESPONSE. Bounded by _GATE_BUDGET_S; on timeout (slow LCR) or error the gate returns None / the
    # wait ends and we proceed to the full eval — err toward allow, never block a real leader on a
    # slow/down LCR (RLS still gates data in that residual window). A leader passes here, pays one
    # user_context, then the full eval runs (deferred as before). Consent (store) is never pre-gated.
    if not store and not ident.get("cached") and ident.get("has_calling") is None:
        gate_fut = _EVAL_POOL.submit(enroll.calling_gate_check, res["cookies"], ident,
                                     request_id=rid, t_start=t0)
        try:
            verdict = gate_fut.result(timeout=_GATE_BUDGET_S)
            if verdict is not None:
                logger.info("[req %s] first-login calling gate blocked (authorized=false)", rid)
                return verdict
        except _futures.TimeoutError:
            logger.info("[req %s] first-login calling gate deferred after %.0fs (LCR slow → allow)",
                        rid, _GATE_BUDGET_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[req %s] first-login calling gate error (allow): %s", rid, exc)
    t_req = t0 if t0 is not None else time.monotonic()
    t_eval = time.monotonic()
    fut = _EVAL_POOL.submit(enroll.evaluate_and_maybe_store, res["cookies"], ident, store,
                            request_id=rid, t_start=t_req,
                            membertools_refresh=res.get("membertools_refresh"))
    try:
        out = fut.result(timeout=None if store else _EVAL_BUDGET_S)
        logger.info("[req %s] login eval %.1fs (authorized=%s stored=%s can_improve=%s can_enroll=%s)",
                    rid, time.monotonic() - t_eval, out.get("authorized"), out.get("stored"),
                    out.get("can_improve"), out.get("can_enroll"))
        return out
    except _futures.TimeoutError:
        logger.info("[req %s] login eval deferred to background after %.1fs budget "
                    "(dashboard surfaces offers via enrollment-status)", rid, _EVAL_BUDGET_S)
        return {"deferred": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[req %s] login eval failed (login still ok): %s", rid, exc)
        return {"error": str(exc)}


def _complete_login(res: dict, store: bool, rid: str, t0: float) -> dict:
    """Shared completion for password/MFA/native logins: mint the Supabase session and run the login
    eval IN PARALLEL (independent — the mint needs only the verified email), then emit the per-phase
    timing event and echo `timing` to the client, so "which part was slow" is one Axiom query
    (server-side) or one /log row (client-experienced) instead of guesswork."""
    okta_ms = int((time.monotonic() - t0) * 1000)
    mint_fut = _FAST_POOL.submit(_mint, res["identity"], rid)
    t1 = time.monotonic()
    enrolled = _login_eval(res, store, rid, t0=t0)
    eval_ms = int((time.monotonic() - t1) * 1000)
    t2 = time.monotonic()
    session = mint_fut.result()  # raises the mint's HTTPException if it failed
    mint_wait_ms = int((time.monotonic() - t2) * 1000)
    total_ms = int((time.monotonic() - t0) * 1000)
    lane = "cached" if (res.get("identity") or {}).get("cached") else "full"
    deferred = bool(isinstance(enrolled, dict) and enrolled.get("deferred"))
    from backend import observability as obs
    obs.event("login.request", duration_ms=total_ms, okta_ms=okta_ms, eval_ms=eval_ms,
              mint_wait_ms=mint_wait_ms, lane=lane, status="ok", deferred=deferred)
    _FAST_POOL.submit(obs.flush)
    logger.info("[req %s] login %dms (okta=%d eval=%d mint_wait=%d lane=%s deferred=%s)",
                rid, total_ms, okta_ms, eval_ms, mint_wait_ms, lane, deferred)
    return {"status": "ok", "session": session,
            "identity_name": (res.get("identity") or {}).get("name"), "enroll": enrolled,
            "timing": {"total_ms": total_ms, "okta_ms": okta_ms, "eval_ms": eval_ms, "lane": lane}}


def _mint(identity: dict, rid: str) -> dict:
    """Turn a verified identity into a Supabase OTP the app verifies into a session."""
    try:
        return session_mint.mint_otp(identity.get("email", ""))
    except session_mint.MintError as e:
        logger.error("[req %s] mint failed: %s", rid, e)
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/health")
def health() -> dict:
    # google_oauth_configured: a non-secret boolean so we can confirm the M7 env loaded (#M7).
    # lcr: "degraded" once 2+ distinct accounts failed the identity leg (the 2026-06-10 outage
    # was only diagnosable by reproducing it by hand) — one glance instead of an audit dig.
    since = okta_flow.lcr_outage_since()
    return {"ok": True, "service": "church-login-broker",
            "google_oauth_configured": google_oauth.is_configured(),
            "lcr": "degraded" if since else "ok",
            "lcr_failing_since": (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since))
                                  if since else None)}


class LogReq(BaseModel):
    level: str = "error"
    event: str = "client.error"
    message: str | None = None
    surface: str | None = None      # "web" | "android" | …
    context: dict | None = None     # small, non-PII extras (ids/counts/route)


@app.post("/log")
def client_log(req: LogReq) -> dict:
    """Client-side error/observability ingest (#53): the app ships uncaught errors / failed calls
    here and the broker forwards them to Axiom (PII-scrubbed, no-op without AXIOM_TOKEN). Anonymous
    + size-capped — it's just telemetry."""
    from backend import observability as obs
    safe = {k: v for k, v in (req.context or {}).items()
            if isinstance(v, (str, int, float, bool))}
    # Also surface client telemetry in the broker's OWN logs (stdout → Render) so it's pullable via
    # tools/render_logs.py — obs.event only ships to Axiom (no-op without a token), which isn't
    # queryable. Client perf summaries (event=client.perf) ride this path too.
    from lcr_client.logging_setup import get_logger
    get_logger().info("client %s/%s %s | %s", req.surface or "?", req.event,
                      (req.message or "")[:300], safe)
    obs.event(req.event, level=req.level, message=(req.message or "")[:500],
              surface=req.surface, **safe)
    obs.flush()
    return {"ok": True}


class RevokeReq(BaseModel):
    stake_id: str


@app.get("/auth/enrollment-status")
def auth_enrollment_status(authorization: str = Header(default="")) -> dict:
    """Return stake enrollment/credential status for the signed-in user.
    Used by the app to show enroll prompts, stale warnings, and sync settings."""
    try:
        email = admin.verify_user(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    token = (authorization or "").removeprefix("Bearer ").strip()
    auth_id = admin._jwt_sub(token)
    try:
        return admin.enrollment_status(email, auth_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/auth/revoke")
def auth_revoke(req: RevokeReq, authorization: str = Header(default="")) -> dict:
    """Revoke the caller's stake credential (provider only — validated server-side)."""
    try:
        email = admin.verify_user(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        return admin.revoke_credential(req.stake_id, email)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/auth/wipe-data")
def auth_wipe_data(req: RevokeReq, authorization: str = Header(default="")) -> dict:
    """Provider self-service tier of the admin wipe (/admin/stakes/{id}/wipe-data): delete the
    caller's stake MEMBER data via the same wipe_stake_members RPC — keeps the stake + roles +
    credential; data re-populates on the next sync. Provider-gated, validated server-side.
    Body shape matches /auth/revoke ({stake_id})."""
    try:
        email = admin.verify_user(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    try:
        return admin.wipe_stake_data_as_provider(req.stake_id, email)
    except admin.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/auth/sync-now")
def auth_sync_now(authorization: str = Header(default="")) -> dict:
    """Provider triggers a sync for their own stake (the 'Sync now' control). Returns whether the
    credential's coverage is full so the app can warn it won't be a complete pull (item 11)."""
    try:
        email = admin.verify_user(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    auth_id = admin._jwt_sub((authorization or "").removeprefix("Bearer ").strip())
    try:
        status = admin.enrollment_status(email, auth_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    cred = status.get("credential", {})
    if not cred.get("is_provider"):
        raise HTTPException(status_code=403, detail="only the stake's sync provider can start a sync")
    # A revoked credential cannot sync — dispatching a run that silently skips the stake would be
    # dishonest (the UI hides the button too; this is the server-side gate behind it).
    if cred.get("state") == "revoked":
        raise HTTPException(status_code=409, detail="Sync is paused — the credential was revoked. "
                                                    "Re-authorize in Sync settings first.")
    if not admin.github_configured():
        raise HTTPException(status_code=503, detail="sync dispatch not configured (GITHUB_TOKEN)")
    # Cooldown (2026-06-25): a provider clicking "Sync now" repeatedly — or a re-auth/re-enroll burst —
    # used to fire a fresh full run EACH time (one stake was observed syncing 7-9×/day from on-demand
    # triggers while schedule-only stakes synced once). If it synced within the cooldown, report it as
    # already-fresh instead of dispatching another run; the daily schedule still covers it.
    from datetime import datetime, timezone, timedelta
    last = status.get("last_synced_at")
    if last:
        try:
            ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - ts < timedelta(minutes=5):
                return {"status": "skipped", "reason": "synced moments ago — already up to date",
                        "coverage_complete": bool(cred.get("complete")), "last_synced_at": last}
        except (ValueError, TypeError):
            pass
    try:
        # PER-STAKE: scope to the provider's own stake — without the `stake` input this dispatched
        # the WHOLE matrix (same fan-out bug as the on-enroll kickoff, provider-path edition).
        inputs = {"targets": "supabase"}
        if status.get("unit_number"):
            inputs["stake"] = str(status["unit_number"])
        admin.dispatch("daily-sync.yml", inputs=inputs)
    except admin.AdminError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "dispatched", "coverage_complete": bool(cred.get("complete")),
            "last_synced_at": status.get("last_synced_at")}


def _profile_refresh_gate(authorization: str) -> dict:
    """Shared gate for the fill-data routes: signed-in stake leader of a stake with a usable
    (non-revoked) credential whose calling can read member profiles. Returns enrollment_status."""
    try:
        email = admin.verify_user(authorization)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    auth_id = admin._jwt_sub((authorization or "").removeprefix("Bearer ").strip())
    try:
        status = admin.enrollment_status(email, auth_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not (status.get("unit_number") and status.get("stake_id")):
        raise HTTPException(status_code=404, detail="no stake linked to this sign-in")
    if not status.get("viewer_is_stake_leader"):
        raise HTTPException(status_code=403, detail="only a stake leader can refresh profile data")
    return status


@app.post("/auth/profile-refresh")
def auth_profile_refresh(authorization: str = Header(default="")) -> dict:
    """Fill every missing profile-sourced field (patriarchal blessing, per-member callings, …) for
    the caller's stake — the fill-data sheet's action. Tries the STORED delegated session first; when
    it can't reach /mlt any more (the steady state — the Okta sid dies within days), answers
    `needs_reauth` so the client opens the re-auth dialog, whose enroll path runs this same fill off
    the freshly-captured live session. Poll GET /auth/profile-refresh/status for progress."""
    status = _profile_refresh_gate(authorization)
    cred = status.get("credential", {})
    if cred.get("state") == "revoked":
        raise HTTPException(status_code=409, detail="Sync is paused — the credential was revoked. "
                                                    "Re-authorize in Sync settings first.")
    if cred.get("can_refresh_patriarchal") is False:
        raise HTTPException(status_code=409, detail="The enrolled account's calling can't read "
                                                    "member profiles, so these fields can't be "
                                                    "refreshed. A leader with member-profile access "
                                                    "should enroll for sync.")
    from backend.auth_broker import enroll
    return enroll.start_profile_refresh(status["unit_number"], status["stake_id"])


@app.get("/auth/profile-refresh/status")
def auth_profile_refresh_status(authorization: str = Header(default="")) -> dict:
    """Progress + per-field missing counts for the caller's stake — what the fill-data sheet polls
    (and shows on open, so a leader sees exactly which fields are missing for how many members)."""
    status = _profile_refresh_gate(authorization)
    from backend.auth_broker import enroll
    out = enroll.profile_refresh_status(status["unit_number"], status["stake_id"])
    out["can_refresh"] = (status.get("credential", {}).get("state") != "revoked"
                          and status.get("credential", {}).get("can_refresh_patriarchal") is not False)
    return out


def _audit_okta_event(who: str, stage: str, error: str, rid: str,
                      duration_ms: int | None = None, phase: str | None = None) -> None:
    """Make OKTA-STAGE events visible in the admin console: a wrong password / failed MFA never
    reaches the login eval, so login_audit had NO row for them — a member 'stuck at login' was
    invisible (the av_kov case: zero server-side evidence of his attempts). Best-effort write with
    outcome='okta_failed'/'mfa_failed'/'mfa_pending'/...; `who` is the Church USERNAME (identity
    hint, admin-only RLS). For identity failures, `error` should be the ROOT CAUSE (e.g. 'auth/me
    502') and `phase` 'identity:<kind>' — the 2026-06-10 LCR outage was undiagnosable from the
    friendly message. Truncation is generous (2000): the 300-char cut chopped the 2026-06-11 MFA
    failure mid-payload."""
    try:
        import requests as _rq
        url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not (url and key):
            return
        _rq.post(f"{url}/rest/v1/login_audit",
                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                          "Content-Type": "application/json", "Prefer": "return=minimal"},
                 json={"email": (who or "").lower()[:120], "outcome": stage,
                       "error": (error or "")[:2000], "request_id": rid,
                       "duration_ms": duration_ms, "phase": phase},
                 timeout=10)
    except Exception:  # noqa: BLE001 — observability must never affect the login path
        pass


def _mfa_phase(e: okta_flow.AuthError) -> str:
    """phase string for MFA-stage audit rows: okta:<kind>[:<factor_type>] — names BOTH what went
    wrong and which factor type was in play (diagnosing 2026-06-11 needed Render logs for that)."""
    kind = getattr(e, "kind", "other") or "other"
    ftype = getattr(e, "factor_type", "") or ""
    return f"okta:{kind}:{ftype}" if ftype else f"okta:{kind}"


@app.post("/auth/password")
def auth_password(req: PasswordReq,
                  _rl: None = Depends(ratelimit.limiter("password", 8, 300))) -> dict:
    rid = _rid()
    t0 = time.monotonic()
    logger.info("[req %s] /auth/password user=%s", rid, req.username)
    ratelimit.hit_identifier("password", req.username)
    try:
        # Plain sign-ins ride the cached-identity fast lane (no LCR) and skip the dead token
        # exchange; an enroll needs the real LCR session + refresh token, so it takes the full path.
        res = okta_flow.start_login(req.username.strip(), req.password,
                                    want_refresh_token=req.enroll,
                                    allow_cached_identity=not req.enroll)
    except okta_flow.IdentityError as e:
        logger.warning("[req %s] LCR identity failed after password OK (%s): %s",
                       rid, getattr(e, "root_cause", "?"), e)
        _audit_okta_event(req.username, "lcr_identity_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=f"identity:{getattr(e, 'kind', 'other')}")
        raise HTTPException(status_code=503, detail=str(e))
    except okta_flow.AuthError as e:
        logger.warning("[req %s] auth failed: %s", rid, e)
        # Audit the RAW cause (root_cause), not the friendly message the user saw — a
        # "wrong password" and a real Okta outage must stay distinguishable after the fact.
        _audit_okta_event(req.username, "okta_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=_mfa_phase(e))
        raise HTTPException(status_code=401, detail=str(e))
    if res["status"] == "mfa_required":
        # Audit the mfa_required hand-off (off the response path): an attempt abandoned at the
        # code screen used to leave ZERO rows — the 2026-06-11 dig had to reconstruct the factor
        # menu from Render stdout. The row names the offered + dropped factor types.
        offered = ",".join(res.get("factor_types", []))
        dropped = ",".join(res.get("dropped_factor_types", []))
        note = f"factors offered: {offered}" + (f"; dropped: {dropped}" if dropped else "")
        _FAST_POOL.submit(_audit_okta_event, req.username, "mfa_pending", note, rid,
                          int((time.monotonic() - t0) * 1000), "okta:mfa_pending")
        return {"status": "mfa_required", "login_id": res["login_id"], "factors": res["factors"]}
    return _complete_login(res, req.enroll, rid, t0)


@app.post("/auth/mfa/select")
def auth_mfa_select(req: FactorReq,
                    _rl: None = Depends(ratelimit.limiter("mfa", 30, 300))) -> dict:
    rid = _rid()
    t0 = time.monotonic()
    logger.info("[req %s] /auth/mfa/select login=%s", rid, req.login_id)
    try:
        return okta_flow.select_factor(req.login_id, req.factor_id)
    except okta_flow.AuthError as e:
        # These were never audited — attempts that died choosing/sending a factor were invisible.
        _audit_okta_event(getattr(e, "username", ""), "mfa_select_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=_mfa_phase(e))
        raise HTTPException(status_code=400, detail=str(e))


def _mfa_handoff(res: dict, who: str, rid: str, t0: float) -> dict | None:
    """A VERIFIED step that still owes another factor (MFA continuation — e.g. an MFA-enabled
    account in the passwordless lane: emailed code, then the password). Audits the hand-off
    like the password endpoint does and returns the wire shape; None when res is a completion."""
    if res.get("status") != "mfa_required":
        return None
    offered = ",".join(res.get("factor_types", []))
    dropped = ",".join(res.get("dropped_factor_types", []))
    note = f"continuation factors offered: {offered}" + (f"; dropped: {dropped}" if dropped else "")
    _FAST_POOL.submit(_audit_okta_event, who, "mfa_pending", note, rid,
                      int((time.monotonic() - t0) * 1000), "okta:mfa_pending")
    return {"status": "mfa_required", "login_id": res["login_id"], "factors": res["factors"]}


@app.post("/auth/mfa/verify")
def auth_mfa_verify(req: MfaReq,
                    _rl: None = Depends(ratelimit.limiter("mfa", 30, 300))) -> dict:
    rid = _rid()
    t0 = time.monotonic()
    logger.info("[req %s] /auth/mfa/verify login=%s", rid, req.login_id)
    ratelimit.hit_identifier("mfa", req.login_id)
    try:
        res = okta_flow.verify_mfa(req.login_id, req.code.strip(),
                                   want_refresh_token=req.enroll,
                                   allow_cached_identity=not req.enroll)
    except okta_flow.IdentityError as e:
        logger.warning("[req %s] LCR identity failed after MFA OK (%s): %s",
                       rid, getattr(e, "root_cause", "?"), e)
        _audit_okta_event(getattr(e, "username", ""), "lcr_identity_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=f"identity:{getattr(e, 'kind', 'other')}")
        raise HTTPException(status_code=503, detail=str(e))
    except okta_flow.AuthError as e:
        _audit_okta_event(getattr(e, "username", ""), "mfa_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=_mfa_phase(e))
        raise HTTPException(status_code=401, detail=str(e))
    return _mfa_handoff(res, "", rid, t0) or _complete_login(res, req.enroll, rid, t0)


@app.post("/auth/session")
def auth_session(req: SessionReq,
                 _rl: None = Depends(ratelimit.limiter("session", 12, 600))) -> dict:
    """Native WebView capture path: the leader signed in on the Church's OWN web page inside the
    app's WebView (password autofilled/typed on churchofjesuschrist.org, full MFA there — including
    text/email/authenticator, which the broker-relayed lanes can't all offer). The app captures the
    resulting Church session cookies and posts them here; the password NEVER reaches our app UI or
    our server. We verify the session, then mint the Supabase session (login) and/or store the
    encrypted credential (enroll) — the same completion as every other lane."""
    rid = _rid()
    t0 = time.monotonic()
    logger.info("[req %s] /auth/session (captured Church web session, %d cookies)",
                rid, len(req.cookies or []))
    try:
        res = okta_flow.verify_captured_session(req.cookies)
    except okta_flow.IdentityError as e:  # must precede AuthError (its subclass)
        logger.warning("[req %s] LCR identity failed after captured session (%s): %s",
                       rid, getattr(e, "root_cause", "?"), e)
        _audit_okta_event(getattr(e, "username", ""), "lcr_identity_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=f"identity:{getattr(e, 'kind', 'other')}")
        raise HTTPException(status_code=503, detail=str(e))
    except okta_flow.AuthError as e:
        _audit_okta_event(getattr(e, "username", ""), "captured_session_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=f"okta:{getattr(e, 'kind', 'other')}")
        raise HTTPException(status_code=401, detail=str(e))
    return _complete_login(res, req.enroll, rid, t0)


# --- credential-capture login (the ONE-MFA flow that mints the 45-day sync token) -----------------
# web_session drives authn -> LCR authorize -> MFA -> appSession + Member Tools 45-day token, so a
# single MFA completion yields everything an unattended 45-day sync needs. Used by the web ENROLL
# (and re-auth) so a stake's sync token is minted at enroll without storing a password or TOTP.

@app.post("/auth/web/start")
def auth_web_start(req: PasswordReq,
                   _rl: None = Depends(ratelimit.limiter("password", 8, 300))) -> dict:
    from backend.auth_broker import web_session
    rid = _rid()
    t0 = time.monotonic()
    logger.info("[req %s] /auth/web/start user=%s enroll=%s", rid, req.username, req.enroll)
    ratelimit.hit_identifier("password", req.username)
    try:
        res = web_session.web_start(req.username.strip(), req.password)
    except okta_flow.IdentityError as e:
        _audit_okta_event(req.username, "lcr_identity_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=f"identity:{getattr(e, 'kind', 'other')}")
        raise HTTPException(status_code=503, detail=str(e))
    except okta_flow.AuthError as e:
        _audit_okta_event(req.username, "okta_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000), phase=_mfa_phase(e))
        raise HTTPException(status_code=401, detail=str(e))
    if res["status"] == "mfa_required":
        offered = ",".join(res.get("factor_types", []))
        note = f"factors offered: {offered}"
        _FAST_POOL.submit(_audit_okta_event, req.username, "mfa_pending", note, rid,
                          int((time.monotonic() - t0) * 1000), "okta:mfa_pending")
        return {"status": "mfa_required", "login_id": res["login_id"], "factors": res["factors"]}
    return _complete_login(res, req.enroll, rid, t0)


@app.post("/auth/web/select")
def auth_web_select(req: FactorReq,
                    _rl: None = Depends(ratelimit.limiter("mfa", 30, 300))) -> dict:
    from backend.auth_broker import web_session
    rid = _rid()
    logger.info("[req %s] /auth/web/select login=%s", rid, req.login_id)
    try:
        return web_session.web_select_factor(req.login_id, req.factor_id)
    except okta_flow.AuthError as e:
        _audit_okta_event(getattr(e, "username", ""), "mfa_select_failed",
                          getattr(e, "root_cause", "") or str(e), rid, phase=_mfa_phase(e))
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/web/verify")
def auth_web_verify(req: MfaReq,
                    _rl: None = Depends(ratelimit.limiter("mfa", 30, 300))) -> dict:
    from backend.auth_broker import web_session
    rid = _rid()
    t0 = time.monotonic()
    logger.info("[req %s] /auth/web/verify login=%s enroll=%s", rid, req.login_id, req.enroll)
    ratelimit.hit_identifier("mfa", req.login_id)
    try:
        res = web_session.web_verify(req.login_id, req.code.strip())
    except okta_flow.IdentityError as e:  # must precede AuthError (its subclass)
        _audit_okta_event(getattr(e, "username", ""), "lcr_identity_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000),
                          phase=f"identity:{getattr(e, 'kind', 'other')}")
        raise HTTPException(status_code=503, detail=str(e))
    except okta_flow.AuthError as e:
        _audit_okta_event(getattr(e, "username", ""), "mfa_failed",
                          getattr(e, "root_cause", "") or str(e), rid,
                          duration_ms=int((time.monotonic() - t0) * 1000), phase=_mfa_phase(e))
        raise HTTPException(status_code=401, detail=str(e))
    return _complete_login(res, req.enroll, rid, t0)


# NOTE: the passwordless Church-login lane (emailed code as the PRIMARY Okta factor, /auth/otp/*)
# was REMOVED 2026-06-12. It signed a leader in but its Okta IDX session is app-scoped — it can NOT
# silently SSO to Member Tools, so it could never mint the 45-day daily-sync token (it stored a
# token-less credential that failed every sync with login_required; the "Ken Packer" re-auth loop).
# Church authentication is now USERNAME + PASSWORD only (the classic /api/v1/authn lane, /auth/web/*
# for enroll + /auth/password for view-only), which establishes the global Okta session the silent
# Member Tools mint needs. Passwordless VIEWING still exists via the Supabase email relay below
# (/auth/email/*) — that's a different system (no Church session, RLS-scoped, can't enroll). See
# docs/DECISIONS.md (ADR-010).


# --- email-OTP relay (sign in when the browser can't reach Supabase directly) ---

class EmailStartReq(BaseModel):
    email: str


class EmailVerifyReq(BaseModel):
    email: str
    code: str


@app.post("/auth/email/start")
def auth_email_start(req: EmailStartReq,
                     _rl: None = Depends(ratelimit.limiter("email", 10, 600))) -> dict:
    """Relay an email one-time-code request to Supabase (server-side, no browser CORS)."""
    rid = _rid()
    logger.info("[req %s] /auth/email/start", rid)
    try:
        return email_relay.start_email_login(req.email)
    except email_relay.RelayError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/email/verify")
def auth_email_verify(req: EmailVerifyReq,
                      _rl: None = Depends(ratelimit.limiter("email", 20, 600))) -> dict:
    """Verify the emailed code server-side and return session tokens for setSession."""
    rid = _rid()
    logger.info("[req %s] /auth/email/verify", rid)
    ratelimit.hit_identifier("email", req.email)
    try:
        return email_relay.verify_email_login(req.email, req.code)
    except email_relay.RelayError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- per-stake Google Drive OAuth (M7) --------------------------------------

@app.get("/auth/google/status")
def google_status(authorization: str = Header(default="")) -> dict:
    """Whether the signed-in user can connect Drive + the current connection."""
    email = admin.verify_user(authorization)
    return {"configured": google_oauth.is_configured(), **admin.gdrive_status_for(email)}


@app.post("/auth/google/start")
def google_start(authorization: str = Header(default="")) -> dict:
    """Authed: returns the Google consent URL for the user's OWN stake (the app opens it)."""
    rid = _rid()
    email = admin.verify_user(authorization)
    if not google_oauth.is_configured():
        raise HTTPException(status_code=503, detail="Google Drive isn't configured on the server yet.")
    stake_id = admin.provider_stake_id(email)
    if not stake_id:
        raise HTTPException(status_code=403,
                            detail="Only your stake's sync provider can connect Google Drive.")
    logger.info("[req %s] /auth/google/start stake=%s", rid, stake_id)
    return {"url": google_oauth.start_url(stake_id, email)}


@app.get("/auth/google/callback", response_class=HTMLResponse)
def google_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
    """Google redirects here. The signed state binds the stake; we exchange + store the refresh token."""
    rid = _rid()
    if error or not code or not state:
        return HTMLResponse(_popup_html(f"Connection cancelled. ({error or 'missing code'})"))
    try:
        stake_id = google_oauth.verify_state(state)
        tokens = google_oauth.exchange_code(code)
        admin.store_gdrive_token(stake_id, google_oauth.encrypt_refresh(tokens["refresh_token"]),
                                 tokens.get("email"))
        logger.info("[req %s] google drive connected for stake=%s", rid, stake_id)
        return HTMLResponse(_popup_html(f"Google Drive connected ({tokens.get('email') or ''}). "
                                        "You can close this window."))
    except Exception:  # noqa: BLE001 — never 500 the OAuth popup; keep the detail server-side only
        logger.exception("[req %s] google callback failed", rid)  # BACKEND-08: generic to the client
        return HTMLResponse(_popup_html(
            "Could not connect Google Drive. Please close this window and try again."))


@app.post("/auth/google/disconnect")
def google_disconnect(authorization: str = Header(default="")) -> dict:
    email = admin.verify_user(authorization)
    stake_id = admin.provider_stake_id(email)
    if not stake_id:
        raise HTTPException(status_code=403, detail="Not a stake provider.")
    return admin.disconnect_gdrive(stake_id)


class ScheduleReq(BaseModel):
    hour_et: int
    paused: bool = False


@app.get("/auth/schedule")
def get_schedule(authorization: str = Header(default="")) -> dict:
    """The provider's in-app daily-sync schedule (ET hour + paused). (#schedule)"""
    email = admin.verify_user(authorization)
    try:
        return admin.get_schedule_for(email)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/auth/schedule")
def set_schedule(body: ScheduleReq, authorization: str = Header(default="")) -> dict:
    """Provider sets WHEN their stake syncs (ET hour) and pause/resume. (#schedule)"""
    email = admin.verify_user(authorization)
    try:
        return admin.set_schedule_for(email, body.hour_et, body.paused)
    except admin.NotAdmin as e:
        raise HTTPException(status_code=403, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _popup_html(message: str) -> str:
    return ("<!doctype html><meta charset=utf-8><title>Covenant Path</title>"
            "<body style='font-family:system-ui;padding:40px;text-align:center'>"
            f"<p>{message}</p><script>setTimeout(()=>window.close(),2500)</script></body>")


# --- passwordless passkey login (WebAuthn) ----------------------------------

class PasskeyCompleteReq(BaseModel):
    handle: str
    credential: dict


@app.post("/webauthn/register/begin")
def webauthn_register_begin(email: str = Depends(require_user)) -> dict:
    """A signed-in user begins binding a passkey to their email (returns ceremony options)."""
    from backend.auth_broker import webauthn_flow
    try:
        return webauthn_flow.register_begin(email)
    except webauthn_flow.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webauthn/register/complete")
def webauthn_register_complete(req: PasskeyCompleteReq, email: str = Depends(require_user)) -> dict:
    """Verify the attestation and store the passkey for the signed-in user."""
    from backend.auth_broker import webauthn_flow
    try:
        return webauthn_flow.register_complete(req.handle, req.credential)
    except webauthn_flow.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webauthn/login/begin")
def webauthn_login_begin(
        _rl: None = Depends(ratelimit.limiter("passkey", 30, 300))) -> dict:
    """Begin a passwordless passkey login (discoverable credential challenge). No auth required."""
    from backend.auth_broker import webauthn_flow
    try:
        return webauthn_flow.login_begin()
    except webauthn_flow.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webauthn/login/complete")
def webauthn_login_complete(req: PasskeyCompleteReq,
                            _rl: None = Depends(ratelimit.limiter("passkey", 30, 300))) -> dict:
    """Verify the assertion and mint a Supabase session OTP for the passkey's owner."""
    rid = _rid()
    from backend.auth_broker import webauthn_flow
    try:
        session = webauthn_flow.login_complete(req.handle, req.credential)
    except webauthn_flow.PasskeyError as e:
        logger.warning("[req %s] passkey login failed: %s", rid, e)
        raise HTTPException(status_code=401, detail=str(e))
    except session_mint.MintError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"status": "ok", "session": session}


# --- admin / ops console (all gated by require_admin) -----------------------

@app.get("/admin/summary")
def admin_summary(email: str = Depends(require_admin)) -> dict:
    """Health + data freshness in one place: broker up, Supabase counts + last sync."""
    return {"admin": email, "broker": {"ok": True}, "supabase": admin.summary(),
            "github_configured": admin.github_configured(),
            "dispatchable": admin.DISPATCHABLE, "links": admin.tool_links()}


class FeedbackReq(BaseModel):
    title: str
    body: str = ""


@app.post("/feedback")
def feedback(body: FeedbackReq, email: str = Depends(require_user)) -> dict:
    """Any signed-in user files in-app feedback as a GitHub issue (+ best-effort Copilot)."""
    try:
        return admin.create_feedback_issue(body.title, body.body, reporter=email)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


class ContactReq(BaseModel):
    subject: str = ""
    message: str


@app.post("/contact")
def contact(body: ContactReq, email: str = Depends(require_user)) -> dict:
    """Support form (#74): a signed-in user emails the owner directly for help."""
    try:
        return admin.send_contact(email, body.subject, body.message)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


class PartnerNoteAddReq(BaseModel):
    body: str
    author: str | None = None
    client_id: str | None = None  # accepted for wire-compat with the partner client; not stored


class PartnerNoteUpdateReq(BaseModel):
    id: str
    body: str
    author: str | None = None


class PartnerNoteDeleteReq(BaseModel):
    id: str


# --- Partner notes lane (Mission-KPIs app reads/writes OUR member_comments thread) -----------
# Token-gated (X-Partner-Token vs PARTNER_NOTES_TOKEN, constant-time; unset env = lane off) and
# rate-limited like the other unauthenticated surfaces (BACKEND-01 posture).

def _partner_guard(request: Request) -> None:
    from backend.auth_broker import partner_notes
    try:
        partner_notes.check_token(request.headers.get("x-partner-token"))
    except partner_notes.PartnerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


@app.get("/partner/notes/{person_uuid}", dependencies=[Depends(ratelimit.limiter("partner", 120, 60.0))])
def partner_notes_list(person_uuid: str, request: Request) -> dict:
    """The member's full note thread, oldest first — the same conversation the web renders."""
    from backend.auth_broker import partner_notes
    _partner_guard(request)
    try:
        return partner_notes.list_entries(person_uuid)
    except partner_notes.PartnerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    except admin.AdminError as e:  # Supabase misconfig is an ops problem, not a client 500
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/partner/notes/{person_uuid}", dependencies=[Depends(ratelimit.limiter("partner", 60, 60.0))])
def partner_notes_add(person_uuid: str, body: PartnerNoteAddReq, request: Request) -> dict:
    """Append one thread entry, attributed to the partner app's signed-in leader."""
    from backend.auth_broker import partner_notes
    _partner_guard(request)
    try:
        return partner_notes.add_entry(person_uuid, body.body, body.author)
    except partner_notes.PartnerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/partner/notes/{person_uuid}/update", dependencies=[Depends(ratelimit.limiter("partner", 60, 60.0))])
def partner_notes_update(person_uuid: str, body: PartnerNoteUpdateReq, request: Request) -> dict:
    """Edit one thread entry in place (the id is scoped to the person)."""
    from backend.auth_broker import partner_notes
    _partner_guard(request)
    try:
        return partner_notes.update_entry(person_uuid, body.id, body.body, body.author)
    except partner_notes.PartnerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/partner/notes/{person_uuid}/delete", dependencies=[Depends(ratelimit.limiter("partner", 60, 60.0))])
def partner_notes_delete(person_uuid: str, body: PartnerNoteDeleteReq, request: Request) -> dict:
    """Delete one thread entry (idempotent; the id is scoped to the person)."""
    from backend.auth_broker import partner_notes
    _partner_guard(request)
    try:
        return partner_notes.delete_entry(person_uuid, body.id)
    except partner_notes.PartnerError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


class ReportEmailReq(BaseModel):
    to_email: str | None = None


@app.get("/report")
def report(email: str = Depends(require_user), authorization: str = Header(default="")) -> dict:
    """Ad-hoc leader report (#73): structured convert-integration status for the caller's scope."""
    from backend.auth_broker import reports
    auth_id = admin._jwt_sub((authorization or "").removeprefix("Bearer ").strip())
    try:
        return reports.build_report(auth_id, email)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/report/email")
def report_email(body: ReportEmailReq, email: str = Depends(require_user),
                 authorization: str = Header(default="")) -> dict:
    """Email the caller's scope report (default: to themselves; or to a chosen recipient)."""
    from backend.auth_broker import reports
    auth_id = admin._jwt_sub((authorization or "").removeprefix("Bearer ").strip())
    try:
        return reports.email_report(auth_id, email, body.to_email)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


class InviteReq(BaseModel):
    email: str


@app.post("/admin/invite")
def admin_invite(body: InviteReq, email: str = Depends(require_admin)) -> dict:
    """Admin requests a new admin; the owner must approve by email before access is granted."""
    try:
        return admin.request_admin_invite(body.email, requested_by=email)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/admin/approve", response_class=HTMLResponse)
def admin_approve(token: str = "") -> str:
    """Token-gated approval link (clicked by the owner from their email — no login)."""
    style = "font-family:system-ui,sans-serif;max-width:480px;margin:60px auto;padding:0 20px"
    try:
        res = admin.approve_admin_invite(token)
    except admin.AdminError as e:
        return f"<html><body style='{style}'><h2>Approval failed</h2><p>{e}</p></body></html>"
    if res["status"] == "approved":
        return (f"<html><body style='{style}'><h2>Approved ✓</h2>"
                f"<p><b>{res['email']}</b> is now an admin.</p></body></html>")
    return (f"<html><body style='{style}'><h2>Already handled</h2>"
            f"<p>{res['email']}: {res['status']}</p></body></html>")


@app.get("/admin/diagnostics")
def admin_diagnostics(email: str = Depends(require_admin)) -> dict:
    """Recent sync/probe diagnostics: success %, failing units, field parity, latency."""
    return {"runs": admin.recent_diagnostics()}


@app.get("/admin/endpoint-health")
def admin_endpoint_health(days: int = 14, email: str = Depends(require_admin)) -> dict:
    """Cross-run per-endpoint health TREND (calls/errors/latency + error-rate by hour-of-day) from
    the telemetry every sync/probe already records — the passive read on whether our current request
    pace is safe, with zero added load on LCR."""
    days = max(1, min(days, 60))
    return admin._cached(f"endpoint_health:{days}", 120, lambda: admin.endpoint_health(days))


@app.get("/admin/enrolled-stakes")
def admin_enrolled_stakes(email: str = Depends(require_admin)) -> dict:
    """Cross-stake ops: every stake with credential state, coverage, freshness, member count."""
    try:
        return {"stakes": admin.enrolled_stakes()}
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 — never surface a raw 500: an uncaught error can reach the
        # browser without CORS headers and show as "Failed to fetch" (exactly the reported symptom).
        logger.warning("enrolled-stakes failed: %s", e)
        raise HTTPException(status_code=503, detail="enrolled-stakes temporarily unavailable")


@app.post("/admin/stakes/{stake_id}/revoke")
def admin_revoke_stake(stake_id: str, email: str = Depends(require_admin)) -> dict:
    """Admin override: revoke any stake's sync credential (ops support — no provider check)."""
    logger.info("admin %s revoking stake credential %s", email, stake_id)
    try:
        return admin.admin_revoke_stake(stake_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/admin/stakes/{stake_id}/reauth-email")
def admin_stake_reauth_email(stake_id: str, email: str = Depends(require_admin)) -> dict:
    """B3: email the stake's credential provider the re-authorize nudge (+ /reauth deep link) on
    demand — the ops worklist button for a stake whose token expired / session went stale."""
    logger.info("admin %s sending re-auth email for stake %s", email, stake_id)
    try:
        return admin.send_reauth_email(stake_id)
    except admin.NotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/admin/stakes/{stake_id}/sync")
def admin_stake_sync(stake_id: str, email: str = Depends(require_admin)) -> dict:
    """Per-stake 'Sync now' — dispatches a sync for ONLY this stake (never the full matrix)."""
    logger.info("admin %s syncing stake %s", email, stake_id)
    try:
        return admin.dispatch_stake_sync(stake_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/admin/stakes/{stake_id}/wipe-data")
def admin_stake_wipe(stake_id: str, email: str = Depends(require_admin)) -> dict:
    """Delete a stake's member DATA (keeps the stake, roles, credential). Re-populates on next sync."""
    logger.warning("admin %s WIPING member data for stake %s", email, stake_id)
    try:
        return admin.wipe_stake_data(stake_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/admin/stakes/{stake_id}/remove")
def admin_stake_remove(stake_id: str, email: str = Depends(require_admin)) -> dict:
    """FULL removal of a stake: credential + members + roles + diagnostics + the stake row.
    Irreversible — admin only (the UI must confirm)."""
    logger.warning("admin %s FULLY REMOVING stake %s", email, stake_id)
    try:
        return admin.remove_stake(stake_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/admin/actions")
def admin_actions(runs: int = 15, commits: int = 10, email: str = Depends(require_admin)) -> dict:
    """Recent GitHub Actions runs + the commit changelog. Graceful when GITHUB_TOKEN unset.
    `runs`/`commits` (≤100) let the ops detail views fetch more than the console front page."""
    if not admin.github_configured():
        return {"configured": False, "runs": [], "commits": []}
    try:
        return {"configured": True,
                "runs": admin.list_runs(max(1, min(runs, 100))),
                "commits": admin.recent_commits(max(1, min(commits, 100)))}
    except Exception as e:  # noqa: BLE001 — surface upstream GitHub errors as 503
        logger.error("admin/actions failed: %s", e)  # BACKEND-08: detail to logs, generic to client
        raise HTTPException(status_code=503, detail="GitHub is temporarily unavailable.")


@app.post("/admin/actions/run")
def admin_run(req: DispatchReq, email: str = Depends(require_admin)) -> dict:
    """Kick off a flow — daily-sync = rescrape LCR + repopulate Sheets & Supabase."""
    logger.info("admin %s dispatching %s inputs=%s", email, req.workflow, req.inputs)
    try:
        admin.dispatch(req.workflow, inputs=req.inputs)
    except admin.AdminError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "dispatched", "workflow": req.workflow, "inputs": req.inputs}


@app.post("/admin/actions/{run_id}/rerun")
def admin_rerun(run_id: int, email: str = Depends(require_admin)) -> dict:
    logger.info("admin %s re-running %s", email, run_id)
    try:
        admin.rerun(run_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "rerun", "run_id": run_id}


@app.get("/admin/actions/{run_id}")
def admin_run_status(run_id: int, email: str = Depends(require_admin)) -> dict:
    """Poll one run's status (for live progress while a rescrape is in flight)."""
    try:
        return admin.run_status(run_id)
    except Exception as e:  # noqa: BLE001
        logger.error("admin/run-status failed: %s", e)  # BACKEND-08: detail to logs, generic to client
        raise HTTPException(status_code=503, detail="GitHub is temporarily unavailable.")
