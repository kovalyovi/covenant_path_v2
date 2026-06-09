"""
Offline tests for the Church-login auth broker (backend/auth_broker).

No network / no LCR / no Supabase: we assert CORS behaviour (the regression that broke
login from *.pages.dev), the health endpoint, and that session minting fails loudly when
misconfigured. Run: python -m backend.test_broker  (or: pytest backend/test_broker.py)
"""

from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient

from backend.auth_broker.app import app, require_admin
from backend.auth_broker import admin, session_mint, okta_flow

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


def test_mfa_factor_parsing() -> None:
    # _factors extracts selectable 2nd factors (id + label + method) and drops the password option.
    rem = {"value": [{"name": "authenticator", "options": [
        {"label": "Password", "value": {"form": {"value": [
            {"name": "id", "value": "pwd"}, {"name": "methodType", "value": "password"}]}}},
        {"label": "Email", "value": {"form": {"value": [
            {"name": "id", "value": "em1"}, {"name": "methodType", "value": "email"}]}}},
    ]}]}
    factors = okta_flow._factors(rem)
    # Public projection (what the client receives) drops the password and keeps the email.
    check("MFA factor parse drops password + keeps email",
          okta_flow._public_factors(factors) == [{"id": "em1", "label": "Email", "method": "email"}])
    # The internal entry also carries the full authenticator object for the select POST.
    check("MFA factor carries full _auth object",
          factors[0]["_auth"] == {"id": "em1", "methodType": "email"})


def test_mfa_factor_full_authenticator_object() -> None:
    # A PHONE factor lists id + methodType + enrollmentId, and methodType may be a nested choice
    # (sms vs voice). The full authenticator object must include enrollmentId (or Okta never sends the
    # SMS) and resolve the nested choice to the first option. This is the Mission-KPIs parity fix.
    rem = {"value": [{"name": "authenticator", "options": [
        {"label": "Phone", "value": {"form": {"value": [
            {"name": "id", "value": "ph1"},
            {"name": "enrollmentId", "value": "enr9"},
            {"name": "methodType", "options": [
                {"label": "SMS", "value": "sms"}, {"label": "Voice", "value": "voice"}]},
        ]}}},
    ]}]}
    factors = okta_flow._factors(rem)
    check("phone factor authenticator object includes id+enrollmentId+methodType",
          factors[0]["_auth"] == {"id": "ph1", "enrollmentId": "enr9", "methodType": "sms"})
    check("phone factor public method comes from resolved nested choice",
          okta_flow._public_factors(factors) == [{"id": "ph1", "label": "Phone", "method": "sms"}])


def test_mfa_factor_types_from_authenticators() -> None:
    # When the IDX payload carries authenticators.value[] (id -> key), _factors uses the TYPE to drop
    # the password (even if the label is localized/odd) and tags each factor with its Okta key.
    payload = {
        "authenticators": {"value": [
            {"id": "pwd", "key": "okta_password"},
            {"id": "otp1", "key": "google_otp"},
        ]},
        "remediation": {"value": [{"name": "select-authenticator-authenticate", "value": [
            {"name": "authenticator", "options": [
                {"label": "Contraseña", "value": {"form": {"value": [{"name": "id", "value": "pwd"}]}}},
                {"label": "Google Authenticator",
                 "value": {"form": {"value": [{"name": "id", "value": "otp1"},
                                              {"name": "methodType", "value": "otp"}]}}},
            ]},
        ]}]},
    }
    types = okta_flow._authenticator_types(payload)
    sel = okta_flow._remediations(payload)["select-authenticator-authenticate"]
    factors = okta_flow._factors(sel, types)
    check("factor types map id->key", types == {"pwd": "okta_password", "otp1": "google_otp"})
    check("type-based password drop keeps only the TOTP factor",
          [f["type"] for f in factors] == ["google_otp"])


def test_select_factor_sends_full_object() -> None:
    # select_factor must POST the stored full authenticator object (id+methodType+enrollmentId), not
    # just {id}. We stub _follow to capture the body and assert the enrollmentId/methodType are sent.
    lid = "test-full-select"
    captured: dict = {}

    def fake_follow(_session, _rem, body, **_kw):
        captured.update(body)
        # Return a state with a challenge so select_factor treats it as a successful send.
        return {"stateHandle": "sh2", "remediation": {"value": [
            {"name": "challenge-authenticator", "href": "https://x/idx/challenge", "value": []}]}}

    factor = {"id": "ph1", "label": "Phone", "method": "sms", "type": "phone_number",
              "_auth": {"id": "ph1", "enrollmentId": "enr9", "methodType": "sms"}}
    okta_flow._PENDING[lid] = {
        "session": None, "verifier": "", "factors": [factor],
        "payload": {"stateHandle": "sh", "remediation": {"value": [
            {"name": "select-authenticator-authenticate", "href": "https://x/idx/challenge",
             "value": []}]}},
        "ts": time.time(),
    }
    saved = okta_flow._follow
    okta_flow._follow = fake_follow
    try:
        res = okta_flow.select_factor(lid, "ph1")
        check("select_factor returns code_sent", res.get("status") == "code_sent")
        check("select_factor POSTs full authenticator object (enrollmentId+methodType)",
              captured.get("authenticator") == {"id": "ph1", "enrollmentId": "enr9", "methodType": "sms"})
    finally:
        okta_flow._follow = saved
        okta_flow._PENDING.pop(lid, None)


