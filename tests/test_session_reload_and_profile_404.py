"""
The two mechanics behind "I re-authorized and it still filled nothing" (Raleigh, 2026-08-30).

Broker log, in order, inside one 19-second window on a session that was 5 seconds old:

    12:12:31  giving up on profile_action 60d3d432 (permanent failure, not retried): 404 ...
    12:12:31  profile action returned no data - attempting action-id auto-discovery
    12:12:46  http discovery: 77 server actions harvested, mapped [... 'record']
    12:12:49  profile refresh: filled fields for 0/9 members with gaps in stake 503991 -> needs_reauth

Eight members processed in the 3.5s after the heal, with no per-member warning at all. That is not
what a live session looks like, and it is not what a dead one looks like either. Two bugs:

  1. `LcrSession.reload()` cleared the cookie jar BEFORE reading the state file. The broker's
     delegated session is built by `_client_from_cookies`, which injects cookies and deletes its
     temp state file -- so the reload at the tail of `action_discovery.heal()` wiped the live
     session and swallowed the FileNotFoundError. Every later call went out unauthenticated.
  2. A 404 on ONE member's profile page ("this person has no record") was treated as the
     stale-action-id signal, triggering that heal in the first place.

FAILS pre-fix: reload() left the jar empty and raised; fetch_member_profile healed on a 404 and
raised a bare RuntimeError indistinguishable from a dead session.
"""

from __future__ import annotations

import json

import pytest
import requests

from lcr_client import member_profile
from lcr_client.auth import LcrSession


# --- bug 1: reload() must never leave a working session with no cookies ---------------------------

def _session_with_cookies(tmp_path, cookies):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    s = LcrSession(storage_state_path=state, auto_login=False)
    return s, state


COOKIE = [{"name": "okta_sid", "value": "live-value", "domain": "lcr.churchofjesuschrist.org",
           "path": "/"}]


def test_reload_keeps_cookies_when_the_state_file_is_gone(tmp_path):
    """The broker's exact shape: cookies injected, temp file deleted, then something calls reload()."""
    s, state = _session_with_cookies(tmp_path, COOKIE)
    state.unlink()

    s.reload()  # pre-fix: cleared the jar, then raised FileNotFoundError

    assert s.session.cookies.get("okta_sid") == "live-value"


def test_reload_keeps_cookies_when_the_state_file_is_empty(tmp_path):
    """A truncated/empty state file is not a reason to throw away a working session either."""
    s, state = _session_with_cookies(tmp_path, COOKIE)
    state.write_text(json.dumps({"cookies": []}), encoding="utf-8")

    s.reload()

    assert s.session.cookies.get("okta_sid") == "live-value"


def test_reload_still_picks_up_refreshed_cookies(tmp_path):
    """The feature reload() exists for keeps working: a re-minted session file replaces the jar."""
    s, state = _session_with_cookies(tmp_path, COOKIE)
    state.write_text(json.dumps({"cookies": [dict(COOKIE[0], value="fresh-value")]}),
                     encoding="utf-8")

    s.reload()

    assert s.session.cookies.get("okta_sid") == "fresh-value"


# --- bug 2: a member-specific 404 is not a stale action id ----------------------------------------

class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _http_error(status_code):
    exc = requests.HTTPError(f"{status_code} Client Error")
    exc.response = _FakeResponse(status_code)
    return exc


@pytest.fixture()
def no_heal(monkeypatch):
    """Record whether action-id auto-discovery was triggered."""
    healed: list = []
    monkeypatch.setattr(member_profile, "_heal_once",
                        lambda session, uuid: healed.append(uuid))
    return healed


def test_a_404_profile_page_raises_ProfileNotFound_without_healing(monkeypatch, no_heal):
    """One member with no LCR record must not cost a full action-id rediscovery."""
    monkeypatch.setattr(member_profile, "call_action",
                        lambda s, uuid, aid, args, errors=None: (
                            errors.append(_http_error(404)) if errors is not None else None) or [])

    with pytest.raises(member_profile.ProfileNotFound):
        member_profile.fetch_member_profile(object(), "9dd08cec")

    assert no_heal == []  # pre-fix: healed, then raised a bare RuntimeError


def test_no_data_without_a_404_still_heals_and_retries(monkeypatch, no_heal):
    """The genuine stale-action-id signature -- empty rows, no permanent 404 -- must still self-heal."""
    monkeypatch.setattr(member_profile, "call_action",
                        lambda s, uuid, aid, args, errors=None: [])

    with pytest.raises(RuntimeError) as excinfo:
        member_profile.fetch_member_profile(object(), "9dd08cec")

    assert not isinstance(excinfo.value, member_profile.ProfileNotFound)
    assert no_heal == ["9dd08cec"]


def test_a_404_after_a_heal_is_still_reported_as_not_found(monkeypatch, no_heal):
    """Rows come back empty first (so we heal), and only then does the 404 land."""
    calls = {"n": 0}

    def _call(s, uuid, aid, args, errors=None):
        calls["n"] += 1
        if calls["n"] > 1 and errors is not None:
            errors.append(_http_error(404))
        return []

    monkeypatch.setattr(member_profile, "call_action", _call)

    with pytest.raises(member_profile.ProfileNotFound):
        member_profile.fetch_member_profile(object(), "9dd08cec")

    assert no_heal == ["9dd08cec"]


# --- the reason plumbing the worker's verdict rests on --------------------------------------------

def test_refresh_profile_fields_ex_reports_not_found_separately(monkeypatch):
    from covenant_path import report

    monkeypatch.setattr(report, "profile_fields",
                        lambda session, uuid: (_ for _ in ()).throw(
                            member_profile.ProfileNotFound("no record")))
    client = type("C", (), {"session": object()})()

    assert report.refresh_profile_fields_ex(client, {"person_uuid": "p1"}) == ({}, "not_found")


def test_refresh_profile_fields_ex_reports_a_dead_fetch_separately(monkeypatch):
    from covenant_path import report

    monkeypatch.setattr(report, "profile_fields",
                        lambda session, uuid: (_ for _ in ()).throw(RuntimeError("307")))
    client = type("C", (), {"session": object()})()

    assert report.refresh_profile_fields_ex(client, {"person_uuid": "p1"}) == ({}, "fetch_failed")


def test_refresh_profile_fields_ex_reports_a_missing_uuid_separately():
    from covenant_path import report

    assert report.refresh_profile_fields_ex(object(), {}) == ({}, "no_uuid")
