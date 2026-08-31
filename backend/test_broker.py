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

# Rate limiting has its own unit test (test_ratelimit_check_caps_attempts); disable the HTTP-path
# limiter here so this suite's many same-IP TestClient calls don't trip a 429 (BACKEND-01).
os.environ.setdefault("RL_DISABLED", "1")

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
    # A foreign origin must NOT be granted CORS (no ACAO header echoing it). BACKEND-07: a stranger's
    # *.pages.dev deploy must be denied now that the regex is pinned to this project's Pages site.
    for bad in ("https://evil.example.com", "https://evil.pages.dev"):
        r = _preflight(bad)
        check(f"preflight denies {bad}",
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


def test_enrolled_stakes_self_renewing_from_membertools() -> None:
    """A1 (REAL BUG): the self_renewing chip showed the OPPOSITE of truth — it read the OLD LCR
    has_refresh_token (~always false), but 45-day self-renewal now lives in the Member Tools refresh
    token (migration 0049). self_renewing must be true when membertools_refresh_enc is set even with
    has_refresh_token false; the payload carries a derived token_expires_in_days
    (45 − days since minted; null with no token). The raw membertools_minted_at is NOT echoed —
    no client reads it; clients consume only the computed days-left."""
    from datetime import datetime, timedelta, timezone
    saved = {k: getattr(admin, k) for k in ("_member_counts", "_reauths_30d", "_jobs_last_7d")}
    saved_get = admin.requests.get
    saved_cfg = (admin.SUPABASE_URL, admin.SERVICE_KEY)
    minted = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    try:
        admin.SUPABASE_URL = admin.SUPABASE_URL or "https://test.supabase.co"
        admin.SERVICE_KEY = admin.SERVICE_KEY or "test-key"
        admin._member_counts = lambda: {}
        admin._reauths_30d = lambda: {}
        admin._jobs_last_7d = lambda: {}
        # Member Tools token present, LCR refresh token absent (the prod reality the bug got backwards).
        admin.requests.get = lambda *a, **k: _FakeResp([{
            "id": "s1", "name": "Raleigh", "unit_number": 503991,
            "last_synced_at": None, "sync_state": None, "onboarded_at": None,
            "stake_credentials": {
                "principal_name": "Ilia", "principal_email": "ilia@example.com",
                "revoked": False, "coverage": {"complete": True}, "access_rank": 1000,
                "updated_at": None, "last_failed_at": None, "last_error": None,
                "last_succeeded_at": None, "has_refresh_token": False,
                "membertools_refresh_enc": "enc-blob", "membertools_minted_at": minted}}])
        cred = (admin._enrolled_stakes()[0] or {}).get("credential") or {}
        check("self_renewing true from membertools token (not has_refresh_token)",
              cred.get("self_renewing") is True)
        # membertools_minted_at is no longer echoed (no client consumer) — only the derived
        # days-left is surfaced; that's what the chip reads.
        check("membertools_minted_at not echoed", "membertools_minted_at" not in cred)
        check("token_expires_in_days ~ 45-5 = 40", cred.get("token_expires_in_days") == 40)

        # No Member Tools token AND no LCR token -> not self-renewing, null countdown.
        admin.requests.get = lambda *a, **k: _FakeResp([{
            "id": "s2", "name": "Cary", "unit_number": 11,
            "last_synced_at": None, "sync_state": None, "onboarded_at": None,
            "stake_credentials": {
                "principal_email": "x@y.z", "revoked": False, "coverage": {},
                "has_refresh_token": False, "membertools_refresh_enc": None,
                "membertools_minted_at": None}}])
        cred2 = (admin._enrolled_stakes()[0] or {}).get("credential") or {}
        check("no token -> self_renewing false", cred2.get("self_renewing") is False)
        check("no token -> token_expires_in_days null", cred2.get("token_expires_in_days") is None)

        # An expired token (minted 50 days ago) yields a NEGATIVE countdown (red in the UI).
        old_minted = (datetime.now(timezone.utc) - timedelta(days=50)).isoformat()
        admin.requests.get = lambda *a, **k: _FakeResp([{
            "id": "s3", "name": "Apex", "unit_number": 12,
            "last_synced_at": None, "sync_state": None, "onboarded_at": None,
            "stake_credentials": {
                "principal_email": "z@y.z", "revoked": False, "coverage": {},
                "has_refresh_token": False, "membertools_refresh_enc": "enc",
                "membertools_minted_at": old_minted}}])
        cred3 = (admin._enrolled_stakes()[0] or {}).get("credential") or {}
        check("expired token -> negative countdown", (cred3.get("token_expires_in_days") or 0) < 0)
    finally:
        admin.requests.get = saved_get
        admin.SUPABASE_URL, admin.SERVICE_KEY = saved_cfg
        for k, v in saved.items():
            setattr(admin, k, v)


def test_enrollment_status_patriarchal_signal() -> None:
    """enrollment_status exposes the two signals that gate the 'refresh patriarchal blessing' banner:
    patriarchal_pending (real, baptized members still missing the profile-only patriarchal flag) and
    credential.can_refresh_patriarchal (this calling can read the member-profile flag). Fails pre-fix:
    neither field existed."""
    from backend.auth_broker import admin

    class _Resp:
        def __init__(self, payload, status=200, content_range=None):
            self._p, self.status_code = payload, status
            self.headers = {"Content-Range": content_range} if content_range else {}

        def json(self):
            return self._p

    def make_get(features):
        def _get(url, headers=None, params=None, timeout=None):
            p = params or {}
            if url.endswith("/user_roles"):
                return _Resp([{"stake_id": "stake-1"}])
            if url.endswith("/stakes"):
                return _Resp([{"name": "Test Stake", "unit_number": 503991, "last_synced_at": None}])
            if url.endswith("/members"):
                # the patriarchal-pending count is distinguished by its filter
                if "patriarchal_blessing" in p:
                    return _Resp([], status=206, content_range="0-0/3")
                return _Resp([], status=206, content_range="0-0/42")
            if url.endswith("/stake_credentials"):
                return _Resp([{"coverage": {"complete": True, "features": features},
                               "principal_email": "leader@example.org", "principal_name": "Leader",
                               "revoked": False, "last_failed_at": None, "updated_at": None}])
            return _Resp([])
        return _get

    saved_get = admin.requests.get
    saved_cfg = (admin.SUPABASE_URL, admin.SERVICE_KEY)
    try:
        admin.SUPABASE_URL = admin.SUPABASE_URL or "https://test.supabase.co"
        admin.SERVICE_KEY = admin.SERVICE_KEY or "test-key"

        admin.requests.get = make_get(["menu.view.member.profiles", "menu.covenant.path"])
        out = admin.enrollment_status("leader@example.org", "")
        assert out["patriarchal_pending"] == 3, out
        assert out["credential"]["can_refresh_patriarchal"] is True, out

        # a calling WITHOUT profile access can't refresh patriarchal → the banner stays hidden
        admin.requests.get = make_get(["menu.covenant.path"])
        out2 = admin.enrollment_status("leader@example.org", "")
        assert out2["credential"]["can_refresh_patriarchal"] is False, out2
    finally:
        admin.requests.get = saved_get
        admin.SUPABASE_URL, admin.SERVICE_KEY = saved_cfg
    print("  ok enrollment_status exposes patriarchal_pending + can_refresh_patriarchal")


def test_profile_refresh_worker_fills_via_live_session() -> None:
    """The re-auth background worker fills EVERY empty profile field for members with gaps, using the
    just-captured live session, via report.refresh_profile_fields_ex — PATCHing the returned patch
    back; a member the profile can't read (empty patch) is skipped, never clobbered."""
    import types as _types
    from backend.auth_broker import enroll
    from covenant_path import report

    patched: list = []

    class _Resp:
        def __init__(self, payload, status=200):
            self._p, self.status_code, self.headers = payload, status, {}

        def json(self):
            return self._p

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/stakes"):
            return _Resp([{"id": "stake-1"}])
        if url.endswith("/members"):
            return _Resp([{"person_uuid": "U1"}, {"person_uuid": "U2"}, {"person_uuid": "U3"}])
        return _Resp([])

    def fake_patch(url, headers=None, params=None, json=None, timeout=None):
        uuid = (params or {}).get("person_uuid", "").replace("eq.", "")
        patched.append((uuid, json or {}))
        return _Resp(None, status=204)

    # U1 fills patriarchal+calling; U2 fills only patriarchal; U3 unreadable → skipped. The reason
    # rides along so the worker can tell "no record to read" from "the session is dead".
    fills = {"U1": ({"patriarchal_blessing": "Yes", "calling": "No"}, "filled"),
             "U2": ({"patriarchal_blessing": "No"}, "filled"), "U3": ({}, "not_found")}
    diag_rows: list = []

    def fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("/sync_diagnostics"):
            diag_rows.append(json or {})
        return _Resp(None, status=201)

    saved = (enroll.requests.get, enroll.requests.patch, enroll.requests.post,
             enroll._client_from_cookies,
             report.refresh_profile_fields_ex, enroll.SUPABASE_URL, enroll.SERVICE_KEY)
    try:
        enroll.SUPABASE_URL = enroll.SUPABASE_URL or "https://test.supabase.co"
        enroll.SERVICE_KEY = enroll.SERVICE_KEY or "test-key"
        enroll.requests.get = fake_get
        enroll.requests.patch = fake_patch
        enroll.requests.post = fake_post
        enroll._client_from_cookies = lambda cookies: _types.SimpleNamespace(session=object())
        report.refresh_profile_fields_ex = lambda client, row: fills[row["person_uuid"]]
        enroll._REFRESH_PROGRESS.clear()
        enroll._refresh_profile_worker([{"name": "x"}], 503991)
    finally:
        (enroll.requests.get, enroll.requests.patch, enroll.requests.post,
         enroll._client_from_cookies,
         report.refresh_profile_fields_ex, enroll.SUPABASE_URL, enroll.SERVICE_KEY) = saved
    by_uuid = dict(patched)
    assert set(by_uuid.get("U1", {})) == {"patriarchal_blessing", "calling", "field_meta"}, patched
    assert by_uuid["U1"]["patriarchal_blessing"] == "Yes" and by_uuid["U1"]["calling"] == "No"
    # The fill stamps per-field freshness for exactly the fields it wrote (f = fetched, t = tried).
    fm = by_uuid["U1"]["field_meta"]
    assert set(fm) == {"patriarchal_blessing", "calling"} and all(
        e.get("f") and e.get("t") for e in fm.values()), fm
    assert by_uuid.get("U2", {}).get("patriarchal_blessing") == "No", patched
    assert "U3" not in by_uuid, f"unreadable member must NOT be patched: {patched}"
    # Progress is published for the status route, and the outcome recorded for the ops console.
    prog = enroll._REFRESH_PROGRESS.get(503991) or {}
    assert prog.get("state") == "done" and prog.get("total") == 3 and prog.get("filled") == 2, prog
    assert diag_rows and diag_rows[0]["kind"] == "profile_refresh" and \
        diag_rows[0]["payload"] == {"source": "reauth", "total": 3, "filled": 2,
                                    "outcome": "done",
                                    # WHY each member ended unfilled, so a run that fills nothing
                                    # can be told apart from a dead session.
                                    "reasons": {"filled": 2, "not_found": 1}}, diag_rows
    enroll._REFRESH_PROGRESS.clear()
    print("  ok profile refresh worker fills every gap via live session (skips unreadable), "
          "stamps field_meta, publishes progress + diagnostics")


def test_profile_refresh_on_demand_start_and_status() -> None:
    """POST /auth/profile-refresh semantics (enroll.start_profile_refresh): a dead stored session →
    needs_reauth (the honest answer that routes the client to the re-auth dialog); a live one →
    started (worker spawned). GET status (profile_refresh_status) reports per-field missing counts
    from the members table + the live worker progress."""
    import types as _types
    from backend.auth_broker import enroll
    from backend import credentials as _creds

    members_rows = [
        {"person_uuid": "U1", "patriarchal_blessing": None, "calling": None,
         "baptism_date": "2024-01-01"},
        {"person_uuid": "U2", "patriarchal_blessing": None, "calling": "Yes",
         "baptism_date": "2024-01-01"},
    ]

    class _Resp:
        def __init__(self, payload, status=200):
            self._p, self.status_code, self.headers = payload, status, {}

        def json(self):
            return self._p

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/members"):
            return _Resp(members_rows)
        if url.endswith("/stake_credentials"):
            return _Resp([{"credential_enc": "blob", "revoked": False}])
        if url.endswith("/sync_diagnostics"):
            return _Resp([{"run_at": "2026-07-06T00:00:00+00:00",
                           "payload": {"filled": 5, "total": 6}}])
        return _Resp([])

    spawned: list = []
    saved = (enroll.requests.get, enroll._client_from_cookies, enroll._refresh_profile_async,
             _creds._decrypt_envelope, enroll.SUPABASE_URL, enroll.SERVICE_KEY)
    try:
        enroll.SUPABASE_URL = enroll.SUPABASE_URL or "https://test.supabase.co"
        enroll.SERVICE_KEY = enroll.SERVICE_KEY or "test-key"
        enroll.requests.get = fake_get
        enroll._REFRESH_PROGRESS.clear()
        _creds._decrypt_envelope = lambda blob: b'{"cookies": [{"name": "x"}]}'
        enroll._refresh_profile_async = (
            lambda cookies, unit, source="reauth": spawned.append((unit, source)))

        # DEAD stored session (get_text raises) → needs_reauth, nothing spawned.
        def _dead(cookies):
            def _raise(url, params=None):
                raise RuntimeError("redirected to login")
            return _types.SimpleNamespace(session=_types.SimpleNamespace(get_text=_raise))
        enroll._client_from_cookies = _dead
        out = enroll.start_profile_refresh(503991, "stake-1")
        assert out["status"] == "needs_reauth" and out["reason"] == "session_expired", out
        assert out["members_with_gaps"] == 2 and not spawned, out

        # DEAD session that still answers 200 from the LCR host with a SIGN-IN page. `get_text` only
        # raises on 4xx/5xx or an identity-host redirect, so this slipped through the probe and let
        # the worker grind through every member and fill nothing — the 2026-08-26 "0/8 members
        # updated with no login prompt" bug. FAILS pre-fix (this returned "started").
        def _dead_but_200(cookies):
            page = "<html><body>Please sign in to continue" + "x" * 800 + "</body></html>"
            return _types.SimpleNamespace(session=_types.SimpleNamespace(
                get_text=lambda url, params=None: page))
        enroll._client_from_cookies = _dead_but_200
        out = enroll.start_profile_refresh(503991, "stake-1")
        assert out["status"] == "needs_reauth" and out["reason"] == "session_expired", out
        assert not spawned, out

        # LIVE stored session → started + worker spawned as on_demand.
        def _alive(cookies):
            page = "<!doctype html><html><body id='member-profile'>" + "x" * 800 + "</body></html>"
            return _types.SimpleNamespace(session=_types.SimpleNamespace(
                get_text=lambda url, params=None: page))
        enroll._client_from_cookies = _alive
        out = enroll.start_profile_refresh(503991, "stake-1")
        assert out["status"] == "started" and spawned == [(503991, "on_demand")], out

        # Already running → reported as running, not restarted.
        enroll._REFRESH_PROGRESS[503991] = {"state": "running", "total": 2, "done": 1}
        out = enroll.start_profile_refresh(503991, "stake-1")
        assert out["status"] == "running" and len(spawned) == 1, out

        # Status: per-field missing counts + the live progress + last recorded refresh.
        st = enroll.profile_refresh_status(503991, "stake-1")
        assert st["running"] is True and st["members_with_gaps"] == 2, st
        assert st["missing"] == {"patriarchal_blessing": 2, "calling": 1,
                                 "temple_recommend": 2, "ministering_assignment": 2,
                                 "ministering_brothers_sisters": 2, "aaronic_priesthood": 2,
                                 "melchizedek_priesthood": 2, "living_ordinance": 2}, st
        assert st["last_refresh"]["payload"] == {"filled": 5, "total": 6}, st
    finally:
        (enroll.requests.get, enroll._client_from_cookies, enroll._refresh_profile_async,
         _creds._decrypt_envelope, enroll.SUPABASE_URL, enroll.SERVICE_KEY) = saved
        enroll._REFRESH_PROGRESS.clear()
    print("  ok on-demand profile refresh: dead session -> needs_reauth; live -> started; "
          "status reports missing counts + progress")


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
        # /api/report/one-work/details/{id} is DEPRECATED (replaced by the Member Tools bulk /api/v5/sync),
        # so a high error rate on it is EXPECTED probe noise — verdict 'expected', never a "hot" alarm
        # (D47, 2026-06-18: the verdict respects classification + keys off the SYNC error rate, not raw
        # error_pct). The error-%-only 'hot' assertion here went stale when that shipped; the new
        # behavior is covered in full by tests/test_endpoint_health.py.
        check("endpoint-health: details classified deprecated", det.get("class") == "deprecated")
        check("endpoint-health: deprecated verdict is 'expected', not 'hot'", det.get("verdict") == "expected")
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


# ---------- 2026-06-11 MFA hardening (the Ricky Bloomfield failure class) ----------
# A high counselor dead-ended at MFA: webauthn was offered (we can never finish it), the wrong-code
# 401 carried its message at the FIELD level (we only read top-level), and the user saw raw IDX
# JSON. Every test here FAILED against the pre-fix code.

def _shape_a_payload(*auths: tuple[str, str, list]) -> dict:
    """A minimal post-password IDX state offering the given (id, key, extra form fields) factors."""
    options = []
    for fid, _key, extra in auths:
        form = [{"name": "id", "value": fid}] + extra
        options.append({"label": fid, "value": {"form": {"value": form}}})
    return {
        "stateHandle": "sh0",
        "authenticators": {"value": [{"id": fid, "key": key} for fid, key, _ in auths]},
        "remediation": {"value": [
            {"name": "select-authenticator-authenticate", "href": "https://x/idx/select",
             "value": [{"name": "authenticator", "options": options}]}]},
    }


def test_mfa_factor_filtering_webauthn() -> None:
    # start_login must not OFFER a factor the flow can't finish — webauthn on the menu is a
    # guaranteed dead-end (it's what stranded the 2026-06-11 member for 28 seconds).
    old_drive = okta_flow._drive_to_password
    payload = _shape_a_payload(
        ("wk1", "webauthn", [{"name": "methodType", "value": "webauthn"}]),
        ("ph1", "phone_number", [{"name": "enrollmentId", "value": "e1"},
                                 {"name": "methodType", "value": "sms"}]))
    okta_flow._drive_to_password = lambda s, u, p, lid: (payload, "ver")
    try:
        res = okta_flow.start_login("rickyb", "pw", want_refresh_token=False)
        check("filter: still mfa_required", res.get("status") == "mfa_required")
        check("filter: webauthn dropped from the menu",
              [f["id"] for f in res["factors"]] == ["ph1"])
        check("filter: dropped types reported for the audit row",
              res.get("dropped_factor_types") == ["webauthn"])
        okta_flow._PENDING.pop(res.get("login_id"), None)
    finally:
        okta_flow._drive_to_password = old_drive


def test_mfa_all_factors_unsupported_friendly() -> None:
    # An account with ONLY unsupported factors gets an actionable message, not a code screen.
    old_drive = okta_flow._drive_to_password
    payload = _shape_a_payload(
        ("wk1", "webauthn", [{"name": "methodType", "value": "webauthn"}]))
    okta_flow._drive_to_password = lambda s, u, p, lid: (payload, "ver")
    try:
        okta_flow.start_login("rickyb", "pw", want_refresh_token=False)
        check("all-unsupported -> AuthError", False)
    except okta_flow.AuthError as e:
        check("all-unsupported -> AuthError", True)
        check("all-unsupported kind", getattr(e, "kind", "") == "mfa_unsupported")
        check("all-unsupported names the fix (add a method at churchofjesuschrist.org)",
              "churchofjesuschrist.org" in str(e))
        check("all-unsupported carries the username for audit",
              getattr(e, "username", "") == "rickyb")
    finally:
        okta_flow._drive_to_password = old_drive


def test_okta_verify_nested_method_prefers_totp() -> None:
    # Okta Verify lists methodType options (push first). Picking push starts a challenge with no
    # code to type; the resolver must prefer totp. (Pre-fix: first option won.)
    opt = {"label": "Okta Verify", "value": {"form": {"value": [
        {"name": "id", "value": "ov1"},
        {"name": "methodType", "options": [
            {"label": "Get a push notification", "value": "push"},
            {"label": "Enter a code", "value": "totp"}]},
    ]}}}
    obj = okta_flow._authenticator_object(opt)
    check("okta_verify resolves methodType=totp over push", obj.get("methodType") == "totp")
    # Phone keeps its sms preference (regression guard for the Jun-9 fix).
    check("phone still resolves sms first", okta_flow._authenticator_object(
        {"label": "Phone", "value": {"form": {"value": [
            {"name": "id", "value": "ph1"},
            {"name": "methodType", "options": [{"label": "Voice", "value": "voice"},
                                               {"label": "SMS", "value": "sms"}]}]}}}
    ).get("methodType") == "sms")


def _webauthn_challenge_rem() -> dict:
    return {"name": "challenge-authenticator", "href": "https://x/idx/challenge",
            "value": [{"name": "credentials", "form": {"value": [
                {"name": "authenticatorData"}, {"name": "clientData"},
                {"name": "signatureData"}]}}]}


def test_select_factor_refuses_non_code_challenge() -> None:
    # Defense in depth behind the menu filter: if a select lands on a challenge with no typed-code
    # field, refuse NOW (pre-fix: returned code_sent and stranded the member on a code screen).
    lid = "test-non-code"
    okta_flow._PENDING[lid] = {
        "session": None, "verifier": "", "username": "rickyb",
        "factors": [{"id": "wk1", "label": "Security Key", "method": "webauthn",
                     "type": "webauthn", "_auth": {"id": "wk1"}}],
        "payload": {"stateHandle": "sh", "remediation": {"value": [
            {"name": "select-authenticator-authenticate", "href": "https://x/idx/select",
             "value": []}]}},
        "ts": time.time(),
    }
    saved = okta_flow._follow
    okta_flow._follow = lambda *_a, **_k: {
        "stateHandle": "sh2", "remediation": {"value": [_webauthn_challenge_rem()]}}
    try:
        okta_flow.select_factor(lid, "wk1")
        check("non-code challenge -> AuthError", False)
    except okta_flow.AuthError as e:
        check("non-code challenge -> AuthError", True)
        check("non-code challenge kind mfa_unsupported", getattr(e, "kind", "") == "mfa_unsupported")
        check("non-code challenge message is friendly (no raw JSON)", "{" not in str(e))
    finally:
        okta_flow._follow = saved
        okta_flow._PENDING.pop(lid, None)


def _code_challenge_rem(field: str = "passcode") -> dict:
    return {"name": "challenge-authenticator", "href": "https://x/idx/challenge",
            "value": [{"name": "credentials", "form": {"value": [{"name": field}]}}]}


def _pending_at_challenge(lid: str, field: str = "passcode", ftype: str = "phone_number") -> None:
    okta_flow._PENDING[lid] = {
        "session": None, "verifier": "", "username": "rickyb", "selected_type": ftype,
        "payload": {"stateHandle": "sh-OLD",
                    "remediation": {"value": [_code_challenge_rem(field)]}},
        "ts": time.time(),
    }


def test_verify_answers_with_declared_field() -> None:
    # The answer body must use the field THIS challenge declares — Okta Verify's TOTP form says
    # `totp`, and the pre-fix hardcoded `passcode` 401s instantly (the 2026-06-11 failure class).
    lid = "test-totp-field"
    _pending_at_challenge(lid, field="totp", ftype="okta_verify")
    captured: dict = {}

    def fake_follow(_s, _rem, body, **_k):
        captured.update(body)
        return {"stateHandle": "sh2", "remediation": {"value": []}}  # non-success, no messages

    saved = okta_flow._follow
    okta_flow._follow = fake_follow
    try:
        okta_flow.verify_mfa(lid, "123456")
        check("totp verify reaches the classifier", False)
    except okta_flow.AuthError:
        check("totp verify reaches the classifier", True)
    check("verify answers with credentials.totp (not passcode)",
          captured.get("credentials") == {"totp": "123456"})
    okta_flow._PENDING.pop(lid, None)
    okta_flow._follow = saved


def test_verify_normalizes_code() -> None:
    # People paste "123 456" / "123-456"; Okta wants bare digits.
    lid = "test-normalize"
    _pending_at_challenge(lid)
    captured: dict = {}

    def fake_follow(_s, _rem, body, **_k):
        captured.update(body)
        return {"stateHandle": "sh2", "remediation": {"value": []}}

    saved = okta_flow._follow
    okta_flow._follow = fake_follow
    try:
        okta_flow.verify_mfa(lid, " 123 4-56 ")
    except okta_flow.AuthError:
        pass
    check("verify strips spaces/hyphens from the code",
          captured.get("credentials") == {"passcode": "123456"})
    okta_flow._PENDING.pop(lid, None)
    okta_flow._follow = saved


def test_verify_wrong_code_friendly_and_state_refresh() -> None:
    # The exact 2026-06-11 shape: Okta answers 401, the "Invalid code" message nested at the FIELD
    # level, no top-level messages. Pre-fix: the user saw raw JSON AND a retry reused the stale
    # stateHandle. Now: friendly mfa_bad_code, pending state refreshed from the failure payload.
    from lcr_client.okta_login import LoginError
    lid = "test-wrong-code"
    _pending_at_challenge(lid)
    err_payload = {
        "stateHandle": "sh-NEW",
        "remediation": {"value": [{
            "name": "challenge-authenticator", "href": "https://x/idx/challenge",
            "value": [{"name": "credentials", "form": {"value": [{
                "name": "passcode",
                "messages": {"value": [{"message": "Invalid code. Try again.",
                                        "class": "ERROR"}]}}]}}]}]},
    }

    def fake_follow(_s, _rem, _body, **_k):
        raise LoginError("IDX step answer failed: HTTP 401", payload=err_payload)

    saved = okta_flow._follow
    okta_flow._follow = fake_follow
    try:
        okta_flow.verify_mfa(lid, "999999")
        check("wrong code -> AuthError", False)
    except okta_flow.AuthError as e:
        check("wrong code -> AuthError", True)
        check("wrong code classified mfa_bad_code (field-level message read)",
              getattr(e, "kind", "") == "mfa_bad_code")
        check("wrong code message is friendly (no raw JSON)", "{" not in str(e))
        check("wrong code keeps attribution", getattr(e, "username", "") == "rickyb"
              and getattr(e, "factor_type", "") == "phone_number")
    check("pending state refreshed from the 401 payload (retry-safe)",
          okta_flow._PENDING[lid]["payload"].get("stateHandle") == "sh-NEW")
    okta_flow._PENDING.pop(lid, None)
    okta_flow._follow = saved


def test_captured_session_verify() -> None:
    # 2026-06-13: the WebView Church-login lane — the leader signs in on churchofjesuschrist.org
    # inside the app's WebView and the app posts the captured session COOKIES (no password ever
    # reaching us). verify_captured_session must: (a) reject a jar with no usable Church cookies
    # honestly; (b) keep only Church-domain cookies; (c) re-raise an LCR IdentityError so the API
    # maps it to 503; (d) wrap a transient LCR failure as IdentityError; (e) return the success
    # shape when identity resolves.
    from lcr_client.okta_login import LoginError

    # (a) empty / non-Church jars fail with the actionable message, never an empty-jar "stranger".
    for jar in ([], [{"name": "x", "value": "1", "domain": "example.com"}],
                [{"name": "appSession.0", "value": "", "domain": "lcr.churchofjesuschrist.org"}]):
        try:
            okta_flow.verify_captured_session(jar)
            check("no usable Church cookies -> AuthError", False)
        except okta_flow.IdentityError:
            check("no usable Church cookies -> AuthError (not IdentityError)", False)
        except okta_flow.AuthError as e:
            check("no usable Church cookies -> AuthError", True)
            check("captured_no_cookies kind", getattr(e, "kind", "") == "captured_no_cookies")

    church = [
        {"name": "sid", "value": "okta-sid", "domain": "id.churchofjesuschrist.org"},
        {"name": "appSession.0", "value": "a", "domain": "lcr.churchofjesuschrist.org"},
        {"name": "appSession.1", "value": "b", "domain": "lcr.churchofjesuschrist.org"},
        {"name": "junk", "value": "drop-me", "domain": "tracker.example.com"},
    ]
    saved = okta_flow._identity
    captured_session = {}

    # (e) success: identity resolves -> success shape; the non-Church cookie was filtered out.
    def fake_identity(session, _lid):
        captured_session["jar"] = sorted(c.name for c in session.cookies)
        return {"email": "leader@example.com", "name": "Leader", "username": "leader.example"}

    okta_flow._identity = fake_identity
    try:
        res = okta_flow.verify_captured_session(church)
        check("captured session verifies to success", res.get("status") == "success")
        check("identity carried through", (res.get("identity") or {}).get("email") == "leader@example.com")
        check("non-Church cookie filtered before building the session",
              "junk" not in captured_session.get("jar", []))
        check("Church session cookies kept", "appSession.0" in captured_session.get("jar", []))
    finally:
        okta_flow._identity = saved

    # (c) an IdentityError from the identity leg propagates unchanged (API -> 503).
    def raise_identity(_s, _l):
        raise okta_flow.IdentityError("LCR down", kind="lcr_5xx", root_cause="auth/me 502")
    okta_flow._identity = raise_identity
    try:
        okta_flow.verify_captured_session(church)
        check("IdentityError propagates", False)
    except okta_flow.IdentityError as e:
        check("IdentityError propagates", True)
        check("IdentityError keeps kind", getattr(e, "kind", "") == "lcr_5xx")
    except okta_flow.AuthError:
        check("IdentityError propagates (not downgraded to AuthError)", False)
    finally:
        okta_flow._identity = saved

    # (d) a transient LCR LoginError is wrapped as IdentityError (503), not a 401 "bad sign-in".
    def raise_5xx(_s, _l):
        raise LoginError("/api/auth/me failed: 502 text/plain")
    okta_flow._identity = raise_5xx
    try:
        okta_flow.verify_captured_session(church)
        check("transient LCR failure -> IdentityError", False)
    except okta_flow.IdentityError as e:
        check("transient LCR failure -> IdentityError", True)
        check("wrapped failure records the root cause", "auth/me" in getattr(e, "root_cause", ""))
    except okta_flow.AuthError:
        check("transient LCR failure -> IdentityError (not 401 AuthError)", False)
    finally:
        okta_flow._identity = saved



def test_verify_no_message_still_friendly() -> None:
    # A 4xx with NO message anywhere must still produce a friendly retry message — the raw-JSON
    # wall is what made a recoverable wrong code look fatal.
    from lcr_client.okta_login import LoginError
    lid = "test-no-msg"
    _pending_at_challenge(lid)
    saved = okta_flow._follow

    def fake_follow(_s, _rem, _body, **_k):
        raise LoginError("IDX step answer failed: HTTP 400",
                         payload={"stateHandle": "sh-NEW", "remediation": {"value": []}})

    okta_flow._follow = fake_follow
    try:
        okta_flow.verify_mfa(lid, "111111")
        check("no-message 4xx -> AuthError", False)
    except okta_flow.AuthError as e:
        check("no-message 4xx -> AuthError", True)
        check("no-message 4xx friendly (no raw JSON, no 'IDX')",
              "{" not in str(e) and "IDX" not in str(e))
        check("no-message 4xx keeps the raw root_cause for audit",
              "IDX step answer failed" in getattr(e, "root_cause", ""))
    okta_flow._PENDING.pop(lid, None)
    okta_flow._follow = saved


def test_mfa_bad_code_factor_guidance() -> None:
    # A rejected code names the right SOURCE per factor — the 2026-06-11 trap was a right-looking
    # code from the wrong source (authenticator-app code typed into a text challenge).
    e = okta_flow._classify_mfa_failure("x", "Invalid code. Try again.",
                                        username="u", factor_type="phone_number")
    check("phone bad-code hint names the newest text", "newest text" in str(e))
    check("phone bad-code hint warns off authenticator apps", "authenticator app" in str(e))
    e = okta_flow._classify_mfa_failure("x", "Invalid code.", username="u",
                                        factor_type="google_otp")
    check("google_otp hint points at the app's current code",
          "currently showing in your authenticator app" in str(e))
    e = okta_flow._classify_mfa_failure("x", "Invalid code.", username="u",
                                        factor_type="okta_email")
    check("email hint points at the newest email", "newest email" in str(e))
    e = okta_flow._classify_mfa_failure("x", "Invalid code.", username="u", factor_type="")
    check("unknown factor keeps the generic retry hint", "Request a new code" in str(e))


def test_mfa_expired_messages_friendly() -> None:
    # Unknown/pruned login_id: both steps answer with a start-over message, sentence-cased.
    for fn, args in ((okta_flow.verify_mfa, ("gone", "000000")),
                     (okta_flow.select_factor, ("gone", "f"))):
        try:
            fn(*args)
            check(f"{fn.__name__} expired -> AuthError", False)
        except okta_flow.AuthError as e:
            check(f"{fn.__name__} expired -> AuthError",
                  getattr(e, "kind", "") == "mfa_expired" and "start over" in str(e))


def test_nested_idx_messages_and_mask() -> None:
    from lcr_client.okta_login import _idx_messages, _mask_payload
    payload = {
        "stateHandle": "02.id.SECRET",
        "messages": {"value": [{"message": "Top-level note."}]},
        "remediation": {"value": [{"value": [{"name": "credentials", "form": {"value": [
            {"name": "passcode",
             "messages": {"value": [{"message": "Invalid code. Try again."}]}}]}}]}]},
    }
    check("idx_messages collects nested field-level messages",
          _idx_messages(payload) == "Top-level note.; Invalid code. Try again.")
    check("idx_messages returns empty (not raw JSON) when none",
          _idx_messages({"stateHandle": "x", "remediation": {"value": []}}) == "")
    masked = _mask_payload(payload)
    check("mask hides stateHandle", masked["stateHandle"] == "**masked**"
          and "SECRET" not in repr(masked))
    check("mask preserves the rest", "Invalid code" in repr(masked))


def test_mfa_pending_and_select_failures_audited() -> None:
    # Endpoint-level: an mfa_required hand-off writes an mfa_pending row (factor menu included),
    # and a failed select writes mfa_select_failed with username + factor type. Pre-fix: neither
    # left ANY server-side trace (the 2026-06-11 dig needed Render stdout).
    rows: list[tuple] = []
    old_audit, old_start, old_select = appmod._audit_okta_event, okta_flow.start_login, okta_flow.select_factor
    old_pool = appmod._FAST_POOL

    class _SyncPool:
        def submit(self, fn, *a, **k):
            fn(*a, **k)

    appmod._audit_okta_event = lambda who, stage, error, rid, duration_ms=None, phase=None: \
        rows.append((who, stage, error, phase))
    appmod._FAST_POOL = _SyncPool()
    okta_flow.start_login = lambda *a, **k: {
        "status": "mfa_required", "login_id": "L1",
        "factors": [{"id": "ph1", "label": "Phone", "method": "sms"}],
        "factor_types": ["phone_number"], "dropped_factor_types": ["webauthn"]}
    try:
        r = client.post("/auth/password", json={"username": "rickyb", "password": "pw"})
        check("mfa_required response unchanged for clients",
              r.status_code == 200 and r.json().get("status") == "mfa_required")
        pend_rows = [x for x in rows if x[1] == "mfa_pending"]
        check("mfa_pending audited with username", pend_rows and pend_rows[0][0] == "rickyb")
        check("mfa_pending names offered + dropped factors",
              pend_rows and "phone_number" in pend_rows[0][2] and "webauthn" in pend_rows[0][2])

        def _boom(_lid, _fid):
            raise okta_flow.AuthError("That verification method isn't supported in this app yet "
                                      "— please choose a different one.", kind="mfa_unsupported",
                                      username="rickyb", factor_type="webauthn")
        okta_flow.select_factor = _boom
        r = client.post("/auth/mfa/select", json={"login_id": "L1", "factor_id": "wk1"})
        check("select failure -> 400 with friendly detail",
              r.status_code == 400 and "isn't supported" in r.json().get("detail", ""))
        sel_rows = [x for x in rows if x[1] == "mfa_select_failed"]
        check("select failure audited with username + factor type",
              sel_rows and sel_rows[0][0] == "rickyb"
              and sel_rows[0][3] == "okta:mfa_unsupported:webauthn")
    finally:
        appmod._audit_okta_event = old_audit
        appmod._FAST_POOL = old_pool
        okta_flow.start_login = old_start
        okta_flow.select_factor = old_select


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


def test_admin_reauth_email() -> None:
    # B3: POST /admin/stakes/{id}/reauth-email looks up the provider email + stake name and sends the
    # re-auth nudge with the /reauth deep link. require_admin gates it; a missing credential / missing
    # provider email -> 404; the LCR-sourced stake name is HTML-escaped in the body.
    app.dependency_overrides[require_admin] = lambda: "admin@test"
    sent: dict = {}
    one_rows: dict = {
        "stake_credentials": {"principal_email": "provider@test", "principal_name": "P", "revoked": False},
        "stakes": {"name": "<b>Raleigh</b>", "unit_number": 503991},
    }
    saved = (admin._one, admin._send_email)
    admin._one = lambda table, params: one_rows.get(table)
    admin._send_email = lambda to, subject, html: sent.update(to=to, subject=subject, html=html)
    try:
        r = client.post("/admin/stakes/s1/reauth-email")
        check("reauth-email -> 200", r.status_code == 200)
        check("reauth-email returns the recipient", r.json().get("to") == "provider@test")
        check("reauth-email sent to the provider", sent.get("to") == "provider@test")
        check("reauth-email body carries the /reauth deep link", "/reauth" in sent.get("html", ""))
        check("reauth-email escapes the stake name (BACKEND-02)",
              "<b>Raleigh</b>" not in sent.get("html", "") and "&lt;b&gt;" in sent.get("html", ""))

        # No credential on file -> 404, nothing sent.
        sent.clear()
        one_rows["stake_credentials"] = None
        r = client.post("/admin/stakes/s1/reauth-email")
        check("reauth-email no credential -> 404", r.status_code == 404)
        check("reauth-email no credential sends nothing", "to" not in sent)

        # Credential but no provider email -> 404.
        one_rows["stake_credentials"] = {"principal_email": "", "revoked": False}
        r = client.post("/admin/stakes/s1/reauth-email")
        check("reauth-email no provider email -> 404", r.status_code == 404)
    finally:
        admin._one, admin._send_email = saved
        app.dependency_overrides.clear()


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
                                   unit_number=1102966, unit_name="Green Level Ward"), c, None)
        out = enroll.calling_gate_check(cookies, {"email": "m@e.org"}, request_id="r")
        check("sync gate blocks no-calling", out is not None and out.get("authorized") is False)
        check("sync gate caches has_calling False", cached.get("has_calling") is False)
        check("sync gate audit phase gate-sync", audited.get("phase") == "gate-sync")

        cached.clear()
        enroll._user_context_with_establish = lambda c: (
            _types.SimpleNamespace(active_position="Bishop", positions=[{"name": "Bishop"}],
                                   child_units=[], unit_number=503991, unit_name="Test Stake"), c, None)
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
    old_audit = appmod._audit_okta_event
    audited: dict = {}
    okta_flow._drive_to_password = (
        lambda s, u, p, lid: ({"successWithInteractionCode": {"value": []}}, "ver"))
    okta_flow.identity_cache.get = lambda u: None
    okta_flow._identity = (lambda s, lid: (_ for _ in ()).throw(
        LoginError("verification /api/auth/me failed: 502 text/plain")))
    appmod._audit_okta_event = (
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
        appmod._audit_okta_event = old_audit
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


def _full_eval_env(ctx, *, on_access=None, on_rpc=None):
    """Patch enroll for a FULL-EVAL test (past the gate, through the access scrape, to the enroll
    RPC) with no network. Returns restore_fn. The scrape + RPC seams are observable via the
    on_access/on_rpc callbacks."""
    import types as _types
    from lcr_client import access as access_mod
    from backend import credentials as cred_mod
    from backend.auth_broker import identity_cache

    class _Resp:
        status_code = 200
        text = "ok"

        def json(self):
            return []

    def fake_post(url, **kw):
        if on_rpc:
            on_rpc(url, kw.get("json") or {})
        return _Resp()

    def fake_access(client):
        if on_access:
            on_access(client)
        return {"can_pull_all": True, "features": [], "missing": [],
                "runner_positions": [{"name": "Stake President", "id": 17}]}

    old = (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
           enroll._client_from_cookies, enroll._audit_login, enroll._bind_identity_email,
           enroll._kickoff_initial_sync, enroll._notify_enrolled, enroll.requests.post,
           identity_cache.set_unit, access_mod.covenant_path_access, cred_mod._encrypt_envelope,
           enroll._is_known_subunit)
    enroll.SUPABASE_URL, enroll.SERVICE_KEY = "https://example.invalid", "key"
    enroll._stored_credential_summary = lambda unit: None  # no usable credential → full path
    enroll._client_from_cookies = lambda cookies: _types.SimpleNamespace(user_context=lambda: ctx)
    enroll._audit_login = lambda *a, **k: None
    enroll._bind_identity_email = lambda identity: None
    enroll._kickoff_initial_sync = lambda unit: False
    enroll._notify_enrolled = lambda *a, **k: None
    enroll.requests.post = fake_post
    identity_cache.set_unit = lambda *a, **k: None
    access_mod.covenant_path_access = fake_access
    cred_mod._encrypt_envelope = lambda raw: "enc-blob"
    # Default: the unit isn't a known ward (no DB round trip in the fast path). Ward-gate tests
    # override this to simulate an already-synced stake's sub-unit.
    enroll._is_known_subunit = lambda unit: False

    def _restore():
        (enroll.SUPABASE_URL, enroll.SERVICE_KEY, enroll._stored_credential_summary,
         enroll._client_from_cookies, enroll._audit_login, enroll._bind_identity_email,
         enroll._kickoff_initial_sync, enroll._notify_enrolled, enroll.requests.post,
         identity_cache.set_unit, access_mod.covenant_path_access,
         cred_mod._encrypt_envelope, enroll._is_known_subunit) = old

    return _restore


def test_full_eval_enroll_reaches_scrape_and_stores() -> None:
    """REGRESSION (2026-06-10): extracting _user_context_with_establish dropped the `client` the
    access scrape still referenced — evaluate_and_maybe_store(store=True) died with
    NameError("name 'client' is not defined") on EVERY consented enroll/re-enroll (the "sign-in
    worked, but the daily sync could not be set up" report). Drive the eval past the gate, through
    the scrape, to the enroll RPC."""
    import types as _types
    ctx = _types.SimpleNamespace(active_position="Stake President",
                                 positions=[{"name": "Stake President", "id": 1}],
                                 child_units=[], unit_number=503991, unit_name="Test Stake")
    seen: dict = {}
    restore = _full_eval_env(
        ctx,
        on_access=lambda client: seen.update(client=client),
        on_rpc=lambda url, body: seen.update(url=url, body=body))
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "president@example.org", "name": "Pres"}, True, request_id="rid-enroll")
        check("enroll: authorized", out.get("authorized") is True)
        check("enroll: stored", out.get("stored") is True)
        check("enroll: scrape got a real client (the NameError seam)",
              seen.get("client") is not None)
        check("enroll: RPC called", "enroll_stake_credential" in str(seen.get("url")))
        check("enroll: RPC carries the unit", seen.get("body", {}).get("p_unit_number") == 503991)
        check("enroll: RPC granting role ids from scrape",
              seen.get("body", {}).get("p_granting_role_ids") == [17])
    finally:
        restore()


