"""
Mock Okta/identity host (id.churchofjesuschrist.org stand-in) — the IDX interaction-code
flow exactly as lcr_client.okta_login / backend.auth_broker.okta_flow drive it:

  POST /oauth2/default/v1/interact          -> {"interaction_handle"}
  POST /idp/idx/introspect                  -> stateHandle + remediation [identify]
  POST /idp/idx/identify                    -> challenge-authenticator(password)   (no-MFA users)
                                               select-authenticator-authenticate(Password) (MFA users)
  POST /idp/idx/challenge   (select)        -> challenge-authenticator
  POST /idp/idx/challenge/answer            -> success / MFA remediation / 401 messages
  POST /oauth2/default/v1/token             -> tokens for interaction_code (refresh grant
                                               rejected with invalid_client, like the real
                                               Church Okta — verified 2026-06-09)
  GET  /oauth2/default/v1/authorize         -> SSO leg: session cookie (or id_token_hint with
                                               prompt=none) -> 302 redirect_uri?code=...;
                                               otherwise (or scenario sso_reject) lands on /signin
  GET  /signin                              -> 200 HTML (the "landed back on Okta" terminal page)

Every remediation carries name + href pointing back at THIS mock, because the production
client POSTs to remediation["href"] (self-adapting); 4xx bodies carry messages.value[].
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from tests.mock_lcr.personas import (
    EMAIL_AUTH_ID, LOCKED_USERNAME, MFA_CODE, PASSWORD_AUTH_ID, PERSONAS,
    PHONE_AUTH_ID, PHONE_ENROLLMENT_ID,
)
from tests.mock_lcr.state import MockChurchState


def _messages(*texts: str) -> dict:
    return {"type": "array",
            "value": [{"message": t, "i18n": {"key": "errors.mock"}, "class": "ERROR"}
                      for t in texts]}


def _remediation(name: str, href: str, value: list) -> dict:
    return {"rel": ["create-form"], "name": name, "href": href, "method": "POST",
            "accepts": "application/json; okta-version=1.0.0", "value": value}


def _state_field(sh: str) -> dict:
    return {"name": "stateHandle", "required": True, "value": sh,
            "visible": False, "mutable": False}


class IdxResponses:
    """IDX payload builders, parameterized by the identity base (remediation hrefs)."""

    def __init__(self, state: MockChurchState):
        self.state = state

    @property
    def base(self) -> str:
        return self.state.identity_base

    def introspect(self, sh: str) -> dict:
        return {
            "version": "1.0.0",
            "stateHandle": sh,
            "expiresAt": "2099-01-01T00:00:00.000Z",
            "intent": "LOGIN",
            "remediation": {"type": "array", "value": [
                _remediation("identify", f"{self.base}/idp/idx/identify", [
                    {"name": "identifier", "label": "Username"},
                    {"name": "rememberMe", "label": "Keep me signed in", "type": "boolean"},
                    _state_field(sh),
                ]),
            ]},
        }

    def password_challenge(self, sh: str) -> dict:
        return {
            "version": "1.0.0",
            "stateHandle": sh,
            "remediation": {"type": "array", "value": [
                _remediation("challenge-authenticator", f"{self.base}/idp/idx/challenge/answer", [
                    {"name": "credentials", "type": "object", "form": {"value": [
                        {"name": "passcode", "label": "Password", "secret": True}]}},
                    _state_field(sh),
                ]),
            ]},
            "currentAuthenticatorEnrollment": {"type": "object", "value": {
                "type": "password", "key": "okta_password", "id": PASSWORD_AUTH_ID,
                "displayName": "Password"}},
        }

    def select_password(self, sh: str) -> dict:
        """select-authenticator-authenticate offering only Password (the first factor)."""
        return {
            "version": "1.0.0",
            "stateHandle": sh,
            "remediation": {"type": "array", "value": [
                _remediation("select-authenticator-authenticate",
                             f"{self.base}/idp/idx/challenge", [
                                 {"name": "authenticator", "type": "object", "options": [
                                     {"label": "Password", "value": {"form": {"value": [
                                         {"name": "id", "required": True,
                                          "value": PASSWORD_AUTH_ID, "mutable": False},
                                         {"name": "methodType", "required": False,
                                          "value": "password", "mutable": False}]}}},
                                 ]},
                                 _state_field(sh),
                             ]),
            ]},
        }

    def select_mfa(self, sh: str) -> dict:
        """MFA shape A: a 2nd-factor menu (Email + Phone) + authenticators.value[{id,key}].
        The phone option requires the FULL authenticator object on select (id + enrollmentId
        + methodType) — exactly the Okta behavior the broker's _authenticator_object exists for."""
        return {
            "version": "1.0.0",
            "stateHandle": sh,
            "remediation": {"type": "array", "value": [
                _remediation("select-authenticator-authenticate",
                             f"{self.base}/idp/idx/challenge", [
                                 {"name": "authenticator", "type": "object", "options": [
                                     {"label": "Email", "value": {"form": {"value": [
                                         {"name": "id", "required": True,
                                          "value": EMAIL_AUTH_ID, "mutable": False},
                                         {"name": "methodType", "required": False,
                                          "value": "email", "mutable": False}]}}},
                                     {"label": "Phone", "value": {"form": {"value": [
                                         {"name": "id", "required": True,
                                          "value": PHONE_AUTH_ID, "mutable": False},
                                         {"name": "enrollmentId", "required": True,
                                          "value": PHONE_ENROLLMENT_ID, "mutable": False},
                                         {"name": "methodType", "type": "string",
                                          "required": False, "options": [
                                              {"label": "SMS", "value": "sms"},
                                              {"label": "Voice call", "value": "voice"}]}]}}},
                                 ]},
                                 _state_field(sh),
                             ]),
            ]},
            "authenticators": {"type": "array", "value": [
                {"id": EMAIL_AUTH_ID, "key": "okta_email", "type": "email",
                 "displayName": "Email"},
                {"id": PHONE_AUTH_ID, "key": "phone_number", "type": "phone",
                 "displayName": "Phone"},
            ]},
        }

    def mfa_code_challenge(self, sh: str, factor_key: str = "okta_email") -> dict:
        """The enter-your-code challenge (shape B's first answer, and post-select for shape A)."""
        fid = EMAIL_AUTH_ID if factor_key == "okta_email" else PHONE_AUTH_ID
        return {
            "version": "1.0.0",
            "stateHandle": sh,
            "remediation": {"type": "array", "value": [
                _remediation("challenge-authenticator", f"{self.base}/idp/idx/challenge/answer", [
                    {"name": "credentials", "type": "object", "form": {"value": [
                        {"name": "passcode", "label": "Enter code"}]}},
                    _state_field(sh),
                ]),
            ]},
            "currentAuthenticatorEnrollment": {"type": "object", "value": {
                "type": "email" if factor_key == "okta_email" else "phone",
                "key": factor_key, "id": fid,
                "displayName": "Email" if factor_key == "okta_email" else "Phone"}},
        }

    def success(self, sh: str, username: str) -> dict:
        code = self.state.issue_interaction_code(username)
        return {
            "version": "1.0.0",
            "stateHandle": sh,
            "successWithInteractionCode": {
                "rel": ["create-form"],
                "name": "successWithInteractionCode",
                "href": f"{self.base}/oauth2/default/v1/token",
                "method": "POST",
                "accepts": "application/x-www-form-urlencoded",
                "value": [
                    {"name": "grant_type", "required": True, "value": "interaction_code"},
                    {"name": "interaction_code", "required": True, "value": code},
                    {"name": "client_id", "required": True, "value": "0oajwqqtpz7f8r1OD357"},
                    {"name": "code_verifier", "required": True},
                ],
            },
        }


