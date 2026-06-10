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
from backend.auth_broker import admin, session_mint, okta_flow, enroll
import backend.auth_broker.app as appmod

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


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_credential_embed_shape() -> None:
    """REGRESSION: PostgREST returns a to-one embedded resource as a JSON OBJECT, not a list.
    The old `for c in embed` iterated a dict's KEYS (strings) -> `c.get(...)` raised -> the offer
    logic silently treated a HEALTHY enrolled stake as un-enrolled (the 'always prompted to set up
    sync even though my credential is stored' bug). Both shapes must read identically."""
    # --- pure normalizer: object, list, None, revoked-only, junk ---
    obj = {"revoked": False, "coverage": {"complete": True}, "access_rank": 1000}
    check("embed: single OBJECT yields the credential",
          enroll._first_usable_credential(obj) == obj)
    check("embed: single-element LIST yields the credential",
          enroll._first_usable_credential([obj]) == obj)
    check("embed: None yields nothing",
          enroll._first_usable_credential(None) is None)
    check("embed: empty list yields nothing",
          enroll._first_usable_credential([]) is None)
    check("embed: a revoked OBJECT is not usable",
          enroll._first_usable_credential({"revoked": True, "coverage": {}}) is None)
    check("embed: revoked-then-active LIST picks the active one",
          enroll._first_usable_credential(
              [{"revoked": True}, {"revoked": False, "coverage": {"complete": True}}])
          == {"revoked": False, "coverage": {"complete": True}})
    check("embed: malformed (string key leak) is tolerated, not raised",
          enroll._first_usable_credential(["revoked", "coverage"]) is None)

    # --- end-to-end: _stored_credential_summary against the REAL object shape ---
    saved_get = enroll.requests.get
    try:
        # The exact shape PostgREST returned in prod: stake_credentials is an OBJECT.
        enroll.requests.get = lambda *a, **k: _FakeResp(
            [{"id": "x", "stake_credentials": {"revoked": False,
                                               "coverage": {"complete": True},
                                               "access_rank": 1000}}])
        summary = enroll._stored_credential_summary(503991)
        check("stored-credential summary: OBJECT embed -> non-None (can_enroll stays False)",
              summary is not None and summary.get("access_rank") == 1000)

        # No credential at all -> None (offer enrollment is correct here).
        enroll.requests.get = lambda *a, **k: _FakeResp([{"id": "x", "stake_credentials": None}])
        check("stored-credential summary: no credential -> None",
              enroll._stored_credential_summary(503991) is None)

        # Revoked credential -> None (offer enrollment).
        enroll.requests.get = lambda *a, **k: _FakeResp(
            [{"id": "x", "stake_credentials": {"revoked": True}}])
        check("stored-credential summary: revoked -> None",
              enroll._stored_credential_summary(503991) is None)

        # No such stake -> None.
        enroll.requests.get = lambda *a, **k: _FakeResp([])
        check("stored-credential summary: unknown stake -> None",
              enroll._stored_credential_summary(999999) is None)
    finally:
        enroll.requests.get = saved_get


def test_enrolled_stakes_object_embed() -> None:
    """REGRESSION: admin.enrolled_stakes must read the same OBJECT-shaped embed (it did
    `creds[0]` on a dict -> KeyError -> the ops 'Enrolled stakes' panel failed to load)."""
    saved = {k: getattr(admin, k) for k in
             ("_member_counts", "_reauths_30d", "_jobs_last_7d")}
    saved_get = admin.requests.get
    saved_cfg = (admin.SUPABASE_URL, admin.SERVICE_KEY)
    try:
        admin.SUPABASE_URL = admin.SUPABASE_URL or "https://test.supabase.co"
        admin.SERVICE_KEY = admin.SERVICE_KEY or "test-key"
        admin._member_counts = lambda: {"stake-uuid": 84}
        admin._reauths_30d = lambda: {503991: 0}
        admin._jobs_last_7d = lambda: {}
        admin.requests.get = lambda *a, **k: _FakeResp([{
            "id": "stake-uuid", "name": "Raleigh", "unit_number": 503991,
            "last_synced_at": None, "sync_state": None, "onboarded_at": None,
            "stake_credentials": {  # OBJECT, not list — the prod shape
                "principal_name": "Ilia", "principal_email": "ilia@example.com",
                "revoked": False, "coverage": {"complete": True}, "access_rank": 1000,
                "updated_at": None, "last_failed_at": None, "last_error": None,
                "last_succeeded_at": None, "has_refresh_token": True}}])
        rows = admin._enrolled_stakes()  # inner fn -> bypass the TTL cache
        check("enrolled_stakes: OBJECT embed loads without raising", len(rows) == 1)
        cred = (rows[0] or {}).get("credential") or {}
        check("enrolled_stakes: reads the credential's principal",
              cred.get("principal_email") == "ilia@example.com")
        check("enrolled_stakes: derives active state for a healthy cred",
              cred.get("state") == "active")
    finally:
        admin.requests.get = saved_get
        admin.SUPABASE_URL, admin.SERVICE_KEY = saved_cfg
        for k, v in saved.items():
            setattr(admin, k, v)