def test_full_eval_new_stake_offers_enroll() -> None:
    """Same regression, store=False flavor: a leader whose stake has NO usable credential must get
    authorized + can_enroll (the post-login "set up daily sync" offer). The NameError silently
    killed the offer — new stakes could never onboard."""
    import types as _types
    ctx = _types.SimpleNamespace(active_position="Stake President",
                                 positions=[{"name": "Stake President", "id": 1}],
                                 child_units=[], unit_number=503991, unit_name="Test Stake")
    rpc_calls: list = []
    restore = _full_eval_env(ctx, on_rpc=lambda url, body: rpc_calls.append(url))
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "president@example.org"}, False, request_id="rid-offer")
        check("offer: authorized", out.get("authorized") is True)
        check("offer: can_enroll", out.get("can_enroll") is True)
        check("offer: nothing stored", out.get("stored") is False)
        check("offer: no RPC without consent", rpc_calls == [])
    finally:
        restore()


def test_ward_leader_enroll_refused_friendly() -> None:
    """The Bond Park bishop (2026-07-20): a WARD leader who consents to enroll must get the FRIENDLY
    ward-scoped refusal, NOT the raw "enroll RPC failed (400)" from the DB sub-unit guard. A bishop
    is the hard case — his calling grants FULL ward data (can_pull_all=True) AND his user-context
    lists child ORGANIZATIONS — so the structural checks alone let him through; only the authoritative
    `units` lookup catches him. The RPC must never be called; store must be False."""
    import types as _types
    # Bishop of Bond Park (2140497): can_pull_all True, children are the ward's ORGS (not wards).
    orgs = [_types.SimpleNamespace(type="ELDERS_QUORUM", unit_number=1, name="EQ"),
            _types.SimpleNamespace(type="RELIEF_SOCIETY", unit_number=2, name="RS")]
    ctx = _types.SimpleNamespace(active_position="Bishop",
                                 positions=[{"name": "Bishop", "id": 4}],
                                 child_units=orgs, unit_number=2140497, unit_name="Bond Park Ward")
    rpc_calls: list = []
    restore = _full_eval_env(ctx, on_rpc=lambda url, body: rpc_calls.append(url))
    enroll._is_known_subunit = lambda unit: unit == 2140497  # already a synced ward
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "bishop@example.org", "name": "Bishop"}, True, request_id="rid-ward")
        check("ward enroll: NOT stored", out.get("stored") is False)
        check("ward enroll: enroll_blocked=ward_scoped", out.get("enroll_blocked") == "ward_scoped")
        check("ward enroll: ward_scoped flag set", out.get("ward_scoped") is True)
        check("ward enroll: can_enroll is False (never offered)", out.get("can_enroll") is False)
        check("ward enroll: friendly reason (not a raw RPC error)",
              "set up" in str(out.get("enroll_block_reason", "")).lower()
              and "400" not in str(out.get("enroll_block_reason", "")))
        check("ward enroll: synced-stake message says 'view here'",
              "view here" in str(out.get("enroll_block_reason", "")).lower())
        check("ward enroll: RPC NEVER called (no DB guard 400)", rpc_calls == [])
    finally:
        restore()


