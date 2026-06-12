"""
Offline tests for the credential-capture (one-MFA) login flow — backend/auth_broker/web_session.py.

The flow (proven live 2026-06-12): authn -> sessionToken -> LCR authorize -> MFA (ONE code) ->
appSession + Member Tools 45-day token. These mock the network legs (authn / authorize / IDX
follow / identity / mint) so the ORCHESTRATION is verified deterministically: web_start ->
web_select_factor -> web_verify yields a success result carrying identity, cookies, AND the
membertools_refresh token; and a wrong code raises the friendly mfa failure (pending preserved).

Run: python -m pytest tests/test_web_session.py -q
"""

from __future__ import annotations

import pytest

from backend.auth_broker import web_session as ws
from backend.auth_broker import okta_flow


def _select_payload():
    """An IDX payload at the MFA factor menu with a TOTP (google_otp) authenticator."""
    return {
        "stateHandle": "sh-1",
        "authenticators": {"value": [{"id": "totp-id", "key": "google_otp"}]},
        "remediation": {"value": [{
            "name": "select-authenticator-authenticate", "href": "https://x/idx/select",
            "value": [{"name": "authenticator", "options": [{
                "label": "Google Authenticator",
                "value": {"form": {"value": [{"name": "id", "value": "totp-id"},
                                             {"name": "methodType", "value": "otp"}]}},
            }]}]}]},
    }


def _challenge_payload():
    return {"stateHandle": "sh-2", "remediation": {"value": [{
        "name": "challenge-authenticator", "href": "https://x/idx/challenge",
        "value": [{"name": "credentials", "form": {"value": [{"name": "passcode"}]}}]}]}}


@pytest.fixture()
def patched(monkeypatch):
    """Mock the network legs; the test drives the orchestration."""
    calls = {"answered": None, "minted": False, "followed_success": False}

    monkeypatch.setattr(ws, "_authn", lambda s, u, p, lid: "SESSION-TOKEN")
    monkeypatch.setattr(ws, "_open_lcr_authorize", lambda s, t, lid: _select_payload())
    monkeypatch.setattr(ws, "new_session", lambda: type("S", (), {"headers": {}})())

    def fake_follow(session, rem, body, **kw):
        # select-authenticator -> the challenge; challenge-authenticator -> success or failure
        if rem.get("name") == "select-authenticator-authenticate":
            return _challenge_payload()
        calls["answered"] = body.get("credentials", {})
        if body["credentials"].get("passcode") == "654321":  # the "right" code
            return {"successWithInteractionCode": {"href": "https://x/success"},
                    "stateHandle": "sh-done"}
        from lcr_client.okta_login import LoginError
        raise LoginError("IDX step challenge failed: HTTP 401", payload={
            "stateHandle": "sh-2b",
            "remediation": {"value": [{"name": "challenge-authenticator",
                "value": [{"name": "credentials", "form": {"value": [{"name": "passcode",
                    "messages": {"value": [{"message": "Invalid code. Try again.", "class": "ERROR"}]}}]}}]}]},
        })

    # _follow is imported into web_session's namespace; patch it there.
    monkeypatch.setattr(ws, "_follow", fake_follow)

    def fake_finish_success(session, payload, lid):
        calls["followed_success"] = True
    monkeypatch.setattr(ws, "_follow_success", fake_finish_success)
    monkeypatch.setattr(ws, "_identity", lambda s, lid: {"email": "leader@example.com", "name": "Leader"})
    monkeypatch.setattr(ws, "serialize_cookies", lambda s: [{"name": "appSession.0", "value": "x"}])

    def fake_mint(session, lid):
        calls["minted"] = True
        return "MT-REFRESH-45D"
    monkeypatch.setattr(ws, "_mint_membertools", fake_mint)
    return calls


def test_one_mfa_yields_identity_cookies_and_membertools_token(patched):
    r = ws.web_start("leader.example", "pw")
    assert r["status"] == "mfa_required"
    lid = r["login_id"]
    assert any(f["method"] == "otp" for f in r["factors"])  # TOTP factor surfaced

    totp = next(f for f in r["factors"] if f["method"] == "otp")
    assert ws.web_select_factor(lid, totp["id"])["status"] == "code_sent"

    res = ws.web_verify(lid, "654321")  # the right code
    assert res["status"] == "success"
    assert res["identity"]["email"] == "leader@example.com"
    assert any(c["name"].startswith("appSession") for c in res["cookies"])
    # THE point of the whole flow: the one MFA produced the 45-day Member Tools token.
    assert res["membertools_refresh"] == "MT-REFRESH-45D"
    assert patched["minted"] and patched["followed_success"]
    assert lid not in ws._WEB_PENDING  # cleaned up


def test_wrong_code_is_friendly_and_keeps_pending(patched):
    r = ws.web_start("leader.example", "pw")
    lid = r["login_id"]
    totp = next(f for f in r["factors"] if f["method"] == "otp")
    ws.web_select_factor(lid, totp["id"])
    with pytest.raises(okta_flow.AuthError) as ei:
        ws.web_verify(lid, "000000")  # wrong
    assert getattr(ei.value, "kind", "") == "mfa_bad_code"
    assert "{" not in str(ei.value)  # never raw IDX JSON
    assert lid in ws._WEB_PENDING  # pending survives for a retry


def test_no_mfa_account_finishes_immediately(monkeypatch):
    # An account with no MFA: authorize completes silently (no widget) → finish right away.
    monkeypatch.setattr(ws, "_authn", lambda s, u, p, lid: "TOK")
    monkeypatch.setattr(ws, "_open_lcr_authorize", lambda s, t, lid: None)  # no widget
    monkeypatch.setattr(ws, "new_session", lambda: type("S", (), {"headers": {}})())
    monkeypatch.setattr(ws, "_follow_success", lambda s, p, lid: None)
    monkeypatch.setattr(ws, "_identity", lambda s, lid: {"email": "nomfa@example.com"})
    monkeypatch.setattr(ws, "serialize_cookies", lambda s: [{"name": "appSession.0", "value": "x"}])
    monkeypatch.setattr(ws, "_mint_membertools", lambda s, lid: "MT-NOMFA")
    res = ws.web_start("nomfa.leader", "pw")
    assert res["status"] == "success"
    assert res["membertools_refresh"] == "MT-NOMFA"
    assert res["identity"]["email"] == "nomfa@example.com"