def test_endpoint_health_trend() -> None:
    """The passive cross-run endpoint trend: aggregate sync_diagnostics across runs into per-endpoint
    calls/errors/error_pct + by-hour error rate, with route-pattern grouping and a verdict."""
    saved_get = admin.requests.get
    saved_cfg = (admin.SUPABASE_URL, admin.SERVICE_KEY)
    try:
        admin.SUPABASE_URL = admin.SUPABASE_URL or "https://test.supabase.co"
        admin.SERVICE_KEY = admin.SERVICE_KEY or "test-key"
        # Two runs, different hours; details/{id} ids differ per row → must group to one route.
        rows = [
            {"run_at": "2026-06-09T02:00:00+00:00", "kind": "sync", "payload": {"requests": {"endpoints": [
                {"endpoint": "/api/report/one-work/details/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", "calls": 50, "errors": 0, "avg_ms": 800, "max_ms": 1200},
                {"endpoint": "/api/report/one-work/progress-record", "calls": 10, "errors": 5, "avg_ms": 21000, "max_ms": 40000},
            ]}}},
            {"run_at": "2026-06-09T14:00:00+00:00", "kind": "probe", "payload": {"requests": {"endpoints": [
                {"endpoint": "/api/report/one-work/details/f6e5d4c3b2a1098765432100aabbccdd", "calls": 50, "errors": 14, "avg_ms": 900, "max_ms": 1500},
                {"endpoint": "/api/report/one-work/progress-record", "calls": 10, "errors": 1, "avg_ms": 9000, "max_ms": 22000},
            ]}}},
        ]
        admin.requests.get = lambda *a, **k: _FakeResp(rows)
        h = admin.endpoint_health(days=14)
        eps = {e["endpoint"]: e for e in h["endpoints"]}
        check("endpoint-health: runs counted", h["runs"] == 2)
        check("endpoint-health: details/{id} grouped across differing ids",
              "/api/report/one-work/details/{id}" in eps)
        det = eps.get("/api/report/one-work/details/{id}", {})
        check("endpoint-health: details calls summed (50+50)", det.get("calls") == 100)
        check("endpoint-health: details error_pct = 14/100", det.get("error_pct") == 14.0)
        check("endpoint-health: details verdict 'hot' (>=10%)", det.get("verdict") == "hot")
        pr = eps.get("/api/report/one-work/progress-record", {})
        check("endpoint-health: progress-record errors summed (5+1)", pr.get("errors") == 6)
        check("endpoint-health: by-hour buckets present (02 worse than 14 for progress)",
              "2" in h["by_hour"] and "14" in h["by_hour"])
    finally:
        admin.requests.get = saved_get
        admin.SUPABASE_URL, admin.SERVICE_KEY = saved_cfg


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


def test_fast_lane_eval_zero_lcr() -> None:
    # Cached-identity repeat login + usable credential on file → authorization is ONE DB check;
    # any LcrClient construction here means the zero-LCR fast lane regressed.
    old = (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
           enroll._client_from_cookies, enroll._audit_login)
    enroll.SUPABASE_URL, enroll.SERVICE_KEY = "https://example.invalid", "key"
    enroll._stored_credential_summary = lambda unit: {"coverage": {}, "access_rank": 3}

    def _boom(cookies):
        raise AssertionError("fast lane must not touch LCR")

    enroll._client_from_cookies = _boom
    audited: dict = {}
    enroll._audit_login = lambda *a, **k: audited.update(k)
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "x@y.z", "cached": True, "unit_number": 503991, "stake_name": "Test Stake",
             "has_calling": True},
            False, request_id="rid42")
        check("fast-lane authorized", out.get("authorized") is True)
        check("fast-lane marks fast", out.get("fast") is True)
        check("fast-lane offers nothing", out.get("can_enroll") is False and out.get("can_improve") is False)
        check("fast-lane audit phase", audited.get("phase") == "fast-lane")
        check("fast-lane audit request id", audited.get("request_id") == "rid42")
    finally:
        (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
         enroll._client_from_cookies, enroll._audit_login) = old