def test_ward_leader_new_stake_points_to_stake_leader() -> None:
    """A bishop of a NOT-yet-synced stake (unknown to `units`) still must not enroll — his org-only
    child units mark him a ward context even with full ward access (can_pull_all=True), so he'd
    otherwise create a phantom stake. He's told to ask his stake leader (user directive 2026-07-20)."""
    import types as _types
    orgs = [_types.SimpleNamespace(type="ELDERS_QUORUM", unit_number=1, name="EQ"),
            _types.SimpleNamespace(type="PRIMARY", unit_number=2, name="Primary")]
    ctx = _types.SimpleNamespace(active_position="Bishop",
                                 positions=[{"name": "Bishop", "id": 4}],
                                 child_units=orgs, unit_number=778899, unit_name="New Ward")
    rpc_calls: list = []
    restore = _full_eval_env(ctx, on_rpc=lambda url, body: rpc_calls.append(url))
    enroll._is_known_subunit = lambda unit: False  # stake never synced → not in units
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "newbishop@example.org"}, True, request_id="rid-newward")
        check("new-stake ward: refused ward_scoped", out.get("enroll_blocked") == "ward_scoped")
        check("new-stake ward: RPC never called (no phantom stake)", rpc_calls == [])
        check("new-stake ward: message points to the stake leader",
              "stake" in str(out.get("enroll_block_reason", "")).lower()
              and "ask" in str(out.get("enroll_block_reason", "")).lower())
        check("new-stake ward: can_enroll False", out.get("can_enroll") is False)
    finally:
        restore()