def test_select_factor_no_challenge_raises() -> None:
    # If Okta returns neither a challenge nor success after select (e.g. an unsupported/failed factor),
    # select_factor surfaces the IDX message instead of silently proceeding to a dead code screen.
    lid = "test-no-challenge"

    def fake_follow(_session, _rem, _body, **_kw):
        return {"stateHandle": "sh2", "remediation": {"value": []},
                "messages": {"value": [{"message": "We can't verify with that method."}]}}

    factor = {"id": "wk1", "label": "Security Key", "method": None, "type": "webauthn",
              "_auth": {"id": "wk1"}}
    okta_flow._PENDING[lid] = {
        "session": None, "verifier": "", "factors": [factor],
        "payload": {"stateHandle": "sh", "remediation": {"value": [
            {"name": "select-authenticator-authenticate", "href": "https://x/idx/challenge",
             "value": []}]}},
        "ts": time.time(),
    }
    saved = okta_flow._follow
    okta_flow._follow = fake_follow
    try:
        okta_flow.select_factor(lid, "wk1")
        check("select_factor with no challenge -> AuthError", False)
    except okta_flow.AuthError as e:
        check("select_factor with no challenge -> AuthError", "verify with that method" in str(e))
    finally:
        okta_flow._follow = saved
        okta_flow._PENDING.pop(lid, None)


def test_idx_summary_pii_safe() -> None:
    # _idx_summary must describe SHAPE only — never names/emails/phones/codes/tokens from the payload.
    payload = {
        "stateHandle": "02.id.secrethandle",
        "user": {"value": {"identifier": "member@example.com", "profile": {"firstName": "Jane"}}},
        "authenticators": {"value": [{"id": "ph1", "key": "phone_number"},
                                     {"id": "em1", "key": "okta_email"}]},
        "remediation": {"value": [{"name": "select-authenticator-authenticate"},
                                  {"name": "challenge-authenticator"}]},
        "messages": {"value": [{"message": "Enter the code sent to (•••) •••-1234"}]},
    }
    s = okta_flow._idx_summary(payload)
    blob = repr(s)
    check("idx_summary lists remediation names",
          s["remediations"] == ["challenge-authenticator", "select-authenticator-authenticate"])
    check("idx_summary lists factor types", sorted(s["factor_types"]) == ["okta_email", "phone_number"])
    check("idx_summary flags messages present", s["has_messages"] is True)
    check("idx_summary leaks no email", "member@example.com" not in blob and "example.com" not in blob)
    check("idx_summary leaks no name", "Jane" not in blob)
    check("idx_summary leaks no stateHandle", "secrethandle" not in blob)
    check("idx_summary leaks no message text", "1234" not in blob)


def test_mfa_single_factor_select_noop() -> None:
    # MFA shape B: already at the code challenge with no factor list — select_factor is a no-op
    # ("code_sent") instead of raising, so the app's auto-send step proceeds to the code entry.
    lid = "test-single-factor"
    okta_flow._PENDING[lid] = {
        "session": None, "verifier": "",
        "payload": {"stateHandle": "sh", "remediation": {"value": [
            {"name": "challenge-authenticator", "href": "https://x/idx/challenge", "value": []}]}},
        "ts": time.time(),
    }
    try:
        res = okta_flow.select_factor(lid, "pending")
        check("single-factor select_factor returns code_sent", res.get("status") == "code_sent")
    except Exception:  # noqa: BLE001
        check("single-factor select_factor returns code_sent", False)
    finally:
        okta_flow._PENDING.pop(lid, None)


