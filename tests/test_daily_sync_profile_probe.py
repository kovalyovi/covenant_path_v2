"""Daily-sync hook for the proactive needs-reauth email (2026-11-08): after a healthy roster sync,
when THIS run established the stored LCR session can't renew headlessly (the Member Tools token
kept the sync alive, so the profile fill silently stopped), the sync asks the broker to probe the
session and email the provider once per streak if it's dead and members still have profile gaps.

REPRODUCES the Oct 12 -> Nov 8 gap: a dead session + gaps + a last profile_refresh outcome of
'done' must POST to the broker probe endpoint — before this fix the sync never asked anyone, so no
email fired for 27 days. FAILS pre-fix: `_maybe_profile_reauth_probe` does not exist.
"""

from __future__ import annotations

import os

import pytest
import requests

import backend.db as _db
import scripts.daily_sync as ds


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._p = status, payload or {}

    @property
    def text(self):
        return str(self._p)


class _FakeCursor:
    """fetchone() answers the hook's two queries in order: gaps count, then last outcome."""

    def __init__(self, fetch_results):
        self._results = list(fetch_results)
        self.executed: list[str] = []

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchone(self):
        return self._results.pop(0) if self._results else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


ST = {"stake_id": "stake-1", "unit_number": 503991, "name": "Raleigh North Carolina West Stake"}


@pytest.fixture()
def hook_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc-key")
    monkeypatch.delenv("BROKER_URL", raising=False)
    posts: list = []

    def fake_post(url, timeout=None, headers=None, json=None):
        posts.append({"url": url, "timeout": timeout, "headers": headers, "json": json})
        return _Resp(200, {"status": "needs_reauth"})

    monkeypatch.setattr(requests, "post", fake_post)
    return {"posts": posts}


def _set_db(monkeypatch, gaps, last_outcome):
    cur = _FakeCursor([(gaps,), (last_outcome,)])
    monkeypatch.setattr(_db, "connect", lambda: _FakeConn(cur))
    return cur


def test_dead_session_with_gaps_and_no_streak_posts_to_broker(hook_env, monkeypatch):
    """The Oct 12 -> Nov 8 gap, reproduced: dead session + 80 gaps + last outcome 'done' must ask
    the broker to probe (service-key auth, unit + stake). FAILS pre-fix: no hook exists."""
    cur = _set_db(monkeypatch, 80, "done")
    ds._maybe_profile_reauth_probe(ST, True)
    assert len(hook_env["posts"]) == 1, "exactly one probe call"
    post = hook_env["posts"][0]
    assert post["url"] == "https://covenant-path-broker.onrender.com/auth/profile-refresh/probe"
    assert post["headers"]["Authorization"] == "Bearer svc-key"
    assert post["json"] == {"unit_number": 503991, "stake_id": "stake-1"}
    assert "members" in " ".join(cur.executed).lower()
    assert "profile_refresh" in " ".join(cur.executed)


def test_already_notified_streak_does_not_post(hook_env, monkeypatch):
    """Once per streak: when the last profile_refresh outcome is already needs_reauth, the sync
    does not call the broker again."""
    _set_db(monkeypatch, 80, "needs_reauth")
    ds._maybe_profile_reauth_probe(ST, True)
    assert hook_env["posts"] == []


def test_no_gaps_does_not_post(hook_env, monkeypatch):
    """Nothing to fill → nothing to email about, no broker call at all."""
    _set_db(monkeypatch, 0, "done")
    ds._maybe_profile_reauth_probe(ST, True)
    assert hook_env["posts"] == []


def test_live_session_does_not_post(hook_env, monkeypatch):
    """A session that renewed fine needs no email — the hook is only for a dead one."""
    cur = _set_db(monkeypatch, 80, "done")
    ds._maybe_profile_reauth_probe(ST, False)
    assert hook_env["posts"] == []
    assert cur.executed == [], "no DB work at all when the session is alive"


def test_broker_failure_never_breaks_the_sync(hook_env, monkeypatch):
    """The broker being down (or the DB hiccuping) must never raise out of the hook — the sync
    already succeeded; alerting is best-effort."""
    _set_db(monkeypatch, 80, "done")
    monkeypatch.setattr(requests, "post", lambda *a, **k: 1 / 0)
    ds._maybe_profile_reauth_probe(ST, True)  # must not raise
    monkeypatch.setattr(_db, "connect", lambda: 1 / 0)
    ds._maybe_profile_reauth_probe(ST, True)  # must not raise either


def test_no_service_key_skips_quietly(hook_env, monkeypatch):
    """Without the service key the broker can't be called — skip instead of posting unauthenticated."""
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    _set_db(monkeypatch, 80, "done")
    ds._maybe_profile_reauth_probe(ST, True)
    assert hook_env["posts"] == []