def test_ward_leader_no_children_still_refused() -> None:
    """The original Green Level Ward shape still works: a ward leader of a NOT-yet-synced stake
    (not in `units`) with no child units and no full access is caught by the STRUCTURAL test."""
    import types as _types
    ctx = _types.SimpleNamespace(active_position="Ward Mission Leader",
                                 positions=[{"name": "Ward Mission Leader", "id": 9}],
                                 child_units=[], unit_number=999001, unit_name="New Ward")
    rpc_calls: list = []
    restore = _full_eval_env(ctx, on_rpc=lambda url, body: rpc_calls.append(url))
    enroll._is_known_subunit = lambda unit: False  # brand-new stake: not in units yet
    # A ward leader with PARTIAL data access (one granted feature → authorized, rank>0) but NOT
    # can_pull_all — so it passes the auth gate yet is still caught by the structural ward test.
    from lcr_client import access as access_mod
    access_mod.covenant_path_access = lambda client: {
        "can_pull_all": False, "features": [{"feature": "menu.member.list", "allowed": True}],
        "missing": [], "runner_positions": [{"name": "Ward Mission Leader", "id": 9}]}
    try:
        out = enroll.evaluate_and_maybe_store(
            [{"name": "sid", "value": "x", "domain": "d", "path": "/"}],
            {"email": "wml@example.org"}, True, request_id="rid-wml")
        check("wml enroll: refused ward_scoped", out.get("enroll_blocked") == "ward_scoped")
        check("wml enroll: RPC never called", rpc_calls == [])
    finally:
        restore()