def _gate_env(ctx, cred_summary):
    """Patch enroll for a calling-gate test: no network, a fake LcrClient whose user_context()
    returns `ctx`, a stubbed stored-credential lookup, and captured audit/cache writes.
    Returns (audited, cached, restore_fn)."""
    import types as _types
    from backend.auth_broker import identity_cache
    old = (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
           enroll._client_from_cookies, enroll._audit_login, identity_cache.set_unit)
    enroll.SUPABASE_URL, enroll.SERVICE_KEY = "https://example.invalid", "key"
    enroll._stored_credential_summary = lambda unit: cred_summary
    enroll._client_from_cookies = lambda cookies: _types.SimpleNamespace(user_context=lambda: ctx)
    audited: dict = {}
    cached: dict = {}
    enroll._audit_login = lambda *a, **k: audited.update(k)
    identity_cache.set_unit = (
        lambda username, identity, unit, stake, has_calling=None:
        cached.update({"unit": unit, "has_calling": has_calling}))

    def _restore():
        (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
         enroll._client_from_cookies, enroll._audit_login, identity_cache.set_unit) = old

    return audited, cached, _restore


def test_calling_gate_blocks_no_calling_member() -> None:
    # The wife-with-no-calling repro: a valid Church account whose user-context shows NO calling
    # (activePosition/positions/childUnits all null — HAR-verified shape) must be blocked even
    # though her stake has a usable credential on file (previously the FAST path authorized her).
    import types as _types
    ctx = _types.SimpleNamespace(active_position=None, positions=[], child_units=[],
                                 unit_number=1102966, unit_name="Green Level Ward")
    audited, cached, restore = _gate_env(ctx, {"coverage": {}, "access_rank": 3})
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "member@example.org"}, False, request_id="rid-gate")
        check("gate blocks no-calling member", out.get("authorized") is False)
        check("gate offers nothing",
              out.get("can_enroll") is False and out.get("can_improve") is False)
        check("gate audit phase", audited.get("phase") == "gate")
        check("gate caches has_calling=False", cached.get("has_calling") is False)
    finally:
        restore()


def test_calling_gate_blocks_enroll_attempt() -> None:
    # store=True (an explicit enroll) from a no-calling account is blocked the same way — it must
    # never reach the access scrape or the enroll RPC.
    import types as _types
    ctx = _types.SimpleNamespace(active_position=None, positions=[], child_units=[],
                                 unit_number=1102966, unit_name="Green Level Ward")
    audited, _cached, restore = _gate_env(ctx, None)
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "member@example.org"}, True, request_id="rid-gate2")
        check("gate blocks enroll attempt", out.get("authorized") is False)
        check("gate enroll not stored", out.get("stored") is False)
        check("gate enroll audit blocked", audited.get("phase") == "gate")
    finally:
        restore()


def test_calling_gate_passes_leader() -> None:
    # NO REGRESSION for real leaders: an active position (a brand-new stake-clerk account, say)
    # passes the gate and the credential-on-file FAST path authorizes exactly as before — and the
    # cache records has_calling=True so their NEXT login rides the zero-LCR lane.
    import types as _types
    ctx = _types.SimpleNamespace(active_position="Stake Clerk", positions=[{"name": "Stake Clerk"}],
                                 child_units=[], unit_number=503991, unit_name="Test Stake")
    audited, cached, restore = _gate_env(ctx, {"coverage": {}, "access_rank": 3})
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "clerk@example.org"}, False, request_id="rid-gate3")
        check("leader passes gate (fast path)", out.get("authorized") is True)
        check("leader audit phase fast", audited.get("phase") == "fast")
        check("leader caches has_calling=True", cached.get("has_calling") is True)
    finally:
        restore()


