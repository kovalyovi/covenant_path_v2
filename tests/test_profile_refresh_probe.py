"""Proactive needs-reauth probe (2026-11-08): the daily sync succeeds on the Member Tools token
while the stored LCR session is dead, so the profile fill silently stops and nobody hears until a
leader opens the app. The sync asks the broker to probe the stored session after a healthy sync;
when it's dead and members still have profile gaps, the provider gets the needs-reauth email once
per streak (missing counts + /reauth link) and the outcome is recorded, so the app banner and the
sync's own guard see the same streak. When the session is alive (or there is nothing to fill) the
probe answers that and sends nothing.

REPRODUCES the Oct 12 -> Nov 8 gap: a dead session + gaps + a last outcome of 'done' (the Oct 12
run) must EMAIL — before this fix nothing in the system attempted a fill between the last fill and
the leader opening the app, so no needs_reauth event ever fired.
"""

from __future__ import annotations

import types as _types

import pytest

from backend.auth_broker import enroll


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p


@pytest.fixture()
def probe_env(monkeypatch):
    """Run `probe_profile_session` offline. `client` controls what /mlt answers."""
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setattr(enroll, "SUPABASE_URL", "https://x")
    monkeypatch.setattr(enroll, "SERVICE_KEY", "k")
    monkeypatch.setattr(enroll, "_sb_h", lambda: {})
    monkeypatch.setattr(enroll, "_profile_worklist",
                        lambda stake_id: [{"person_uuid": "p1"}, {"person_uuid": "p2"}])
    monkeypatch.setattr(enroll.requests, "get", lambda url, headers=None, params=None,
                        timeout=None: _Resp([{"credential_enc": "blob", "revoked": False}])
                        if url.endswith("/stake_credentials") else _Resp([]))
    from backend import credentials as _creds
    monkeypatch.setattr(_creds, "_decrypt_envelope",
                        lambda blob: b'{"cookies": [{"name": "x"}]}')
    notified: list = []
    recorded: list = []
    monkeypatch.setattr(enroll, "_notify_profile_refresh",
                        lambda stake_id, **kw: notified.append((stake_id, kw)) or True)
    monkeypatch.setattr(enroll, "_record_profile_refresh",
                        lambda stake_id, payload: recorded.append(payload))
    monkeypatch.setattr(enroll, "_last_profile_refresh_outcome", lambda stake_id: "done")
    return {"notified": notified, "recorded": recorded}


def _dead_client(cookies):
    def _raise(url, params=None):
        raise RuntimeError("redirected to login")
    return _types.SimpleNamespace(session=_types.SimpleNamespace(get_text=_raise))


def _alive_client(cookies):
    page = "<!doctype html><html><body id='member-profile'>" + "x" * 800 + "</body></html>"
    return _types.SimpleNamespace(session=_types.SimpleNamespace(
        get_text=lambda url, params=None: page))


def test_dead_session_with_gaps_emails_once_and_records(probe_env, monkeypatch):
    """The Oct 12 -> Nov 8 gap, reproduced: dead session + gaps + last outcome 'done' must email
    the provider (once per streak) and record the needs_reauth outcome. FAILS pre-fix: nothing in
    the system probed the session between fills, so no email ever fired."""
    monkeypatch.setattr(enroll, "_client_from_cookies", _dead_client)
    out = enroll.probe_profile_session(503991, "stake-1")
    assert out["status"] == "needs_reauth" and out["reason"] == "session_expired", out
    assert out["members_with_gaps"] == 2, out
    assert len(probe_env["notified"]) == 1, "exactly one needs_reauth email"
    stake_id, kw = probe_env["notified"][0]
    assert stake_id == "stake-1" and kw["outcome"] == "needs_reauth" and kw["total"] == 2
    assert len(probe_env["recorded"]) == 1, "the streak is recorded for the banner + the sync guard"
    assert probe_env["recorded"][0]["outcome"] == "needs_reauth"
    assert probe_env["recorded"][0]["source"] == "probe"