def test_friendly_okta_errors() -> None:
    """Bad credentials must read like "wrong username/password", not the raw
    "IDX step answer failed: Authentication failed" — while login_audit keeps the raw cause."""
    from lcr_client.okta_login import LoginError
    e = okta_flow.friendly_auth_error(LoginError("IDX step answer failed: Authentication failed"))
    check("bad creds: friendly text", "incorrect" in str(e).lower() and "IDX" not in str(e))
    check("bad creds: kind", getattr(e, "kind", "") == "bad_credentials")
    check("bad creds: raw kept as root_cause", "Authentication failed" in e.root_cause)
    e2 = okta_flow.friendly_auth_error(LoginError("IDX step answer failed: Your account is locked."))
    check("locked: classified", getattr(e2, "kind", "") == "account_locked")
    check("locked: friendly names the unlock path", "churchofjesuschrist.org" in str(e2))
    # 2026-06-12 (Ken Packer): Okta's "Password requirements were not met" rejected his password and
    # read as a confusing dead-end (he fell back to the emailed-code lane that can't set up sync). It
    # must classify with an actionable reset path, not surface raw.
    e4 = okta_flow.friendly_auth_error(LoginError("IDX step answer failed: Password requirements were not met."))
    check("password_rejected: classified", getattr(e4, "kind", "") == "password_rejected")
    check("password_rejected: names the reset path", "churchofjesuschrist.org" in str(e4))
    check("password_rejected: not raw", "requirements were not met" not in str(e4))
    check("password_rejected: raw kept as root_cause", "requirements were not met" in e4.root_cause)
    e3 = okta_flow.friendly_auth_error(RuntimeError("weird transport thing"))
    check("unknown: keeps the raw text", "weird transport thing" in str(e3))
    check("unknown: kind other", getattr(e3, "kind", "") == "other")


