"""
The on-demand "fill missing member data" run must never report a DEAD session as a success.

2026-08-26: a fill ran against an expired stored session, fetched nothing, and finished as
`state="done"` — the sheet rendered "Last fill: 8/26/2026, 10:48:06 PM — 0/8 members updated" and
never asked the user to sign in. `sync_diagnostics` shows the same shape on 2026-08-16: `0/5`, then
`5/5` thirty-seven seconds later once a fresh session existed — i.e. a zero-fill is not "nothing to
do", it is "the session is dead".

Two independent guards, both tested here:
  1. the liveness probe validates the RESPONSE, not merely that no exception was raised (a dead LCR
     session can answer 200 with a sign-in / app-shell page from the LCR host, which `get_text`
     does not treat as expiry)
  2. the worker terminates as `needs_reauth` whenever it processed members and filled none — the
     catch-all that holds no matter what shape a dead session takes next

FAILS pre-fix: `_looks_like_member_profile` did not exist and the worker always ended `done`.
"""

from __future__ import annotations

import pytest

from backend.auth_broker import enroll


# --- guard 1: the liveness probe actually looks at the page ---------------------------------------

@pytest.mark.parametrize("page", [
    None,
    "",
    "<html><body>tiny shell</body></html>",                       # too small to be a real profile
    "<html><body>Please sign in to continue" + "x" * 800 + "</body></html>",
    "<html><body>Your session has expired" + "x" * 800 + "</body></html>",
    "<html><body>Access denied" + "x" * 800 + "</body></html>",
    "<html><body>Enter your password" + "x" * 800 + "</body></html>",
])
def test_non_profile_pages_are_rejected(page):
    assert enroll._looks_like_member_profile(page) is False


@pytest.mark.parametrize("page", [
    "<!doctype html><html><body>" + "x" * 800 + "</body></html>",
    "<html><div id='member-profile'>" + "x" * 800 + "</div></html>",
    "<html><script src='/mlt/app.js'></script>" + "x" * 800 + "</html>",
])
def test_real_profile_pages_are_accepted(page):
    assert enroll._looks_like_member_profile(page) is True


# --- guard 2: the worker's terminal state ---------------------------------------------------------

class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return []


@pytest.fixture()
def worker_env(monkeypatch):
    """Run `_refresh_profile_worker` offline. `patches` controls what each member yields."""
    monkeypatch.setattr(enroll, "SUPABASE_URL", "https://x")
    monkeypatch.setattr(enroll, "SERVICE_KEY", "k")
    monkeypatch.setattr(enroll, "_sb_h", lambda: {})
    monkeypatch.setattr(enroll, "_stake_id_for_unit_rest", lambda unit: "stake-1")
    monkeypatch.setattr(enroll, "_client_from_cookies", lambda cookies: object())
    monkeypatch.setattr(enroll, "_profile_worklist",
                        lambda stake_id: [{"person_uuid": f"p{i}"} for i in range(8)])
    monkeypatch.setattr(enroll.requests, "patch", lambda *a, **k: _Resp())
    recorded: list = []
    monkeypatch.setattr(enroll, "_record_profile_refresh",
                        lambda stake_id, payload: recorded.append(payload))
    enroll._REFRESH_PROGRESS.pop(503991, None)
    return recorded


def _run(monkeypatch, patch_for):
    from covenant_path import report
    monkeypatch.setattr(report, "refresh_profile_fields", patch_for)
    enroll._refresh_profile_worker([], 503991, source="on_demand")
    return dict(enroll._REFRESH_PROGRESS.get(503991) or {})


def test_a_zero_fill_run_ends_as_needs_reauth(worker_env, monkeypatch):
    """The exact 2026-08-26 shape: 8 members with gaps, every profile fetch fails -> {}."""
    prog = _run(monkeypatch, lambda client, row: {})
    assert prog["state"] == "needs_reauth"          # was "done" pre-fix -> "0/8 members updated"
    assert prog["total"] == 8 and prog["filled"] == 0
    assert prog["error"]                             # says why, for the ops trail
    assert worker_env[-1]["outcome"] == "needs_reauth"


def test_a_successful_fill_still_ends_done(worker_env, monkeypatch):
    prog = _run(monkeypatch, lambda client, row: {"patriarchal_blessing": "Yes"})
    assert prog["state"] == "done"
    assert prog["filled"] == 8
    assert worker_env[-1]["outcome"] == "done"


def test_a_partial_fill_is_a_success_not_a_dead_session(worker_env, monkeypatch):
    """Some members genuinely have no record to pull; that is NOT a dead session. Only filling
    ZERO of a non-empty worklist is."""
    def _partial(client, row):
        return {"patriarchal_blessing": "Yes"} if row["person_uuid"] in ("p0", "p1") else {}
    prog = _run(monkeypatch, _partial)
    assert prog["state"] == "done"
    assert prog["filled"] == 2


def test_an_empty_worklist_is_done_not_needs_reauth(worker_env, monkeypatch):
    """Nothing to fill must never nag the user to re-authenticate."""
    monkeypatch.setattr(enroll, "_profile_worklist", lambda stake_id: [])
    prog = _run(monkeypatch, lambda client, row: {})
    assert prog["state"] == "done"
    assert prog["total"] == 0