def test_calling_gate_partial_context_passes() -> None:
    # Err-toward-allow: a leader whose user-context came back DEGRADED (no active position but
    # child units present — or any single signal) must NOT be blocked by the gate.
    from types import SimpleNamespace
    for shim, label in [
        (SimpleNamespace(active_position=None, positions=[],
                         child_units=[SimpleNamespace(name="W1", unit_number=1, type="WARD")],
                         unit_number=503991, unit_name="Test Stake"), "child units only"),
        (SimpleNamespace(active_position=None, positions=[{"name": "High Councilor"}],
                         child_units=[], unit_number=503991, unit_name="Test Stake"), "positions only"),
    ]:
        audited, _cached, restore = _gate_env(shim, {"coverage": {}, "access_rank": 1})
        try:
            out = enroll.evaluate_and_maybe_store(
                [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
                {"email": "leader@example.org"}, False)
            check(f"partial context passes ({label})", out.get("authorized") is True)
        finally:
            restore()


def test_calling_gate_check_sync() -> None:
    # The synchronous first-login gate (one user_context call, no scrape): blocks a clear no-calling
    # account, passes a leader, and ALLOWS on an LCR error (err toward allow — never block a leader
    # on a slow/down LCR). Caches has_calling either way.
    import types as _types
    from backend.auth_broker import identity_cache
    old = (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._user_context_with_establish,
           identity_cache.set_unit, enroll._audit_login)
    enroll.SUPABASE_URL, enroll.SERVICE_KEY = "https://example.invalid", "key"
    cached: dict = {}
    identity_cache.set_unit = (lambda u, i, unit, stake, has_calling=None:
                               cached.update({"has_calling": has_calling}))
    audited: dict = {}
    enroll._audit_login = lambda *a, **k: audited.update(k)
    cookies = [{"name": "s", "value": "x", "domain": "d", "path": "/"}]
    try:
        enroll._user_context_with_establish = lambda c: (
            _types.SimpleNamespace(active_position=None, positions=[], child_units=[],
                                   unit_number=1102966, unit_name="Green Level Ward"), c)
        out = enroll.calling_gate_check(cookies, {"email": "m@e.org"}, request_id="r")
        check("sync gate blocks no-calling", out is not None and out.get("authorized") is False)
        check("sync gate caches has_calling False", cached.get("has_calling") is False)
        check("sync gate audit phase gate-sync", audited.get("phase") == "gate-sync")

        cached.clear()
        enroll._user_context_with_establish = lambda c: (
            _types.SimpleNamespace(active_position="Bishop", positions=[{"name": "Bishop"}],
                                   child_units=[], unit_number=503991, unit_name="Test Stake"), c)
        out2 = enroll.calling_gate_check(cookies, {"email": "l@e.org"})
        check("sync gate passes leader (None)", out2 is None)
        check("sync gate caches has_calling True", cached.get("has_calling") is True)

        def _boom(c):
            raise RuntimeError("LCR down")

        enroll._user_context_with_establish = _boom
        out3 = enroll.calling_gate_check(cookies, {"email": "x@e.org"})
        check("sync gate allows on LCR error", out3 is None)
    finally:
        (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._user_context_with_establish,
         identity_cache.set_unit, enroll._audit_login) = old


def test_login_eval_first_login_sync_gate() -> None:
    # _login_eval on an UNCACHED (first) login runs the synchronous gate: a block verdict is returned
    # in the response and the full eval is NEVER run; a pass (None) falls through to the full eval.
    old_check = enroll.calling_gate_check
    old_eval = enroll.evaluate_and_maybe_store
    eval_called = {"v": False}
    enroll.evaluate_and_maybe_store = (
        lambda *a, **k: (eval_called.__setitem__("v", True), {"authorized": True})[1])
    res = {"cookies": [{"name": "s", "value": "x", "domain": "d", "path": "/"}],
           "identity": {"email": "m@e.org"}}  # uncached, no has_calling → sync gate runs
    try:
        enroll.calling_gate_check = (lambda *a, **k: {"authorized": False, "can_enroll": False,
                                                      "can_improve": False, "stored": False})
        out = appmod._login_eval(res, False, "rid-sg")
        check("first-login gate blocks in response", out.get("authorized") is False)
        check("first-login gate skips full eval", eval_called["v"] is False)

        eval_called["v"] = False
        enroll.calling_gate_check = lambda *a, **k: None
        out2 = appmod._login_eval(res, False, "rid-sg2")
        check("first-login gate pass -> full eval runs", eval_called["v"] is True)
        check("first-login gate pass -> authorized true", out2.get("authorized") is True)
    finally:
        enroll.calling_gate_check = old_check
        enroll.evaluate_and_maybe_store = old_eval


def test_login_eval_fast_calling_gate() -> None:
    # The "no calling but still signed in / saw the set-up-sync prompt" fix: a cached identity with
    # has_calling=False must be blocked SYNCHRONOUSLY in _login_eval (in the login response, zero
    # LCR) — not deferred to the background eval whose verdict lands after the ≤5s budget. A cached
    # leader (has_calling=True) is NOT fast-blocked; the eval runs as before.
    called = {"eval": False}
    old = enroll.evaluate_and_maybe_store
    enroll.evaluate_and_maybe_store = (
        lambda *a, **k: (called.__setitem__("eval", True), {"authorized": True})[1])
    try:
        res_block = {"cookies": [{"name": "x", "value": "y", "domain": "d", "path": "/"}],
                     "identity": {"email": "member@example.org", "cached": True,
                                  "has_calling": False, "unit_number": 1102966,
                                  "stake_name": "Green Level Ward", "login_username": "okotoks"}}
        out = appmod._login_eval(res_block, False, "rid-fastgate")
        check("fast gate: authorized false", out.get("authorized") is False)
        check("fast gate: eval skipped (zero LCR)", called["eval"] is False)
        check("fast gate: no offers", not out.get("can_enroll") and not out.get("can_improve"))

        called["eval"] = False
        res_ok = {"cookies": [{"name": "x", "value": "y", "domain": "d", "path": "/"}],
                  "identity": {"email": "leader@example.org", "cached": True, "has_calling": True,
                               "unit_number": 503991, "stake_name": "Test Stake",
                               "login_username": "leader"}}
        out2 = appmod._login_eval(res_ok, False, "rid-okgate")
        check("leader cached: not fast-blocked (eval runs)", called["eval"] is True)
        check("leader cached: authorized true", out2.get("authorized") is True)
    finally:
        enroll.evaluate_and_maybe_store = old


def test_zero_lcr_lane_requires_has_calling() -> None:
    # A cached identity WITHOUT has_calling=true (pre-0044 row, or a blocked member) must fall
    # through to the LCR-backed path — where the gate re-runs — instead of being authorized blind.
    import types as _types
    ctx = _types.SimpleNamespace(active_position=None, positions=[], child_units=[],
                                 unit_number=1102966, unit_name="Green Level Ward")
    audited, _cached, restore = _gate_env(ctx, {"coverage": {}, "access_rank": 3})
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "member@example.org", "cached": True, "unit_number": 503991,
             "stake_name": "Test Stake"},  # no has_calling → no zero-LCR shortcut
            False)
        check("cached row without has_calling falls through to gate",
              out.get("authorized") is False and audited.get("phase") == "gate")
    finally:
        restore()