def test_password_endpoint_friendly_bad_creds() -> None:
    """End-to-end through the API: a bad-credential login answers 401 with the FRIENDLY detail,
    and the audit row records the RAW cause + okta:<kind> phase."""
    from lcr_client.okta_login import LoginError
    audited: dict = {}
    old_start, old_audit = okta_flow.start_login, appmod._audit_okta_event

    def boom(username, password, **kw):
        raise okta_flow.friendly_auth_error(
            LoginError("IDX step answer failed: Authentication failed"))

    okta_flow.start_login = boom
    appmod._audit_okta_event = (
        lambda who, stage, error, rid, **kw: audited.update({"stage": stage, "error": error, **kw}))
    try:
        r = client.post("/auth/password", json={"username": "u", "password": "p"})
        check("bad creds → 401", r.status_code == 401)
        d = str(r.json().get("detail", ""))
        check("bad creds detail is friendly", "incorrect" in d.lower() and "IDX" not in d)
        check("audit keeps the raw cause", "Authentication failed" in audited.get("error", ""))
        check("audit phase carries the kind", audited.get("phase") == "okta:bad_credentials")
        check("audit duration recorded", isinstance(audited.get("duration_ms"), int))
    finally:
        okta_flow.start_login, appmod._audit_okta_event = old_start, old_audit


def test_sync_now_blocked_when_revoked() -> None:
    """A revoked credential cannot "Sync now": the endpoint answers 409 with a re-authorize hint
    instead of dispatching a run that would silently skip the stake (the settings sheet hides the
    button; this is the server gate behind it)."""
    old_verify, old_status = admin.verify_user, admin.enrollment_status
    admin.verify_user = lambda authorization: "prov@example.org"
    admin.enrollment_status = lambda email, auth_id: {
        "unit_number": 503991,
        "credential": {"state": "revoked", "is_provider": True, "complete": True}}
    try:
        r = client.post("/auth/sync-now", headers={"Authorization": "Bearer x"})
        check("sync-now on revoked → 409", r.status_code == 409)
        check("sync-now revoked points to re-auth",
              "re-authorize" in str(r.json().get("detail", "")).lower())
    finally:
        admin.verify_user, admin.enrollment_status = old_verify, old_status


def test_report_html_escapes_member_data() -> None:
    # BACKEND-02: LCR-sourced names/units must be HTML-escaped in the report email body.
    from backend.auth_broker import reports
    rep = {"stake_name": "S", "generated_at": "2026-06-11T00:00:00", "total": 1, "on_track": 0,
           "outstanding": [{"name": "<script>x</script>", "unit": "<b>U</b>", "missing": ["baptism"]}],
           "by_milestone": [("<i>m</i>", 1)]}
    html = reports._report_html(rep)
    check("report html: member name escaped", "<script>" not in html and "&lt;script&gt;" in html)
    check("report html: unit escaped", "<b>U</b>" not in html)


def test_safe_cred_id_rejects_filter_metachars() -> None:
    # BACKEND-03: the unauthenticated passkey credential id must be strict base64url before it
    # reaches a PostgREST eq. filter.
    from backend.auth_broker import webauthn_flow as wf
    good = "A" * 20 + "_-"
    check("cred_id: valid base64url accepted", wf._safe_cred_id(good) == good)
    for bad in ("a,b", "x*", "ab.cd", "short", "has space", ""):
        try:
            wf._safe_cred_id(bad)
            check(f"cred_id rejects {bad!r}", False)
        except wf.PasskeyError:
            check(f"cred_id rejects {bad!r}", True)


def test_user_routes_require_auth() -> None:
    # BACKEND-04: the broker bypasses RLS (service key), so each data route's own auth check is the
    # gate. A representative data route must reject an unauthenticated call (never serve data).
    # (A few routes call admin.verify_user directly and 500 on missing auth rather than 403 — tracked
    # as a follow-up to route them through require_user; they still never serve data unauthenticated.)
    check("report no auth -> 403 (not served)", client.get("/report").status_code == 403)


def test_partner_notes_lane() -> None:
    """Partner notes API (Mission-KPIs reads/writes OUR member_comments): token gate (unset=503,
    wrong=401, constant-time), thread list mapping, add with attribution + 32KB cap, PENDING add for a
    not-yet-synced person (NO 404 — the Ricky bug), stake-inherit from a prior comment, edit-in-place,
    idempotent scoped delete."""
    from backend.auth_broker import partner_notes

    uuid = "5c3fb668-f0a8-4452-8704-0a1374911aeb"
    saved_token = os.environ.pop("PARTNER_NOTES_TOKEN", None)
    saved_one = admin._one
    saved_headers = admin._sb_headers
    admin._sb_headers = lambda: {}  # offline: no SUPABASE env; REST calls are stubbed below
    saved_get = partner_notes.requests.get
    saved_post = partner_notes.requests.post
    saved_patch = partner_notes.requests.patch
    saved_delete = partner_notes.requests.delete

    # admin._one backs both _member (table 'members') and _scope_for's inherit query (table
    # 'member_comments'); this dict lets each test simulate a synced / absent / previously-noted person.
    one_returns = {"members": None, "member_comments": None}

    def fake_one(table, params=None, *a, **k):
        return one_returns.get(table)

    try:
        # Lane off until a token is issued.
        check("partner: unset token env -> 503",
              client.get(f"/partner/notes/{uuid}").status_code == 503)
        os.environ["PARTNER_NOTES_TOKEN"] = "sekrit"
        check("partner: wrong token -> 401",
              client.get(f"/partner/notes/{uuid}",
                         headers={"X-Partner-Token": "nope"}).status_code == 401)

        admin._one = fake_one

        # List: NO existence gate — a person with no members row can still have (pending) notes to read.
        rows = [{"id": "c1", "body": "**Hi**", "author_name": None,
                 "author_email": "leader@x.org", "created_at": "2026-07-01", "updated_at": None},
                {"id": "c2", "body": "More", "author_name": "Sister Lopez",
                 "author_email": "l@x.org", "created_at": "2026-07-02", "updated_at": None}]
        partner_notes.requests.get = lambda *a, **k: _FakeResp(rows)
        r = client.get(f"/partner/notes/{uuid}", headers={"X-Partner-Token": "sekrit"})
        body = r.json()
        check("partner: list 200 with mapped entries",
              r.status_code == 200 and [e["id"] for e in body["entries"]] == ["c1", "c2"])
        check("partner: author falls back name->email",
              body["entries"][0]["author"] == "leader@x.org"
              and body["entries"][1]["author"] == "Sister Lopez")

        posted = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            posted.clear()
            posted.update(json or {})
            return _FakeResp([{**(json or {}), "id": "new1", "created_at": "2026-07-19"}], 201)

        partner_notes.requests.post = fake_post

        # Add for a SYNCED person: scope taken from the member + attributed to the partner marker email.
        one_returns["members"] = {"person_uuid": uuid, "stake_id": "s1", "unit_id": "u1"}
        r = client.post(f"/partner/notes/{uuid}", headers={"X-Partner-Token": "sekrit"},
                        json={"body": "Visited **today**", "author": "Elder Kim"})
        check("partner: add 200 entry id", r.status_code == 200
              and r.json()["entry"]["id"] == "new1")
        check("partner: add attributed to partner email + author name + member scope",
              posted.get("author_email") == partner_notes.PARTNER_EMAIL
              and posted.get("author_name") == "Elder Kim"
              and posted.get("stake_id") == "s1")

        # Add for a NOT-YET-SYNCED person: no 404 — stored PENDING (null stake), adopted on next sync.
        one_returns["members"] = None
        one_returns["member_comments"] = None
        r = client.post(f"/partner/notes/{uuid}", headers={"X-Partner-Token": "sekrit"},
                        json={"body": "Met at English class"})
        check("partner: add for unsynced person -> 200 (no 404)", r.status_code == 200)
        check("partner: unsynced add is PENDING (null stake)", posted.get("stake_id") is None)

        # If the person once had a comment, a new note inherits that stake (member row transiently gone).
        one_returns["member_comments"] = {"stake_id": "s9", "unit_id": "u9"}
        client.post(f"/partner/notes/{uuid}", headers={"X-Partner-Token": "sekrit"},
                    json={"body": "Back again"})
        check("partner: add inherits stake from a prior comment when member absent",
              posted.get("stake_id") == "s9" and posted.get("unit_id") == "u9")

        check("partner: empty body -> 400",
              client.post(f"/partner/notes/{uuid}", headers={"X-Partner-Token": "sekrit"},
                          json={"body": "   "}).status_code == 400)
        check("partner: oversized body -> 413",
              client.post(f"/partner/notes/{uuid}", headers={"X-Partner-Token": "sekrit"},
                          json={"body": "x" * (32 * 1024 + 1)}).status_code == 413)

        # Update (edit in place): scoped to the person's uuid + stamps the partner editor.
        patched = {"params": {}, "json": {}}

        def fake_patch(url, headers=None, params=None, json=None, timeout=None):
            patched["params"] = params or {}
            patched["json"] = json or {}
            return _FakeResp([{"id": "c1", "body": (json or {}).get("body"),
                               "author_name": (json or {}).get("author_name"),
                               "created_at": "2026-07-01", "updated_at": "2026-07-20"}], 200)

        partner_notes.requests.patch = fake_patch
        r = client.post(f"/partner/notes/{uuid}/update", headers={"X-Partner-Token": "sekrit"},
                        json={"id": "c1", "body": "Edited body", "author": "Elder Kim"})
        check("partner: update 200 with edited body",
              r.status_code == 200 and r.json()["entry"]["body"] == "Edited body")
        check("partner: update scoped to person uuid + stamps editor",
              patched["params"].get("member_person_uuid") == f"eq.{uuid}"
              and patched["params"].get("id") == "eq.c1"
              and patched["json"].get("updated_by") == partner_notes.PARTNER_EMAIL)
        check("partner: update empty body -> 400",
              client.post(f"/partner/notes/{uuid}/update", headers={"X-Partner-Token": "sekrit"},
                          json={"id": "c1", "body": "  "}).status_code == 400)

        # Delete: scoped to the person's uuid (a leaked id can't reach another person's entries).
        deleted = {}

        def fake_delete(url, headers=None, params=None, timeout=None):
            deleted.update(params or {})
            return _FakeResp([], 204)

        partner_notes.requests.delete = fake_delete
        r = client.post(f"/partner/notes/{uuid}/delete", headers={"X-Partner-Token": "sekrit"},
                        json={"id": "c1"})
        check("partner: delete 200 idempotent", r.status_code == 200 and r.json()["deleted"])
        check("partner: delete scoped to person uuid",
              deleted.get("member_person_uuid") == f"eq.{uuid}" and deleted.get("id") == "eq.c1")
    finally:
        admin._one = saved_one
        admin._sb_headers = saved_headers
        partner_notes.requests.get = saved_get
        partner_notes.requests.post = saved_post
        partner_notes.requests.patch = saved_patch
        partner_notes.requests.delete = saved_delete
        if saved_token is None:
            os.environ.pop("PARTNER_NOTES_TOKEN", None)
        else:
            os.environ["PARTNER_NOTES_TOKEN"] = saved_token