def test_already_notified_streak_probes_nothing_and_emails_nothing(probe_env, monkeypatch):
    """Once per streak: when the last outcome is already needs_reauth, the probe answers that
    without re-probing, re-emailing, or re-recording."""
    monkeypatch.setattr(enroll, "_last_profile_refresh_outcome", lambda stake_id: "needs_reauth")
    probed: list = []
    monkeypatch.setattr(enroll, "_client_from_cookies",
                        lambda cookies: probed.append(cookies) or _dead_client(cookies))
    out = enroll.probe_profile_session(503991, "stake-1")
    assert out["status"] == "needs_reauth" and out["reason"] == "already_notified", out
    assert not probed and not probe_env["notified"] and not probe_env["recorded"]


def test_live_session_answers_alive_and_sends_nothing(probe_env, monkeypatch):
    """A live session needs no email and no record — the fill isn't blocked."""
    monkeypatch.setattr(enroll, "_client_from_cookies", _alive_client)
    out = enroll.probe_profile_session(503991, "stake-1")
    assert out["status"] == "alive" and out["members_with_gaps"] == 2, out
    assert not probe_env["notified"] and not probe_env["recorded"]


def test_no_gaps_answers_nothing_to_fill_without_probing(probe_env, monkeypatch):
    """Nothing to fill → nothing to email about, and the session isn't even probed."""
    monkeypatch.setattr(enroll, "_profile_worklist", lambda stake_id: [])
    probed: list = []
    monkeypatch.setattr(enroll, "_client_from_cookies",
                        lambda cookies: probed.append(cookies) or _dead_client(cookies))
    out = enroll.probe_profile_session(503991, "stake-1")
    assert out["status"] == "nothing_to_fill" and out["members_with_gaps"] == 0, out
    assert not probed and not probe_env["notified"] and not probe_env["recorded"]


def test_no_credential_is_needs_reauth_not_a_crash(probe_env, monkeypatch):
    """No stored credential at all is the same dead end (the provider must re-authorize) — the
    probe answers needs_reauth and emails, it doesn't raise."""
    monkeypatch.setattr(enroll.requests, "get", lambda url, headers=None, params=None,
                        timeout=None: _Resp([]))
    out = enroll.probe_profile_session(503991, "stake-1")
    assert out["status"] == "needs_reauth" and out["reason"] == "no_credential", out
    assert len(probe_env["notified"]) == 1


def test_probe_never_raises(probe_env, monkeypatch):
    """A probe that blows up (Supabase hiccup, decrypt failure) answers 'failed' — it must never
    take down the caller (the daily sync)."""
    monkeypatch.setattr(enroll, "_profile_worklist", lambda stake_id: 1 / 0)
    out = enroll.probe_profile_session(503991, "stake-1")
    assert out["status"] == "failed" and out.get("error"), out


# --- the on-demand start records its dead-session discovery -------------------------------
# 2026-11-08: the sheet latched the Oct 12 expired-session notice because the start's
# needs_reauth answer was never recorded — the status had no row behind it, so nothing could
# clear the banner after the 9:41pm fill completed. The start records the discovery now.

def test_start_records_needs_reauth_discovery(probe_env, monkeypatch):
    monkeypatch.setattr(enroll, "_client_from_cookies", _dead_client)
    monkeypatch.setattr(enroll, "_refresh_profile_async", lambda *a, **k: None)
    enroll._REFRESH_PROGRESS.pop(503991, None)
    out = enroll.start_profile_refresh(503991, "stake-1")
    assert out["status"] == "needs_reauth" and out["reason"] == "session_expired", out
    assert len(probe_env["recorded"]) == 1, "the discovery is recorded for the status + the sync guard"
    assert probe_env["recorded"][0]["outcome"] == "needs_reauth"
    assert probe_env["recorded"][0]["source"] == "on_demand"
    assert len(probe_env["notified"]) == 1, "the email still fires once per streak"


def test_start_with_live_session_records_nothing(probe_env, monkeypatch):
    """A start that spawns the worker records nothing itself — the worker records on completion."""
    spawned: list = []
    monkeypatch.setattr(enroll, "_client_from_cookies", _alive_client)
    monkeypatch.setattr(enroll, "_refresh_profile_async",
                        lambda cookies, unit, source="reauth": spawned.append((unit, source)))
    enroll._REFRESH_PROGRESS.pop(503991, None)
    out = enroll.start_profile_refresh(503991, "stake-1")
    assert out["status"] == "started" and spawned == [(503991, "on_demand")], out
    assert not probe_env["recorded"] and not probe_env["notified"]
