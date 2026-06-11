"""
In-memory Supabase stub (PostgREST + GoTrue surface) for the broker e2e suite.

REST (/rest/v1/...): the generic table engine + rpc/enroll_stake_credential — see engine.py
for exactly which PostgREST semantics are honored.

Auth (/auth/v1/...): the minimum session_mint.mint_otp + admin.verify_user need —
  POST /auth/v1/admin/users         {email, email_confirm}      -> create (idempotent)
  POST /auth/v1/admin/generate_link {type: magiclink, email}    -> {..., "email_otp"}
  POST /auth/v1/verify              {type, email, token}        -> GoTrue session (real-shaped
                                                                   unsigned JWT; the broker only
                                                                   base64-decodes the payload)
  GET  /auth/v1/user                Bearer <access_token>       -> {id, email, ...}

Control plane:
  POST /__test/seed        {"stakes": [...], "user_roles": [...], ...} (replaces those tables)
  GET  /__test/rows/{table}
  POST /__test/reset
  GET  /__test/state       (table row counts — readiness probe)

Run standalone: python -m tests.supabase_stub [--port 8903]
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tests.supabase_stub.engine import Store


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _jwt_for(user: dict) -> str:
    """Real-shaped (header.payload.signature) but unsigned JWT. The broker's _jwt_sub only
    base64-decodes the payload; GoTrue 'verification' happens in this stub's /auth/v1/user."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "sub": user["id"], "email": user["email"], "role": "authenticated",
        "aud": "authenticated", "exp": int(time.time()) + 3600,
        "session_id": str(uuid.uuid4()),
    }).encode())
    return f"{header}.{payload}.stub-signature"


def _jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:  # noqa: BLE001 — malformed token is just "not signed in"
        return {}


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(title="supabase stub", docs_url=None, redoc_url=None)
    db = store or Store()
    app.state.store = db

    def _user_for_email(email: str) -> dict:
        email = email.strip().lower()
        user = db.users.get(email)
        if user is None:
            user = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cp-test-user:{email}")),
                    "email": email, "aud": "authenticated", "role": "authenticated",
                    "email_confirmed_at": "2026-01-01T00:00:00Z",
                    "created_at": "2026-01-01T00:00:00Z"}
            db.users[email] = user
        return user

    # ---------------- control plane ----------------------------------------------------
    @app.post("/__test/seed")
    async def seed(request: Request):
        payload = await request.json()
        try:
            return {"ok": True, "seeded": db.seed(payload)}
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.get("/__test/rows/{table}")
    async def rows(table: str):
        return {"table": table, "rows": db.rows(table)}

    @app.post("/__test/reset")
    async def reset():
        db.reset()
        return {"ok": True}

    @app.get("/__test/state")
    async def state():
        return {"tables": {t: len(r) for t, r in db.tables.items()},
                "auth_users": len(db.users)}

    # ---------------- GoTrue ------------------------------------------------------------
    @app.post("/auth/v1/admin/users")
    async def admin_create_user(request: Request):
        body = await request.json()
        email = (body.get("email") or "").strip().lower()
        if not email:
            return JSONResponse({"msg": "email required"}, status_code=422)
        return JSONResponse(_user_for_email(email), status_code=201)

    @app.post("/auth/v1/admin/generate_link")
    async def generate_link(request: Request):
        body = await request.json()
        email = (body.get("email") or "").strip().lower()
        if not email:
            return JSONResponse({"msg": "email required"}, status_code=422)
        user = _user_for_email(email)
        otp = f"{secrets.randbelow(10**6):06d}"
        db.otps[email] = otp
        return {
            "id": user["id"], "email": email,
            "action_link": f"https://stub.invalid/verify?token=ht-{otp}&type=magiclink",
            "email_otp": otp, "hashed_token": f"ht-{otp}",
            "verification_type": body.get("type") or "magiclink",
            "redirect_to": "", "properties": {"email_otp": otp},
        }

    @app.post("/auth/v1/verify")
    async def verify(request: Request):
        body = await request.json()
        email = (body.get("email") or "").strip().lower()
        token = (body.get("token") or "").strip()
        if not email or db.otps.get(email) != token:
            return JSONResponse({"error_code": "otp_expired",
                                 "msg": "Token has expired or is invalid"}, status_code=403)
        db.otps.pop(email, None)
        user = _user_for_email(email)
        return {
            "access_token": _jwt_for(user), "token_type": "bearer", "expires_in": 3600,
            "expires_at": int(time.time()) + 3600,
            "refresh_token": "stub-rt-" + secrets.token_urlsafe(8), "user": user,
        }

    @app.get("/auth/v1/user")
    async def auth_user(request: Request):
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        payload = _jwt_payload(token)
        email = (payload.get("email") or "").lower()
        user = db.users.get(email)
        if not user or payload.get("sub") != user["id"]:
            return JSONResponse({"msg": "invalid JWT"}, status_code=401)
        return user

    # ---------------- PostgREST ---------------------------------------------------------
    @app.post("/rest/v1/rpc/enroll_stake_credential")
    async def rpc_enroll(request: Request):
        body = await request.json()
        stake_id = db.rpc_enroll_stake_credential(body)
        return JSONResponse(stake_id)  # PostgREST returns the scalar as a JSON string

    @app.post("/rest/v1/rpc/{name}")
    async def rpc_other(name: str):
        return JSONResponse({"message": f"rpc {name} not implemented in stub"},
                            status_code=404)

    @app.get("/rest/v1/{table}")
    async def rest_select(table: str, request: Request):
        params = dict(request.query_params)
        try:
            rows = db.select(table, params)
        except ValueError as exc:
            return JSONResponse({"message": str(exc)}, status_code=400)
        total = len(rows)
        start, end = _range_window(request, params, total)
        body = rows[start:end + 1] if total else []
        headers = {}
        prefer = request.headers.get("prefer", "")
        if "count=exact" in prefer:
            upper = f"{start}-{min(end, total - 1)}" if total else "*"
            headers["Content-Range"] = f"{upper}/{total}"
        status = 206 if request.headers.get("range") else 200
        return JSONResponse(body, status_code=status, headers=headers)

    @app.post("/rest/v1/{table}")
    async def rest_insert(table: str, request: Request):
        payload = await request.json()
        prefer = request.headers.get("prefer", "")
        written = db.insert(table, payload, prefer,
                            request.query_params.get("on_conflict"))
        if "return=representation" in prefer:
            return JSONResponse(written, status_code=201)
        return Response(status_code=201)

    @app.patch("/rest/v1/{table}")
    async def rest_update(table: str, request: Request):
        payload = await request.json()
        params = dict(request.query_params)
        updated = db.update(table, payload, params)
        if "return=representation" in request.headers.get("prefer", ""):
            return JSONResponse(updated, status_code=200)
        return Response(status_code=204)

    @app.delete("/rest/v1/{table}")
    async def rest_delete(table: str, request: Request):
        db.delete(table, dict(request.query_params))
        return Response(status_code=204)

    return app


def _range_window(request: Request, params: dict, total: int) -> tuple[int, int]:
    """Resolve the row window from Range header / limit / offset (PostgREST precedence-ish)."""
    rng = request.headers.get("range", "")
    if rng and "-" in rng:
        a, _, b = rng.partition("-")
        try:
            return int(a), int(b)
        except ValueError:
            pass
    offset = int(params.get("offset") or 0)
    limit = params.get("limit")
    end = (offset + int(limit) - 1) if limit else max(total - 1, 0)
    return offset, end