def test_partner_data_lanes() -> None:
    """Partner DATA lanes (transfer dates / ward goals / manual people): shared token gate, stake
    resolved from PARTNER_STAKE_UNIT, his unit_number ↔ our unit_id mapping, upsert + delete."""
    from backend.auth_broker import partner_data

    saved_token = os.environ.pop("PARTNER_NOTES_TOKEN", None)
    saved_stake = os.environ.pop("PARTNER_STAKE_UNIT", None)
    saved_one, saved_headers = admin._one, admin._sb_headers
    saved_get, saved_post = partner_data.requests.get, partner_data.requests.post
    saved_patch, saved_delete = partner_data.requests.patch, partner_data.requests.delete
    admin._sb_headers = lambda: {}
    # stakes lookup goes through admin._one; everything else through the stubbed requests.* below.
    admin._one = lambda table, params=None, *a, **k: {"id": "stk1"} if table == "stakes" else None

    def fake_get(url, headers=None, params=None, timeout=None):
        if "/units" in url:
            return _FakeResp([{"id": "u10", "unit_number": 10, "name": "Alpha Ward"}])
        if "/transfer_dates" in url:
            return _FakeResp([{"transfer_id": "t-2026-07-23", "transfer_date": "2026-07-23"}])
        if "/ward_goals" in url:
            # unit_number null (as the WEB writes it) — the lane must resolve it from unit_id.
            return _FakeResp([{"unit_id": "u10", "unit_number": None, "unit_name": "Alpha Ward",
                               "transfer_id": "t-2026-07-23", "goal": 3, "updated_at": "t", "updated_by": "u"}])
        if "/manual_members" in url:
            return _FakeResp([{"id": "mm1", "name": "John S", "first_name": "John", "last_initial": "S",
                               "baptism_date": "2026-08-01", "unit_id": "u10", "unit_name": "Alpha Ward",
                               "custom_notes": "keep", "updated_at": "t"}])
        return _FakeResp([])

    posted: dict = {}

    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        posted.clear()
        posted["url"], posted["body"] = url, json or {}
        return _FakeResp([{**(json or {}), "id": "new1"}], 201)

    deleted: dict = {}

    def fake_delete(url, headers=None, params=None, timeout=None):
        deleted.clear()
        deleted.update(params or {})
        return _FakeResp([], 204)

    patched: dict = {}

    def fake_patch(url, headers=None, params=None, json=None, timeout=None):
        patched.clear()
        patched["params"] = params or {}
        patched["body"] = json or {}
        return _FakeResp([{"id": "mm1"}], 200)

    try:
        # Token gate is shared with the notes lane (unset ⇒ 503).
        check("partner-data: unset token -> 503",
              client.get("/partner/transfer-dates").status_code == 503)
        os.environ["PARTNER_NOTES_TOKEN"] = "sekrit"
        check("partner-data: wrong token -> 401",
              client.get("/partner/transfer-dates",
                         headers={"X-Partner-Token": "no"}).status_code == 401)

        admin._one = lambda table, params=None, *a, **k: {"id": "stk1"} if table == "stakes" else None
        partner_data.requests.get = fake_get
        partner_data.requests.post = fake_post
        partner_data.requests.delete = fake_delete
        partner_data.requests.patch = fake_patch
        h = {"X-Partner-Token": "sekrit"}

        # Transfer dates: list + upsert (transfer_id derived from date when absent) + bad date 400.
        r = client.get("/partner/transfer-dates", headers=h)
        check("partner-data: transfers list", r.status_code == 200
              and r.json()["transfers"][0]["transfer_id"] == "t-2026-07-23")
        r = client.post("/partner/transfer-dates", headers=h, json={"transfer_date": "2026-09-03"})
        check("partner-data: transfer upsert derives id + stake-scoped",
              r.status_code == 200 and posted["body"].get("transfer_id") == "t-2026-09-03"
              and posted["body"].get("stake_id") == "stk1")
        check("partner-data: bad transfer date -> 400",
              client.post("/partner/transfer-dates", headers=h,
                          json={"transfer_date": "9/3/26"}).status_code == 400)

        # Ward goals: unit_number → unit_id mapping; unknown unit -> 404.
        r = client.post("/partner/ward-goals", headers=h,
                        json={"unit_number": 10, "transfer_id": "t-2026-07-23", "goal": 5})
        check("partner-data: ward goal maps unit_number->unit_id",
              r.status_code == 200 and posted["body"].get("unit_id") == "u10"
              and posted["body"].get("goal") == 5)
        check("partner-data: ward goal unknown unit -> 404",
              client.post("/partner/ward-goals", headers=h,
                          json={"unit_number": 99, "transfer_id": "t-2026-07-23", "goal": 5}).status_code == 404)
        r = client.get("/partner/ward-goals", headers=h)
        check("partner-data: ward-goals GET resolves null unit_number from unit_id",
              r.status_code == 200 and r.json()["goals"][0]["unit_number"] == 10)

        # Manual people: list maps id->uuid + unit_id->unit_number; create returns a uuid.
        r = client.get("/partner/manual-people", headers=h)
        person = r.json()["people"][0]
        check("partner-data: manual list maps id->uuid + unit_number",
              r.status_code == 200 and person["uuid"] == "mm1" and person["unit_number"] == 10)
        r = client.post("/partner/manual-people", headers=h,
                        json={"first_name": "Maria", "last_initial": "G", "unit_number": 10,
                              "baptism_date": "2026-08-15", "notes": "referral"})
        check("partner-data: manual create returns uuid + builds name + maps unit",
              r.status_code == 200 and r.json()["person"]["uuid"] == "new1"
              and posted["body"].get("name") == "Maria G" and posted["body"].get("unit_id") == "u10")
        check("partner-data: manual first_name required -> 400",
              client.post("/partner/manual-people", headers=h, json={"first_name": "  "}).status_code == 400)

        # Update (uuid present) WITHOUT notes must NOT wipe custom_notes (his app has no notes concept);
        # WITH notes it updates them. Preserves a web leader's notes on the shared member.
        client.post("/partner/manual-people", headers=h,
                    json={"first_name": "Maria", "uuid": "mm1", "unit_number": 10})
        check("partner-data: manual update omits custom_notes when notes not sent",
              "custom_notes" not in patched["body"])
        client.post("/partner/manual-people", headers=h,
                    json={"first_name": "Maria", "uuid": "mm1", "notes": "keep me"})
        check("partner-data: manual update sets custom_notes when notes sent",
              patched["body"].get("custom_notes") == "keep me")

        # Delete is stake-scoped.
        r = client.post("/partner/manual-people/delete", headers=h, json={"uuid": "mm1"})
        check("partner-data: manual delete stake-scoped",
              r.status_code == 200 and deleted.get("id") == "eq.mm1" and deleted.get("stake_id") == "eq.stk1")
    finally:
        admin._one, admin._sb_headers = saved_one, saved_headers
        partner_data.requests.get, partner_data.requests.post = saved_get, saved_post
        partner_data.requests.patch, partner_data.requests.delete = saved_patch, saved_delete
        for key, val in (("PARTNER_NOTES_TOKEN", saved_token), ("PARTNER_STAKE_UNIT", saved_stake)):
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def test_ratelimit_check_caps_attempts() -> None:
    # BACKEND-01: the sliding-window core raises 429 once `limit` hits land inside `window`.
    from fastapi import HTTPException
    from backend.auth_broker import ratelimit
    key = f"unit-test-{time.time()}"
    ratelimit._check(key, 2, 100)
    ratelimit._check(key, 2, 100)
    raised = False
    try:
        ratelimit._check(key, 2, 100)
    except HTTPException as e:
        raised = e.status_code == 429
    check("ratelimit: 3rd hit over limit 2 -> 429", raised)
    ratelimit._check(f"{key}-other", 2, 100)  # a distinct key is independent
    check("ratelimit: distinct key not limited", True)


