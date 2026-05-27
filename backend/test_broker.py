"""
Offline tests for the Church-login auth broker (backend/auth_broker).

No network / no LCR / no Supabase: we assert CORS behaviour (the regression that broke
login from *.pages.dev), the health endpoint, and that session minting fails loudly when
misconfigured. Run: python -m backend.test_broker  (or: pytest backend/test_broker.py)
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.auth_broker.app import app
from backend.auth_broker import session_mint, okta_flow

client = TestClient(app)
_PASS = 0
_FAIL = 0


def check(name: str, cond: bool) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ok   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}")


def _preflight(origin: str):
    return client.options("/auth/password", headers={
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })


def test_health() -> None:
    r = client.get("/health")
    check("health 200", r.status_code == 200)
    check("health ok:true", r.json().get("ok") is True)


def test_cors() -> None:
    # Allowed origins must receive an Access-Control-Allow-Origin echo on preflight.
    for ok_origin in ("https://covenant-path-app.pages.dev",
                      "https://app.membercovenantpath.org",
                      "https://abc123.covenant-path-app.pages.dev",
                      "http://localhost:8080"):
        r = _preflight(ok_origin)
        check(f"preflight allows {ok_origin}",
              r.headers.get("access-control-allow-origin") == ok_origin)
    # A foreign origin must NOT be granted CORS (no ACAO header echoing it).
    bad = "https://evil.example.com"
    r = _preflight(bad)
    check("preflight denies foreign origin",
          r.headers.get("access-control-allow-origin") not in (bad, "*"))


def test_mint_misconfig() -> None:
    saved = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")}
    try:
        raised = False
        try:
            session_mint.mint_otp("someone@example.com")
        except session_mint.MintError:
            raised = True
        check("mint raises MintError without SUPABASE env", raised)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_mint_empty_email() -> None:
    # Empty email is invalid regardless of config.
    os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
    raised = False
    try:
        session_mint.mint_otp("")
    except session_mint.MintError:
        raised = True
    check("mint raises MintError on empty email", raised)


def test_mfa_expiry() -> None:
    # An unknown/expired login_id must be rejected, not crash.
    raised = False
    try:
        okta_flow.verify_mfa("does-not-exist", "000000")
    except okta_flow.AuthError:
        raised = True
    check("verify_mfa on unknown login_id -> AuthError", raised)
    raised = False
    try:
        okta_flow.select_factor("does-not-exist", "f")
    except okta_flow.AuthError:
        raised = True
    check("select_factor on unknown login_id -> AuthError", raised)


def main() -> int:
    print("broker tests")
    test_health()
    test_cors()
    test_mint_misconfig()
    test_mint_empty_email()
    test_mfa_expiry()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