def test_start_login_cached_identity_skips_lcr() -> None:
    # Okta verifies the password; church_identities supplies the identity. The LCR identity leg and
    # the (dead) token exchange must not run on a plain repeat sign-in.
    from backend.auth_broker import identity_cache
    old_drive = okta_flow._drive_to_password
    old_get = identity_cache.get
    old_ident = okta_flow._identity
    old_exchange = okta_flow._exchange_code
    okta_flow._drive_to_password = lambda s, u, p, lid: ({"successWithInteractionCode": {"value": []}}, "ver")
    identity_cache.get = lambda u: {"username": "canonical", "email": "x@y.z", "name": "X",
                                    "unit_number": 1, "stale": False}

    def _no_lcr(*a, **k):
        raise AssertionError("cached lane must not fetch the LCR identity")

    def _no_exchange(*a, **k):
        raise AssertionError("plain sign-in must skip the token exchange")

    okta_flow._identity = _no_lcr
    okta_flow._exchange_code = _no_exchange
    try:
        res = okta_flow.start_login("USER", "pw", want_refresh_token=False, allow_cached_identity=True)
        check("cached lane success", res.get("status") == "success")
        check("cached lane email", res["identity"].get("email") == "x@y.z")
        check("cached lane marker", res["identity"].get("cached") is True)
        check("cached lane keeps typed username", res["identity"].get("login_username") == "USER")
    finally:
        okta_flow._drive_to_password = old_drive
        identity_cache.get = old_get
        okta_flow._identity = old_ident
        okta_flow._exchange_code = old_exchange


def test_identity_refresh_throttle() -> None:
    # A login burst must trigger ONE background refresh per user, not one per login (B).
    import time as _t
    enroll._REFRESH_AT.clear()
    check("first refresh due", enroll._refresh_due("user_a") is True)
    check("burst suppressed", enroll._refresh_due("user_a") is False)
    check("other user independent", enroll._refresh_due("user_b") is True)
    enroll._REFRESH_AT["user_a"] = _t.monotonic() - enroll._REFRESH_TTL_S - 1
    check("due again after TTL", enroll._refresh_due("user_a") is True)
    enroll._REFRESH_AT.clear()