def test_mfa_lockout_after_max_fails() -> None:
    # BACKEND-01: a pending login is dropped after _MFA_MAX_FAILS wrong codes (no infinite retry).
    lid = f"unit-test-{time.time()}"
    okta_flow._PENDING[lid] = {"session": None, "payload": {}, "fails": 0}
    for _ in range(okta_flow._MFA_MAX_FAILS - 1):
        okta_flow._bump_mfa_fail(okta_flow._PENDING[lid], lid, "u@x.test", "totp")
    check("mfa lockout: pending alive before the cap", lid in okta_flow._PENDING)
    locked = False
    try:
        okta_flow._bump_mfa_fail(okta_flow._PENDING[lid], lid, "u@x.test", "totp")
    except okta_flow.AuthError as e:
        locked = getattr(e, "kind", "") == "mfa_locked"
    check("mfa lockout: final wrong code raises mfa_locked", locked)
    check("mfa lockout: pending dropped after the cap", lid not in okta_flow._PENDING)


def test_membertools_persist_verifies_after_patch() -> None:
    """#0 fix F4: persist_membertools_refresh_rest must FAIL LOUDLY when the PATCH matched no row
    (PostgREST returns 200/204 with an empty effect — RLS or a missing credential row). Without the
    read-back the token silently vanishes and the daily sync reports needs-reauth days later."""
    from backend import credentials as _cred
    saved = (enroll.requests.get, enroll.requests.patch, enroll.SUPABASE_URL, enroll.SERVICE_KEY,
             _cred._encrypt_envelope)
    try:
        enroll.SUPABASE_URL = enroll.SUPABASE_URL or "https://test.supabase.co"
        enroll.SERVICE_KEY = enroll.SERVICE_KEY or "test-key"
        _cred._encrypt_envelope = lambda b: "enc-blob"            # no CP_TOKEN_KEY needed offline
        enroll.requests.patch = lambda *a, **k: _FakeResp(None, status=204)

        # Happy path: stake resolves, PATCH ok, verify-GET shows the token stored -> no raise.
        def get_ok(url, *a, **k):
            return _FakeResp([{"membertools_refresh_enc": "enc-blob"}]) if "stake_credentials" in url \
                else _FakeResp([{"id": "stake-uuid"}])
        enroll.requests.get = get_ok
        ok = True
        try:
            enroll.persist_membertools_refresh_rest(503991, "R-TOKEN")
        except Exception:
            ok = False
        check("membertools persist: stored token verifies -> no raise", ok)

        # Silent no-op: PATCH 'succeeds' but the verify-GET shows NO row -> must raise (fails pre-fix).
        def get_empty(url, *a, **k):
            return _FakeResp([]) if "stake_credentials" in url else _FakeResp([{"id": "stake-uuid"}])
        enroll.requests.get = get_empty
        raised = False
        try:
            enroll.persist_membertools_refresh_rest(503991, "R-TOKEN")
        except RuntimeError:
            raised = True
        check("membertools persist: empty verify-GET raises (catches the silent no-op)", raised)
    finally:
        (enroll.requests.get, enroll.requests.patch, enroll.SUPABASE_URL, enroll.SERVICE_KEY,
         _cred._encrypt_envelope) = saved



def test_feedback_inbox_and_thank_you() -> None:
    # Item 2 (2026-08-25): feedback used to exist ONLY as a GitHub issue -- no admin inbox, no
    # addressed state, no word back to the reporter, no ping to the owner. Now /feedback also records
    # a row + emails the owner, and an admin can flip it to addressed, which thanks the reporter once.
    # FAILS pre-fix: none of these routes/functions existed.
    from backend.auth_broker.app import require_user
    app.dependency_overrides[require_user] = lambda: "reporter@test"
    app.dependency_overrides[require_admin] = lambda: "admin@test"
    saved = (admin.create_feedback_issue, admin.record_feedback, admin.list_feedback,
             admin._one, admin._send_email, admin.OWNER_EMAIL, admin._sb_headers)
    # _sb_headers raises without SUPABASE_URL/SERVICE_ROLE_KEY, which the offline suite has no reason
    # to set; the REST calls themselves are stubbed below.
    admin._sb_headers = lambda: {}
    sent: list = []
    patched: list = []
    admin.OWNER_EMAIL = "owner@test"
    admin.create_feedback_issue = lambda t, b, reporter: {"number": 7, "url": "https://gh/7",
                                                          "copilot": False}
    admin.record_feedback = lambda t, b, reporter, issue: {"id": 42}
    admin._send_email = lambda to, subject, html: sent.append((to, subject, html))
    try:
        r = client.post("/feedback", json={"title": "Bug <b>x</b>", "body": "it broke @everyone"})
        body = r.json()
        check("feedback -> 200", r.status_code == 200)
        check("feedback still returns the GitHub issue", body.get("number") == 7)
        check("feedback returns the inbox row id", body.get("feedback_id") == 42)
        check("feedback notified the owner", body.get("owner_notified") is True)
        check("owner email went to OWNER_EMAIL", sent and sent[0][0] == "owner@test")
        check("owner email escapes reporter-supplied HTML (BACKEND-02)",
              "<b>x</b>" not in sent[0][2] and "&lt;b&gt;" in sent[0][2])

        # A Supabase/Resend outage must NEVER cost us the report: the issue is already filed.
        sent.clear()
        admin.record_feedback = lambda t, b, reporter, issue: None
        admin.OWNER_EMAIL = ""
        r = client.post("/feedback", json={"title": "Second", "body": ""})
        check("feedback survives a failed inbox write", r.status_code == 200)
        check("feedback_id is null when the row didn't land", r.json().get("feedback_id") is None)
        check("owner_notified false without OWNER_EMAIL", r.json().get("owner_notified") is False)
        admin.OWNER_EMAIL = "owner@test"

        # The inbox lists + counts.
        admin.list_feedback = lambda status=None, limit=100: [
            {"id": 42, "status": "open", "title": "Bug"},
            {"id": 41, "status": "addressed", "title": "Old"},
        ]
        r = client.get("/admin/feedback")
        check("admin/feedback -> 200", r.status_code == 200)
        check("admin/feedback counts open", r.json().get("open") == 1)
        check("admin/feedback counts addressed", r.json().get("addressed") == 1)

        # Marking addressed patches the row and thanks the reporter exactly once.
        sent.clear()
        admin._one = lambda table, params: {"id": 42, "title": "Bug", "status": "open",
                                            "reporter_email": "reporter@test", "thanked_at": None}
        import backend.auth_broker.admin as _a

        class _Resp:
            status_code = 200
            text = ""

            def json(self):
                return []

        saved_patch = _a.requests.patch          # restored in `finally` -- this is the SHARED
        _a.requests.patch = lambda *a, **k: (      # requests module, so leaking it breaks later tests
            patched.append(k.get("json")), _Resp())[1]
        r = client.post("/admin/feedback/42/status", json={"status": "addressed", "note": "Fixed it."})
        out = r.json()
        check("mark addressed -> 200", r.status_code == 200)
        check("mark addressed reports thanked", out.get("thanked") is True)
        check("thank-you went to the reporter", sent and sent[0][0] == "reporter@test")
        check("thank-you quotes the admin's note", "Fixed it." in sent[0][2])
        check("addressed_by is the acting admin",
              any((p or {}).get("addressed_by") == "admin@test" for p in patched))
        check("thanked_at stamped after a successful send",
              any("thanked_at" in (p or {}) for p in patched))

        # Re-marking an already-thanked report must not email them again.
        sent.clear()
        patched.clear()
        admin._one = lambda table, params: {"id": 42, "title": "Bug", "status": "addressed",
                                            "reporter_email": "reporter@test",
                                            "thanked_at": "2026-08-25T00:00:00Z"}
        r = client.post("/admin/feedback/42/status", json={"status": "addressed", "note": ""})
        check("re-mark does not re-thank", r.json().get("thanked") is False and not sent)
        check("re-mark reports already_thanked", r.json().get("already_thanked") is True)

        # A bad status is rejected, not silently coerced.
        r = client.post("/admin/feedback/42/status", json={"status": "wontfix"})
        check("invalid status -> 400", r.status_code == 400)
    finally:
        import backend.auth_broker.admin as _a2
        if "saved_patch" in dir():
            _a2.requests.patch = saved_patch
        (admin.create_feedback_issue, admin.record_feedback, admin.list_feedback,
         admin._one, admin._send_email, admin.OWNER_EMAIL, admin._sb_headers) = saved
        app.dependency_overrides.pop(require_user, None)
        app.dependency_overrides.pop(require_admin, None)

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
    test_enrolled_stakes_self_renewing_from_membertools()
    test_endpoint_health_trend()
    test_enrollment_status_patriarchal_signal()
    test_profile_refresh_worker_fills_via_live_session()
    test_profile_refresh_on_demand_start_and_status()
    test_membertools_persist_verifies_after_patch()
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
    test_mfa_factor_filtering_webauthn()
    test_mfa_all_factors_unsupported_friendly()
    test_okta_verify_nested_method_prefers_totp()
    test_select_factor_refuses_non_code_challenge()
    test_verify_answers_with_declared_field()
    test_verify_normalizes_code()
    test_verify_wrong_code_friendly_and_state_refresh()
    test_captured_session_verify()
    test_verify_no_message_still_friendly()
    test_mfa_bad_code_factor_guidance()
    test_mfa_expired_messages_friendly()
    test_nested_idx_messages_and_mask()
    test_mfa_pending_and_select_failures_audited()
    test_provider_wipe_data()
    test_admin_reauth_email()
    test_feedback_inbox_and_thank_you()
    test_full_eval_enroll_reaches_scrape_and_stores()
    test_full_eval_new_stake_offers_enroll()
    test_ward_leader_enroll_refused_friendly()
    test_ward_leader_new_stake_points_to_stake_leader()
    test_ward_leader_no_children_still_refused()
    test_friendly_okta_errors()
    test_password_endpoint_friendly_bad_creds()
    test_sync_now_blocked_when_revoked()
    test_admin_requires_auth()
    test_admin_actions_graceful_without_github()
    test_dispatch_allowlist()
    test_report_html_escapes_member_data()
    test_safe_cred_id_rejects_filter_metachars()
    test_user_routes_require_auth()
    test_partner_notes_lane()
    test_partner_data_lanes()
    test_ratelimit_check_caps_attempts()
    test_mfa_lockout_after_max_fails()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
