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
from backend.auth_broker import admin, okta_flow, session_mint

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


class FactorReq(BaseModel):
    login_id: str
    factor_id: str


class MfaReq(BaseModel):
    login_id: str
    code: str


class SessionReq(BaseModel):
    cookies: list[dict]


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
    return {"status": "ok", "session": _mint(res["identity"], rid), "identity_name": res["identity"].get("name")}


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
    return {"status": "ok", "session": _mint(res["identity"], rid), "identity_name": res["identity"].get("name")}


@app.post("/auth/session")
def auth_session(req: SessionReq) -> dict:
    """Native WebView path: app captured the Okta session itself (password only to Okta)."""
    rid = _rid()
    logger.info("[req %s] /auth/session (native captured)", rid)
    try:
        res = okta_flow.verify_captured_session(req.cookies)
    except okta_flow.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"status": "ok", "session": _mint(res["identity"], rid), "identity_name": res["identity"].get("name")}


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