def create_identity_app(state: MockChurchState) -> FastAPI:
    app = FastAPI(title="mock Church identity (Okta IDX)", docs_url=None, redoc_url=None)
    idx = IdxResponses(state)

    @app.middleware("http")
    async def _count(request: Request, call_next):
        state.record_hit(request.url.path)
        if state.scenario == "identity_timeout" and not request.url.path.startswith("/__test"):
            await asyncio.sleep(state.sleep_seconds)
        return await call_next(request)

    # ---- control plane (shared state: either host's /__test works) -------------------
    _mount_control(app, state)

    # ---- OAuth interact / token -------------------------------------------------------
    @app.post("/oauth2/default/v1/interact")
    async def interact():
        ih, _sh = state.new_transaction()
        return {"interaction_handle": ih}

    @app.post("/oauth2/default/v1/token")
    async def token(request: Request):
        # parse x-www-form-urlencoded by hand (no python-multipart dependency needed)
        from urllib.parse import parse_qs
        raw = (await request.body()).decode("utf-8", errors="replace")
        form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        grant = form.get("grant_type", "")
        if grant == "interaction_code":
            username = state.interaction_codes.pop(form.get("interaction_code", ""), None)
            if username is None:
                return JSONResponse({"error": "invalid_grant",
                                     "error_description": "interaction_code is invalid or expired"},
                                    status_code=400)
            return state.issue_tokens(username)
        if grant == "refresh_token":
            # Faithful to the real Church Okta: this public client cannot redeem refresh
            # tokens headlessly (invalid_client, verified 2026-06-09).
            return JSONResponse({"error": "invalid_client",
                                 "error_description": "Client authentication failed."},
                                status_code=401)
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    # ---- IDX --------------------------------------------------------------------------
    @app.post("/idp/idx/introspect")
    async def introspect(request: Request):
        body = await request.json()
        found = state.txn_by_interaction(body.get("interactionHandle", ""))
        if not found:
            return JSONResponse({"version": "1.0.0",
                                 "messages": _messages("The session has expired.")},
                                status_code=401)
        sh, _txn = found
        return idx.introspect(sh)

    @app.post("/idp/idx/identify")
    async def identify(request: Request):
        body = await request.json()
        sh = body.get("stateHandle", "")
        txn = state.txn(sh)
        if txn is None:
            return JSONResponse({"messages": _messages("The session has expired.")},
                                status_code=401)
        username = (body.get("identifier") or "").strip()
        txn["username"] = username
        persona = PERSONAS.get(username)
        if persona is not None and persona.mfa:
            # MFA accounts go through the authenticator menu first (Password is the option),
            # like the live flow; the password challenge follows the select.
            txn["step"] = "password-select"
            return idx.select_password(sh)
        txn["step"] = "password"
        return idx.password_challenge(sh)

    @app.post("/idp/idx/challenge")
    async def challenge(request: Request):
        """select-authenticator-authenticate target — both the password select and the
        shape-A MFA factor select land here."""
        body = await request.json()
        sh = body.get("stateHandle", "")
        txn = state.txn(sh)
        if txn is None:
            return JSONResponse({"messages": _messages("The session has expired.")},
                                status_code=401)
        auth = body.get("authenticator") or {}
        aid = auth.get("id")
        if txn["step"] == "password-select":
            if aid != PASSWORD_AUTH_ID:
                return JSONResponse({"stateHandle": sh,
                                     "messages": _messages("Authenticator not available.")},
                                    status_code=400)
            txn["step"] = "password"
            return idx.password_challenge(sh)
        if txn["step"] == "mfa-select":
            if aid == PHONE_AUTH_ID and not auth.get("enrollmentId"):
                # The real-Okta silent failure: a phone select without the full authenticator
                # object is ACCEPTED but no code is ever sent — modeled as a 200 with no
                # challenge remediation (what the broker's select_factor guards against).
                return {"version": "1.0.0", "stateHandle": sh,
                        "remediation": {"type": "array", "value": []},
                        "messages": _messages("Unable to send the code.")}
            if aid not in (EMAIL_AUTH_ID, PHONE_AUTH_ID):
                return JSONResponse({"stateHandle": sh,
                                     "messages": _messages("Authenticator not available.")},
                                    status_code=400)
            txn["step"] = "mfa-answer"
            txn["factor"] = "okta_email" if aid == EMAIL_AUTH_ID else "phone_number"
            # "select sends nothing real": no email/SMS leaves the mock; the fixed test
            # passcode (123456) simply becomes answerable.
            return idx.mfa_code_challenge(sh, txn["factor"])
        return JSONResponse({"stateHandle": sh,
                             "messages": _messages("No authenticator selection pending.")},
                            status_code=400)

    @app.post("/idp/idx/challenge/answer")
    async def challenge_answer(request: Request):
        body = await request.json()
        sh = body.get("stateHandle", "")
        txn = state.txn(sh)
        if txn is None:
            return JSONResponse({"messages": _messages("The session has expired.")},
                                status_code=401)
        passcode = (body.get("credentials") or {}).get("passcode", "")
        username = txn.get("username") or ""
        persona = PERSONAS.get(username)

        if txn["step"] == "password":
            if username == LOCKED_USERNAME:
                return JSONResponse(
                    {"stateHandle": sh, "version": "1.0.0",
                     "messages": _messages(
                         "Your account is locked. Please contact your administrator.")},
                    status_code=401)
            if persona is None or passcode != persona.password:
                return JSONResponse(
                    {"stateHandle": sh, "version": "1.0.0",
                     "messages": _messages("Authentication failed")},
                    status_code=401)
            if persona.mfa == "shape_a":
                txn["step"] = "mfa-select"
                return idx.select_mfa(sh)
            if persona.mfa == "shape_b":
                # Shape B: Okta auto-sent a code and goes straight to the challenge.
                txn["step"] = "mfa-answer"
                txn["factor"] = "okta_email"
                return idx.mfa_code_challenge(sh, "okta_email")
            return _success_response(idx, state, sh, username)

        if txn["step"] == "mfa-answer":
            if passcode != MFA_CODE:
                # Transaction stays alive at the same step — a corrected code must still work.
                return JSONResponse(
                    {"stateHandle": sh, "version": "1.0.0",
                     "messages": _messages("Invalid Passcode/Answer")},
                    status_code=401)
            return _success_response(idx, state, sh, username)

        return JSONResponse({"stateHandle": sh,
                             "messages": _messages("No challenge pending.")},
                            status_code=400)

    # ---- SSO leg ------------------------------------------------------------------------
    @app.get("/oauth2/default/v1/authorize")
    async def authorize(request: Request):
        q = request.query_params
        redirect_uri = q.get("redirect_uri", "")
        state_param = q.get("state", "")
        if state.scenario == "sso_reject":
            return RedirectResponse(f"{state.identity_base}/signin?error=login_required",
                                    status_code=302)
        username = state.okta_sessions.get(request.cookies.get("idx", ""))
        if username is None and q.get("id_token_hint"):
            username = state.id_tokens.get(q.get("id_token_hint", ""))
        if username is None or not redirect_uri.startswith(state.lcr_base):
            if q.get("prompt") == "none":
                return RedirectResponse(f"{state.identity_base}/signin?error=login_required",
                                        status_code=302)
            return RedirectResponse(f"{state.identity_base}/signin", status_code=302)
        code = state.issue_auth_code(username)
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{sep}code={code}&state={state_param}",
                                status_code=302)

    @app.get("/signin")
    async def signin():
        return HTMLResponse("<!doctype html><title>Mock Church sign-in</title>"
                            "<h1>Sign in (mock Okta)</h1>")

    return app


def _success_response(idx: IdxResponses, state: MockChurchState, sh: str, username: str):
    """Terminal IDX success: payload + the org-wide Okta session cookie (what the later
    /authorize SSO hop honors)."""
    payload = idx.success(sh, username)
    resp = JSONResponse(payload)
    resp.set_cookie("idx", state.issue_okta_session(username), path="/", httponly=True)
    return resp


def _mount_control(app: FastAPI, state: MockChurchState) -> None:
    @app.post("/__test/control")
    async def control(request: Request):
        body = await request.json()
        try:
            state.set_scenario(body.get("scenario", "healthy"), body.get("sleep_seconds"))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return {"ok": True, **state.snapshot()}

    @app.get("/__test/state")
    async def test_state():
        return state.snapshot()

    @app.post("/__test/reset")
    async def reset():
        state.reset()
        return {"ok": True}


# re-exported for lcr_app (same handlers on both hosts)
mount_control = _mount_control
