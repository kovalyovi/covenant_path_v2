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

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from lcr_client.logging_setup import get_logger
from backend.auth_broker import admin, email_relay, okta_flow, session_mint

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
    r"|https://([a-z0-9-]+\.)*pages\.dev"
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


def _try_enroll(res: dict, want: bool, rid: str) -> dict | None:
    """If the leader consented, persist their captured session as the stake credential. Always
    guarded — a failure here must never break the login that just succeeded."""
    if not want or not res.get("cookies"):
        return None
    try:
        from backend.auth_broker import enroll
        out = enroll.persist(res["cookies"], res["identity"])
        logger.info("[req %s] enrolled stake (complete=%s)", rid, out.get("complete"))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("[req %s] enroll persist failed (login still ok): %s", rid, exc)
        return {"error": str(exc)}


def _mint(identity: dict, rid: str) -> dict:
    """Turn a verified identity into a Supabase OTP the app verifies into a session."""
    try:
        return session_mint.mint_otp(identity.get("email", ""))
    except session_mint.MintError as e:
        logger.error("[req %s] mint failed: %s", rid, e)
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "church-login-broker"}


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
    if not admin.github_configured():
        raise HTTPException(status_code=503, detail="sync dispatch not configured (GITHUB_TOKEN)")
    try:
        admin.dispatch("daily-sync.yml", inputs={"targets": "supabase"})
    except admin.AdminError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "dispatched", "coverage_complete": bool(cred.get("complete")),
            "last_synced_at": status.get("last_synced_at")}


@app.post("/auth/password")
def auth_password(req: PasswordReq) -> dict:
    rid = _rid()
    logger.info("[req %s] /auth/password user=%s", rid, req.username)
    try:
        res = okta_flow.start_login(req.username.strip(), req.password)
    except okta_flow.AuthError as e:
        logger.warning("[req %s] auth failed: %s", rid, e)
        raise HTTPException(status_code=401, detail=str(e))
    if res["status"] == "mfa_required":
        return {"status": "mfa_required", "login_id": res["login_id"], "factors": res["factors"]}
    enrolled = _try_enroll(res, req.enroll, rid)
    return {"status": "ok", "session": _mint(res["identity"], rid),
            "identity_name": res["identity"].get("name"), "enroll": enrolled}


@app.post("/auth/mfa/select")
def auth_mfa_select(req: FactorReq) -> dict:
    rid = _rid()
    logger.info("[req %s] /auth/mfa/select login=%s", rid, req.login_id)
    try:
        return okta_flow.select_factor(req.login_id, req.factor_id)
    except okta_flow.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/mfa/verify")
def auth_mfa_verify(req: MfaReq) -> dict:
    rid = _rid()
    logger.info("[req %s] /auth/mfa/verify login=%s", rid, req.login_id)
    try:
        res = okta_flow.verify_mfa(req.login_id, req.code.strip())
    except okta_flow.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    enrolled = _try_enroll(res, req.enroll, rid)
    return {"status": "ok", "session": _mint(res["identity"], rid),
            "identity_name": res["identity"].get("name"), "enroll": enrolled}


@app.post("/auth/session")
def auth_session(req: SessionReq) -> dict:
    """Native WebView path: app captured the Okta session itself (password only to Okta)."""
    rid = _rid()
    logger.info("[req %s] /auth/session (native captured)", rid)
    try:
        res = okta_flow.verify_captured_session(req.cookies)
    except okta_flow.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    enrolled = _try_enroll(res, req.enroll, rid)
    return {"status": "ok", "session": _mint(res["identity"], rid),
            "identity_name": res["identity"].get("name"), "enroll": enrolled}


# --- email-OTP relay (sign in when the browser can't reach Supabase directly) ---

class EmailStartReq(BaseModel):
    email: str


class EmailVerifyReq(BaseModel):
    email: str
    code: str


@app.post("/auth/email/start")
def auth_email_start(req: EmailStartReq) -> dict:
    """Relay an email one-time-code request to Supabase (server-side, no browser CORS)."""
    rid = _rid()
    logger.info("[req %s] /auth/email/start", rid)
    try:
        return email_relay.start_email_login(req.email)
    except email_relay.RelayError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/email/verify")
def auth_email_verify(req: EmailVerifyReq) -> dict:
    """Verify the emailed code server-side and return session tokens for setSession."""
    rid = _rid()
    logger.info("[req %s] /auth/email/verify", rid)
    try:
        return email_relay.verify_email_login(req.email, req.code)
    except email_relay.RelayError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
def webauthn_login_begin() -> dict:
    """Begin a passwordless passkey login (discoverable credential challenge). No auth required."""
    from backend.auth_broker import webauthn_flow
    try:
        return webauthn_flow.login_begin()
    except webauthn_flow.PasskeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webauthn/login/complete")
def webauthn_login_complete(req: PasskeyCompleteReq) -> dict:
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


class ReportEmailReq(BaseModel):
    to_email: str | None = None


@app.get("/report")
def report(email: str = Depends(require_user), authorization: str = Header(default="")) -> dict:
    """Ad-hoc leader report (#73): structured convert-integration status for the caller's scope."""
    from backend.auth_broker import reports
    auth_id = admin._jwt_sub((authorization or "").removeprefix("Bearer ").strip())
    try:
        return reports.build_report(auth_id)
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


@app.get("/admin/enrolled-stakes")
def admin_enrolled_stakes(email: str = Depends(require_admin)) -> dict:
    """Cross-stake ops: every stake with credential state, coverage, freshness, member count."""
    try:
        return {"stakes": admin.enrolled_stakes()}
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/admin/stakes/{stake_id}/revoke")
def admin_revoke_stake(stake_id: str, email: str = Depends(require_admin)) -> dict:
    """Admin override: revoke any stake's sync credential (ops support — no provider check)."""
    logger.info("admin %s revoking stake credential %s", email, stake_id)
    try:
        return admin.admin_revoke_stake(stake_id)
    except admin.AdminError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/admin/actions")
def admin_actions(email: str = Depends(require_admin)) -> dict:
    """Recent GitHub Actions runs + the commit changelog. Graceful when GITHUB_TOKEN unset."""
    if not admin.github_configured():
        return {"configured": False, "runs": [], "commits": []}
    try:
        return {"configured": True, "runs": admin.list_runs(), "commits": admin.recent_commits()}
    except Exception as e:  # noqa: BLE001 — surface upstream GitHub errors as 503
        logger.error("admin/actions failed: %s", e)
        raise HTTPException(status_code=503, detail=f"github error: {e}")


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
        raise HTTPException(status_code=503, detail=f"github error: {e}")