def test_identity_refresh_never_raises() -> None:
    # An LCR outage during the background refresh must be swallowed (the login already answered).
    enroll._REFRESH_AT.clear()
    old = okta_flow._identity
    okta_flow._identity = lambda s, lid: (_ for _ in ()).throw(RuntimeError("LCR down"))
    try:
        enroll.refresh_cached_identity(
            [{"name": "x", "value": "y", "domain": "d", "path": "/"}], "user_c")
        check("refresh swallowed the LCR failure", True)
    except Exception:  # noqa: BLE001
        check("refresh swallowed the LCR failure", False)
    finally:
        okta_flow._identity = old
        enroll._REFRESH_AT.clear()


def test_identity_email_binding() -> None:
    # The link that lets a provisioned leader (e.g. a high councilor) actually SEE their stake:
    # a Church login stamps its verified email onto user_roles rows matched by lcr_person_uuid
    # (== auth/me churchCMISUUID). Best-effort — must never raise, never fire without a real uuid.
    import types as _types
    uuid_ok = "3c888028-fa94-4422-9bdd-c6c48ffa7c4d"
    old = (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll.requests)
    enroll.SUPABASE_URL, enroll.SERVICE_KEY = "https://example.invalid", "key"
    calls: list[dict] = []

    def _patch(url, headers=None, params=None, json=None, timeout=None):
        calls.append({"url": url, "params": params, "json": json})
        resp = _FakeResp([{"role": "stake_leader"}], 200)
        resp.text = '[{"role":"stake_leader"}]'
        return resp

    enroll.requests = _types.SimpleNamespace(patch=_patch)
    try:
        enroll._bind_identity_email({"email": "HC@Example.org", "cmis_uuid": uuid_ok})
        check("bind: one PATCH", len(calls) == 1)
        check("bind: targets user_roles", calls and calls[0]["url"].endswith("/rest/v1/user_roles"))
        check("bind: matches by person uuid",
              calls and calls[0]["params"].get("lcr_person_uuid") == f"eq.{uuid_ok}")
        check("bind: stamps lowercased email", calls and calls[0]["json"] == {"email": "hc@example.org"})

        calls.clear()
        enroll._bind_identity_email({"email": "hc@example.org"})                      # no uuid
        enroll._bind_identity_email({"cmis_uuid": uuid_ok})                            # no email
        enroll._bind_identity_email({"email": "hc@example.org", "cmis_uuid": "junk"})  # not a uuid
        check("bind: no-ops never PATCH", len(calls) == 0)

        def _boom(*a, **k):
            raise RuntimeError("REST down")

        enroll.requests = _types.SimpleNamespace(patch=_boom)
        try:
            enroll._bind_identity_email({"email": "hc@example.org", "cmis_uuid": uuid_ok})
            check("bind: REST failure swallowed", True)
        except Exception:  # noqa: BLE001
            check("bind: REST failure swallowed", False)
    finally:
        enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll.requests = old


def test_enrollment_status_no_role_resolves_stake_via_identity_cache() -> None:
    # G: a no-role caller WITH an identity-cache row + an EXISTING stake row gets that stake's
    # real state (honest "no access with your calling" UI). A never-enrolled stake (no stakes
    # row) stays legacy — preserving the "set up stake sync" CTA for first-time leaders — and so
    # do email-OTP-only users (no cache row).
    import types as _types
    old_env = (admin.SUPABASE_URL, admin.SERVICE_KEY)
    old_one, old_requests = admin._one, admin.requests
    admin.SUPABASE_URL, admin.SERVICE_KEY = "https://example.invalid", "key"
    admin.requests = _types.SimpleNamespace(get=lambda *a, **k: _FakeResp([], 404))

    def one_with_cache(table, params):
        if table == "stake_credentials" and "principal_email" in params:
            return None  # not a first-enroller provider
        if table == "church_identities":
            return {"unit_number": 503991, "stake_name": "Test Stake"}
        if table == "stakes":
            return {"id": "stk1", "name": "Test Stake", "unit_number": 503991,
                    "last_synced_at": "2026-06-09T11:00:00+00:00"}
        if table == "stake_credentials":
            return {"revoked": False, "last_failed_at": None}
        return None

    try:
        admin._one = one_with_cache
        out = admin.enrollment_status("released@example.com", "")
        check("released: status no_role", out.get("status") == "no_role")
        check("released: stake resolved", out.get("stake_name") == "Test Stake")
        check("released: credential active", (out.get("credential") or {}).get("state") == "active")
        check("released: member_count omitted", out.get("member_count") == 0)

        admin._one = lambda table, params: (one_with_cache(table, params)
                                            if table != "stakes" else None)
        out_new = admin.enrollment_status("released@example.com", "")
        check("never-enrolled stake: legacy payload",
              (out_new.get("credential") or {}).get("state") == "none")

        admin._one = lambda table, params: None
        out2 = admin.enrollment_status("emailonly@example.com", "")
        check("email-only: legacy payload", (out2.get("credential") or {}).get("state") == "none")
        check("email-only: no stake leak", out2.get("stake_name") is None)
    finally:
        admin.SUPABASE_URL, admin.SERVICE_KEY = old_env
        admin._one, admin.requests = old_one, old_requests


