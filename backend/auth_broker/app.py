"""
Auth-broker API (FastAPI) — "Sign in with your Church account" for web + native.

Flow: the app posts Church username/password (or a native-captured session); the broker
authenticates server-side (okta_flow, MFA-aware), then mints a Supabase session OTP that
the app verifies to get an RLS-scoped session. No password is stored; nothing secret is
logged. Each request gets a short id for troubleshooting.

Run locally:  uvicorn backend.auth_broker.app:app --reload --port 8787
Deploy: any container host (Render/Fly free tier). Set env: SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, CP_TOKEN_KEY (unused here but shared), ALLOWED_ORIGINS.
"""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from lcr_client.logging_setup import get_logger
from backend.auth_broker import okta_flow, session_mint

logger = get_logger()
app = FastAPI(title="Covenant Path — Church login broker")

_origins = [o.strip() for o in os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:*,https://*.membercovenantpath.org").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=False)


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


def _rid() -> str:
    return secrets.token_hex(4)


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
