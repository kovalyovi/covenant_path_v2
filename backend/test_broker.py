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
            {"email": "x@y.z", "cached": True, "unit_number": 503991, "stake_name": "Test Stake"},
            False, request_id="rid42")
        check("fast-lane authorized", out.get("authorized") is True)
        check("fast-lane marks fast", out.get("fast") is True)
        check("fast-lane offers nothing", out.get("can_enroll") is False and out.get("can_improve") is False)
        check("fast-lane audit phase", audited.get("phase") == "fast-lane")
        check("fast-lane audit request id", audited.get("request_id") == "rid42")
    finally:
        (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
         enroll._client_from_cookies, enroll._audit_login) = old


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


def main() -> int:
    print("broker tests")
    test_fast_lane_eval_zero_lcr()
    test_start_login_cached_identity_skips_lcr()
    test_identity_refresh_throttle()
    test_identity_refresh_never_raises()
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