def test_classify_lcr_failure() -> None:
    # 2026-06-10 outage postmortem: login_audit stored only the friendly message, so a hard 502, a
    # rejected SSO, and a timeout were indistinguishable. The classifier is what makes the next
    # outage diagnosable from the audit row alone.
    import requests as _rq
    from lcr_client.okta_login import LoginError, classify_lcr_failure

    k, r = classify_lcr_failure(LoginError("verification /api/auth/me failed: 502 text/plain"))
    check("classify: auth/me 502 -> lcr_5xx", k == "lcr_5xx" and r.startswith("auth/me 502"))
    k, _r = classify_lcr_failure(LoginError("verification /api/auth/me failed: 403 text/html"))
    check("classify: auth/me 403 -> lcr_http (no retry)", k == "lcr_http")
    k, r = classify_lcr_failure(LoginError(
        "SSO did not complete — landed back on Okta. The Okta session cookie was not honored."))
    check("classify: SSO bounce -> sso_rejected",
          k == "sso_rejected" and r == "SSO landed back on Okta")
    # Wrapped causes (the shape _finish_success actually sees) must classify by the CHAIN.
    try:
        try:
            raise _rq.exceptions.ConnectTimeout("hang")
        except Exception as inner:
            raise LoginError("identity failed") from inner
    except LoginError as outer:
        k, _r = classify_lcr_failure(outer)
        check("classify: chained timeout -> timeout", k == "timeout")
    k, _r = classify_lcr_failure(_rq.exceptions.ConnectionError("reset"))
    check("classify: connection error -> network", k == "network")
    k, _r = classify_lcr_failure(RuntimeError("???"))
    check("classify: unknown -> other", k == "other")


def test_establish_and_verify_retry_behavior() -> None:
    # The identity leg must survive a BLIP (one instant 5xx) but not loop on real answers:
    # lcr_http (e.g. 403) fails immediately, an SSO rejection is re-driven exactly once.
    from lcr_client import okta_login as ol

    old_est, old_ver = ol._establish_lcr_session, ol._verify
    calls = {"est": 0, "ver": 0}
    try:
        # 1) 502 once, then success — establish must NOT be redone (cookies are fine).
        def _est(session, timeout=60):
            calls["est"] += 1

        def _ver_blip(session, timeout=60):
            calls["ver"] += 1
            if calls["ver"] == 1:
                raise ol.LoginError("verification /api/auth/me failed: 502 text/plain")
            return {"email": "x@y.z"}

        ol._establish_lcr_session, ol._verify = _est, _ver_blip
        out = ol.establish_and_verify(object(), backoff_s=0)
        check("retry: survives one 502 blip", out.get("email") == "x@y.z")
        check("retry: establish ran once", calls["est"] == 1)

        # 2) non-5xx HTTP answer (403) is a real answer — no retry.
        calls.update(est=0, ver=0)

        def _ver_403(session, timeout=60):
            calls["ver"] += 1
            raise ol.LoginError("verification /api/auth/me failed: 403 text/html")

        ol._verify = _ver_403
        try:
            ol.establish_and_verify(object(), backoff_s=0)
            check("retry: 403 raises", False)
        except ol.LoginError:
            check("retry: 403 raises", True)
        check("retry: 403 not retried", calls["ver"] == 1)

        # 3) SSO rejection: re-driven exactly once, then surfaces.
        calls.update(est=0, ver=0)

        def _est_bounce(session, timeout=60):
            calls["est"] += 1
            raise ol.LoginError("SSO did not complete — landed back on Okta. x")

        ol._establish_lcr_session = _est_bounce
        try:
            ol.establish_and_verify(object(), backoff_s=0)
            check("retry: persistent SSO bounce raises", False)
        except ol.LoginError:
            check("retry: persistent SSO bounce raises", True)
        check("retry: SSO re-driven exactly once", calls["est"] == 2)
    finally:
        ol._establish_lcr_session, ol._verify = old_est, old_ver


