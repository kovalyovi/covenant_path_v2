"""
Mock LCR host (lcr.churchofjesuschrist.org stand-in).

Serves exactly what the production client code reads during login/enroll:
  GET  /api/auth/login    -> 302 {identity}/oauth2/default/v1/authorize?... (the SSO hop;
                             establish_lcr_session follows the chain, failure = final URL
                             on the identity netloc)
  GET  /api/auth/callback -> validates ?code, sets the LCR session cookie, 302 /
  GET  /api/auth/me       -> persona identity JSON (lcr_5xx scenario: instant 502 text/plain,
                             the 2026-06-10 outage shape)
  GET  /api/user-context  -> persona context (both the UserContext.from_api keys and the
                             platformUserContext tree access.runner_positions walks)
  GET  /other/access-table-> HTML with the __NEXT_DATA__ access matrix
  POST /mlt/orgs          -> empty React-flight stream (leadership name enrichment no-ops)

Unauthenticated API hits redirect to the identity /signin page — like real LCR — which the
client surfaces as AuthExpiredError (and is also why /api/auth/me sees "200 text/html").
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
)

from tests.mock_lcr.identity_app import mount_control
from tests.mock_lcr.personas import PERSONAS, access_table_html, auth_me, user_context
from tests.mock_lcr.state import MockChurchState


def create_lcr_app(state: MockChurchState) -> FastAPI:
    app = FastAPI(title="mock LCR", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def _count(request: Request, call_next):
        state.record_hit(request.url.path)
        if state.scenario == "identity_timeout" and request.url.path.startswith("/api/auth/login"):
            # the SSO hop is identity-bound too; let it hang with the identity host
            await asyncio.sleep(state.sleep_seconds)
        return await call_next(request)

    _mount = mount_control
    _mount(app, state)

    def _session_user(request: Request) -> str | None:
        return state.lcr_sessions.get(request.cookies.get("lcr_session", ""))

    def _login_redirect() -> RedirectResponse:
        return RedirectResponse(f"{state.identity_base}/signin", status_code=302)

    def _maybe_502(path: str) -> Response | None:
        """The lcr_5xx scenario: /api/auth/me + /api/user-context answer an INSTANT 502 with a
        text/plain body — the exact outage shape classify_lcr_failure fingerprints."""
        if state.scenario == "lcr_5xx" and path in ("/api/auth/me", "/api/user-context"):
            return PlainTextResponse("Bad Gateway", status_code=502, media_type="text/plain")
        return None

    # ---- SSO ---------------------------------------------------------------------------
    @app.get("/api/auth/login")
    async def auth_login(request: Request):
        return_to = request.query_params.get("returnTo", "/")
        return RedirectResponse(
            f"{state.identity_base}/oauth2/default/v1/authorize"
            f"?client_id=0oajwqqtpz7f8r1OD357&response_type=code&scope=openid"
            f"&redirect_uri={state.lcr_base}/api/auth/callback"
            f"&state=mocklcr&returnTo={return_to}",
            status_code=302)

    @app.get("/api/auth/callback")
    async def auth_callback(request: Request):
        code = request.query_params.get("code", "")
        username = state.auth_codes.pop(code, None)
        if username is None:
            return _login_redirect()
        resp = RedirectResponse(f"{state.lcr_base}/", status_code=302)
        resp.set_cookie("lcr_session", state.issue_lcr_session(username), path="/",
                        httponly=True)
        # Production LCR names its session cookie `appSession`; the credential-capture flow
        # (web_session._open_lcr_authorize / _follow_success) gates on a cookie whose name starts
        # with "appSession". Set it alongside lcr_session (which the mock keys its own auth on) so the
        # web lane recognizes the established session. Both ride the captured/replayed cookie jar.
        resp.set_cookie("appSession", state.issue_lcr_session(username), path="/", httponly=True)
        return resp

    @app.get("/")
    async def home():
        return HTMLResponse("<!doctype html><title>Mock LCR</title><h1>Mock LCR home</h1>")

    # ---- identity + context --------------------------------------------------------------
    @app.get("/api/auth/me")
    async def api_auth_me(request: Request):
        err = _maybe_502("/api/auth/me")
        if err is not None:
            return err
        username = _session_user(request)
        if username is None or username not in PERSONAS:
            return _login_redirect()
        return JSONResponse(auth_me(PERSONAS[username]))

    @app.get("/api/user-context")
    async def api_user_context(request: Request):
        err = _maybe_502("/api/user-context")
        if err is not None:
            return err
        username = _session_user(request)
        if username is None or username not in PERSONAS:
            return _login_redirect()
        return JSONResponse(user_context(PERSONAS[username]))

    # ---- access matrix + leadership ---------------------------------------------------
    @app.get("/other/access-table")
    async def other_access_table(request: Request):
        if _session_user(request) is None:
            return _login_redirect()
        # slow_access: the access SCRAPE outlasts the broker's eval budget (B6 deferred-eval
        # scenario) while the identity/user-context legs stay fast — set sleep_seconds small
        # (a few seconds), unlike identity_timeout's caller-killing 70s default.
        if state.scenario == "slow_access":
            await asyncio.sleep(state.sleep_seconds)
        return HTMLResponse(access_table_html())

    @app.post("/mlt/orgs")
    async def mlt_orgs(request: Request):
        # The leadership Server Action. An EMPTY flight stream is a valid response the
        # client's name-enrichment treats as "nothing new" (logged + skipped).
        if _session_user(request) is None:
            return _login_redirect()
        return PlainTextResponse("0:[]\n", media_type="text/x-component")

    # Realistic enough for anything else the client probes during a test run.
    @app.get("/favicon.ico")
    async def favicon():
        return PlainTextResponse("", status_code=404)

    return app