def test_provider_wipe_data() -> None:
    # /auth/wipe-data: the provider self-service tier of the admin wipe. Same RPC
    # (wipe_stake_members), but gated to the credential's principal_email — mirrors
    # revoke_credential. All REST calls are mocked (no network).

    # No bearer token -> 403 before any network call (verify_user short-circuits).
    r = client.post("/auth/wipe-data", json={"stake_id": "s1"})
    check("auth/wipe-data without token -> 403", r.status_code == 403)

    class _Resp:
        def __init__(self, status: int, body):
            self.status_code = status
            self._body = body
            self.text = "" if body is None else str(body)

        def json(self):
            return self._body

    calls: dict = {}
    creds: list = [{"principal_email": "provider@test"}]

    def fake_get(url, **_kw):
        calls["get_url"] = url
        return _Resp(200, list(creds))

    def fake_post(url, **kw):
        calls["post_url"] = url
        calls["post_json"] = kw.get("json")
        return _Resp(200, 42)  # RPC returns the deleted-row count

    saved_env = (admin.SUPABASE_URL, admin.SERVICE_KEY)
    saved_fns = (admin.verify_user, admin.requests.get, admin.requests.post)
    admin.SUPABASE_URL, admin.SERVICE_KEY = "https://x.supabase.co", "svc"
    admin.verify_user = lambda _auth: "provider@test"
    admin.requests.get, admin.requests.post = fake_get, fake_post
    try:
        hdr = {"Authorization": "Bearer t"}
        r = client.post("/auth/wipe-data", json={"stake_id": "s1"}, headers=hdr)
        check("provider wipe -> 200", r.status_code == 200)
        check("provider wipe returns status:wiped", r.json().get("status") == "wiped")
        check("wipe gate reads the stake credential",
              "stake_credentials" in calls.get("get_url", ""))
        check("wipe calls the wipe_stake_members RPC with the stake id",
              str(calls.get("post_url", "")).endswith("/rpc/wipe_stake_members")
              and calls.get("post_json") == {"p_stake_id": "s1"})

        # A signed-in NON-provider must be rejected (403) and never reach the RPC.
        calls.clear()
        admin.verify_user = lambda _auth: "someone-else@test"
        r = client.post("/auth/wipe-data", json={"stake_id": "s1"}, headers=hdr)
        check("non-provider wipe -> 403", r.status_code == 403)
        check("non-provider wipe never calls the RPC", "post_url" not in calls)

        # No credential on file for the stake -> 404.
        creds.clear()
        r = client.post("/auth/wipe-data", json={"stake_id": "s1"}, headers=hdr)
        check("wipe with no credential -> 404", r.status_code == 404)
    finally:
        admin.SUPABASE_URL, admin.SERVICE_KEY = saved_env
        admin.verify_user, admin.requests.get, admin.requests.post = saved_fns


def test_admin_requires_auth() -> None:
    # No bearer token -> 403 before any network call (verify_admin short-circuits).
    r = client.get("/admin/summary")
    check("admin/summary without token -> 403", r.status_code == 403)
    check("verify_admin('') raises NotAdmin", _raises(admin.NotAdmin, admin.verify_admin, ""))


def test_admin_actions_graceful_without_github() -> None:
    # An authenticated admin with no GITHUB_TOKEN still gets a (degraded) actions panel.
    app.dependency_overrides[require_admin] = lambda: "admin@test"
    saved = admin.GITHUB_TOKEN
    admin.GITHUB_TOKEN = ""
    try:
        r = client.get("/admin/actions")
        body = r.json()
        check("admin/actions 200 when github unset", r.status_code == 200)
        check("admin/actions reports configured:false", body.get("configured") is False)
        check("github_configured() false when unset", admin.github_configured() is False)
    finally:
        admin.GITHUB_TOKEN = saved
        app.dependency_overrides.clear()


def test_dispatch_allowlist() -> None:
    # Only known workflows may be dispatched — arbitrary input is rejected (400, no network).
    app.dependency_overrides[require_admin] = lambda: "admin@test"
    try:
        r = client.post("/admin/actions/run", json={"workflow": "evil.yml"})
        check("dispatch rejects unknown workflow -> 400", r.status_code == 400)
        check("admin.dispatch('evil.yml') raises AdminError",
              _raises(admin.AdminError, admin.dispatch, "evil.yml"))
        check("daily-sync.yml is dispatchable", "daily-sync.yml" in admin.DISPATCHABLE)
    finally:
        app.dependency_overrides.clear()


def _raises(exc, fn, *args) -> bool:
    try:
        fn(*args)
        return False
    except exc:
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    print("broker tests")
    test_health()
    test_cors()
    test_mint_misconfig()
    test_mint_empty_email()
    test_mfa_expiry()
    test_mfa_factor_parsing()
    test_mfa_factor_full_authenticator_object()
    test_mfa_factor_types_from_authenticators()
    test_select_factor_sends_full_object()
    test_select_factor_no_challenge_raises()
    test_idx_summary_pii_safe()
    test_mfa_single_factor_select_noop()
    test_provider_wipe_data()
    test_admin_requires_auth()
    test_admin_actions_graceful_without_github()
    test_dispatch_allowlist()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