def test_identity_failure_kind_message_and_audit() -> None:
    # End-to-end through the API layer: a hard 502 outage yields a 503 whose detail says LCR (not
    # us, not the account) is down, and the audit row records the ROOT CAUSE + identity phase —
    # exactly what was missing while diagnosing vzhdanov's 2026-06-10 attempts.
    from lcr_client.okta_login import LoginError

    old_drive, old_identity = okta_flow._drive_to_password, okta_flow._identity
    old_get = okta_flow.identity_cache.get
    old_audit = appmod._audit_okta_failure
    audited: dict = {}
    okta_flow._drive_to_password = (
        lambda s, u, p, lid: ({"successWithInteractionCode": {"value": []}}, "ver"))
    okta_flow.identity_cache.get = lambda u: None
    okta_flow._identity = (lambda s, lid: (_ for _ in ()).throw(
        LoginError("verification /api/auth/me failed: 502 text/plain")))
    appmod._audit_okta_failure = (
        lambda who, stage, error, rid, duration_ms=None, phase=None:
        audited.update(who=who, stage=stage, error=error, duration_ms=duration_ms, phase=phase))
    okta_flow._note_lcr_identity(True, "")  # reset outage state
    try:
        r = client.post("/auth/password", json={"username": "vzh", "password": "pw"})
        check("identity 502 -> HTTP 503", r.status_code == 503)
        detail = r.json().get("detail", "")
        check("identity 502 detail blames LCR, not the user",
              "LCR itself appears to be down" in detail and "account or permissions" in detail)
        check("audit stage lcr_identity_failed", audited.get("stage") == "lcr_identity_failed")
        check("audit error is the ROOT CAUSE", str(audited.get("error", "")).startswith("auth/me 502"))
        check("audit phase identity:lcr_5xx", audited.get("phase") == "identity:lcr_5xx")
        check("audit duration recorded", isinstance(audited.get("duration_ms"), int))
    finally:
        okta_flow._drive_to_password, okta_flow._identity = old_drive, old_identity
        okta_flow.identity_cache.get = old_get
        appmod._audit_okta_failure = old_audit
        okta_flow._note_lcr_identity(True, "")


def test_lcr_outage_tracker_and_health() -> None:
    # One failing account is one weird account; TWO distinct accounts = an outage. /health then says
    # so (lcr: degraded + since), the user message gains the "failing for everyone" suffix, and any
    # full-identity success resets it.
    okta_flow._note_lcr_identity(True, "")  # clean slate
    okta_flow._note_lcr_identity(False, "userA")
    check("outage: one user is not an outage", okta_flow.lcr_outage_since() is None)
    okta_flow._note_lcr_identity(False, "userB")
    check("outage: two distinct users is", okta_flow.lcr_outage_since() is not None)
    check("outage: message suffix names the start",
          "failing for everyone since" in okta_flow._outage_suffix())
    r = client.get("/health")
    check("health: lcr degraded", r.json().get("lcr") == "degraded")
    check("health: failing-since stamped", bool(r.json().get("lcr_failing_since")))
    okta_flow._note_lcr_identity(True, "userA")
    check("outage: success resets", okta_flow.lcr_outage_since() is None)
    check("health: lcr ok again", client.get("/health").json().get("lcr") == "ok")


def main() -> int:
    print("broker tests")
    test_fast_lane_eval_zero_lcr()
    test_calling_gate_blocks_no_calling_member()
    test_calling_gate_blocks_enroll_attempt()
    test_calling_gate_passes_leader()
    test_calling_gate_partial_context_passes()
    test_calling_gate_check_sync()
    test_login_eval_first_login_sync_gate()
    test_login_eval_fast_calling_gate()
    test_zero_lcr_lane_requires_has_calling()
    test_start_login_cached_identity_skips_lcr()
    test_classify_lcr_failure()
    test_establish_and_verify_retry_behavior()
    test_identity_failure_kind_message_and_audit()
    test_lcr_outage_tracker_and_health()
    test_identity_refresh_throttle()
    test_identity_refresh_never_raises()
    test_identity_email_binding()
    test_enrollment_status_no_role_resolves_stake_via_identity_cache()
    test_health()
    test_cors()
    test_credential_embed_shape()
    test_enrolled_stakes_object_embed()
    test_endpoint_health_trend()
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
