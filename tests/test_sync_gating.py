"""
Offline tests for the daily-sync gates (catalog rows E4 + E5) — no network, no DB.

E4: scripts.daily_sync._due_today — the delay-robust "due-by-hour" check that replaced the
fragile exact-hour match (GitHub cron fires 10-50 min late; a slipped fire must still sync,
and a stake must sync exactly once per day unless the run failed).

E5: scripts.daily_sync._revoke_if_ineligible — the every-sync re-verification that a stored
credential's calling STILL grants covenant-path access. Conservative by contract: only a
POSITIVE read of the runner's callings with zero granting positions may revoke; inconclusive
reads and scrape errors must never strand a healthy stake.

Run: python -m pytest tests/test_sync_gating.py -q
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import scripts.daily_sync as ds

ET = ZoneInfo("America/New_York")


def _et(hour: int, minute: int = 0, day: int = 10) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=ET)


# --- E4: _due_today ------------------------------------------------------------------------


def test_not_due_before_the_configured_hour():
    assert ds._due_today(_et(6, 59), 7, None) is False


def test_due_at_the_hour_when_never_synced():
    assert ds._due_today(_et(7, 0), 7, None) is True


def test_due_on_a_LATE_cron_fire_same_day():
    # The whole point of the window check: a 7:00 stake picked up by the 9:40 fire still syncs.
    assert ds._due_today(_et(9, 40), 7, _et(8, 0, day=9)) is True


def test_not_due_again_after_syncing_inside_todays_window():
    assert ds._due_today(_et(10, 0), 7, _et(7, 25)) is False


def test_failed_run_stays_due():
    # A sync that last SUCCEEDED before today's window opened keeps the stake due — retry.
    assert ds._due_today(_et(12, 0), 7, _et(23, 50, day=9)) is True


def test_naive_last_synced_treated_as_et_wall_clock():
    naive = datetime(2026, 6, 10, 7, 30)  # no tzinfo
    assert ds._due_today(_et(9, 0), 7, naive) is False
    naive_yesterday = datetime(2026, 6, 9, 7, 30)
    assert ds._due_today(_et(9, 0), 7, naive_yesterday) is True


def test_late_evening_hour_config():
    assert ds._due_today(_et(21, 5), 21, _et(7, 0)) is True
    assert ds._due_today(_et(20, 55), 21, _et(7, 0)) is False


# --- E5: _revoke_if_ineligible -------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.revoked: list[tuple] = []
        self.connected = 0


@pytest.fixture()
def patched(monkeypatch):
    """Stub the LCR scrape + DB seams; the test chooses what the access read returns."""
    import lcr_client
    import lcr_client.access as access_mod
    from backend import credentials as cred_mod
    from backend import db as db_mod

    rec = _Recorder()
    holder = {"access": None, "raise": None}

    class _FakeConn:
        def close(self):
            pass

    def fake_connect():
        rec.connected += 1
        return _FakeConn()

    def fake_access(client):
        if holder["raise"] is not None:
            raise holder["raise"]
        return holder["access"]

    monkeypatch.setattr(lcr_client, "LcrClient", lambda *a, **k: object())
    monkeypatch.setattr(access_mod, "covenant_path_access", fake_access)
    monkeypatch.setattr(db_mod, "connect", fake_connect)
    monkeypatch.setattr(cred_mod, "revoke",
                        lambda conn, stake_id, reason="": rec.revoked.append((stake_id, reason)))
    return rec, holder


_ST = {"stake_id": "stake-uuid-1", "name": "Testvale North Stake", "unit_number": 999001}


def test_still_authorized_leader_is_untouched(patched):
    rec, holder = patched
    holder["access"] = {"can_pull_all": True, "features": [],
                        "runner_positions": [{"name": "Stake President"}]}
    ds._revoke_if_ineligible(_ST)
    assert rec.revoked == []


def test_feature_rank_counts_as_authorized(patched):
    rec, holder = patched
    holder["access"] = {"can_pull_all": False,
                        "features": [{"feature": "progress-record", "allowed": True}],
                        "runner_positions": [{"name": "Some Calling"}]}
    ds._revoke_if_ineligible(_ST)
    assert rec.revoked == []


def test_inconclusive_read_never_revokes(patched):
    rec, holder = patched
    holder["access"] = {"can_pull_all": False, "features": [], "runner_positions": []}
    ds._revoke_if_ineligible(_ST)  # empty positions = couldn't determine -> keep the stake alive
    assert rec.revoked == []


def test_scrape_error_never_revokes(patched):
    rec, holder = patched
    holder["raise"] = RuntimeError("LCR 502")
    ds._revoke_if_ineligible(_ST)  # must swallow, not raise, not revoke
    assert rec.revoked == []


def test_positively_ineligible_runner_is_revoked_and_run_stops(patched):
    rec, holder = patched
    holder["access"] = {"can_pull_all": False, "features": [],
                        "runner_positions": [{"name": "Primary Pianist"}]}
    with pytest.raises(RuntimeError, match="no longer has covenant-path access"):
        ds._revoke_if_ineligible(_ST)
    assert rec.revoked and rec.revoked[0][0] == "stake-uuid-1"


def test_always_allowed_stewardship_calling_survives_an_empty_matrix(patched):
    # A stake clerk whose LCR access-table read came back empty must NOT be revoked: the
    # stake-stewardship safety net (backend.roles._calling_always_allowed) keeps them eligible.
    rec, holder = patched
    holder["access"] = {"can_pull_all": False, "features": [],
                        "runner_positions": [{"name": "Stake Clerk"}]}
    ds._revoke_if_ineligible(_ST)
    assert rec.revoked == []


# --- E6: Member Tools token acquisition (the 2026-06-12 "re-authorize loop" fix) -----------------
# The delegated sync mints the /api/v5/sync bearer via a SILENT prompt=none authorize that needs a
# LIVE Okta web session — which a stored delegated credential loses within days. The fix persists the
# Member Tools 45-day REFRESH token (Supabase, migration 0049) and renews off it with NO Okta session.
# These prove _membertools_access_token PREFERS the refresh token and only mints when there's none.


class _FakeMTClient:
    """Minimal stand-in: _membertools_access_token only touches client.session.session."""
    class _S:
        session = object()
    session = _S()


def _patch_membertools(monkeypatch, *, refresh_result=None, refresh_raises=False, mint_result=None):
    from lcr_client import membertools
    calls = {"refresh": 0, "mint": 0, "saved": [], "cleared": []}

    def fake_refresh(token):
        calls["refresh"] += 1
        if refresh_raises:
            raise membertools.RefreshTokenExpired("45-day wall")
        return refresh_result or {}

    def fake_mint(_session):
        calls["mint"] += 1
        return mint_result or {}

    monkeypatch.setattr(membertools, "refresh", fake_refresh)
    monkeypatch.setattr(membertools, "mint_from_okta_session", fake_mint)
    monkeypatch.setattr(ds, "_save_membertools_token", lambda u, t: calls["saved"].append((u, t)))
    monkeypatch.setattr(ds, "_clear_membertools_token", lambda u: calls["cleared"].append(u))
    return calls


def test_membertools_uses_stored_refresh_token_no_mint(monkeypatch):
    # Steady state: a stored 45-day refresh token renews the bearer with NO Okta session — the
    # mint-off-live-session path (which the aged delegated credential can't do) is never reached.
    monkeypatch.setattr(ds, "_membertools_token", lambda u: {"refresh_token": "R", "minted_at": "x"})
    calls = _patch_membertools(monkeypatch, refresh_result={"access_token": "AT-from-refresh"})
    tok = ds._membertools_access_token(_FakeMTClient(), 503991)
    assert tok == "AT-from-refresh"
    assert calls["refresh"] == 1 and calls["mint"] == 0


def test_membertools_mints_and_persists_when_no_stored_token(monkeypatch):
    # First sync after enroll (or no token yet): mint off the live session AND persist the new
    # 45-day refresh token so the next 45 days take the refresh path.
    monkeypatch.setattr(ds, "_membertools_token", lambda u: {})
    calls = _patch_membertools(
        monkeypatch, mint_result={"access_token": "AT-from-mint", "refresh_token": "NEW-R"})
    tok = ds._membertools_access_token(_FakeMTClient(), 503991)
    assert tok == "AT-from-mint"
    assert calls["mint"] == 1
    assert calls["saved"] == [(503991, "NEW-R")]  # persisted for next time


def test_membertools_expired_refresh_clears_and_remints(monkeypatch):
    # The 45-day wall: a RefreshTokenExpired clears the dead token and falls through to a fresh mint.
    monkeypatch.setattr(ds, "_membertools_token", lambda u: {"refresh_token": "OLD"})
    calls = _patch_membertools(
        monkeypatch, refresh_raises=True,
        mint_result={"access_token": "AT-remint", "refresh_token": "R2"})
    tok = ds._membertools_access_token(_FakeMTClient(), 503991)
    assert tok == "AT-remint"
    assert calls["cleared"] == [503991]
    assert calls["mint"] == 1 and calls["saved"] == [(503991, "R2")]


# --- E7: Member-Tools-primary resilience (the golden-flow sync, 2026-06-12) ----------------------
# The covenant-path CORE comes from the Member Tools /api/v5/sync 45-day token; the stake/ward
# STRUCTURE comes from that same payload (context_from_sync), so the daily sync completes with NO
# live LCR session (which dies within days). These prove the structure derivation + that sync_stake
# falls back to it when the LCR user_context is dead. Proven live: 503991 synced 93 members with a
# dead LCR session.


def test_context_from_sync_builds_stake_and_wards():
    from covenant_path.membertools_adapter import context_from_sync
    payload = {"units": [{
        "unitNumber": 503991, "name": "Raleigh North Carolina West Stake", "unitType": "STAKE",
        "childUnits": [
            {"unitNumber": 111, "name": "Green Level Ward", "unitType": "WARD"},
            {"unitNumber": 222, "name": "Highlands Ward", "unitType": "WARD"},
        ],
    }]}
    ctx = context_from_sync(payload)
    assert ctx.unit_number == 503991
    assert ctx.unit_name == "Raleigh North Carolina West Stake"
    assert [(u.unit_number, u.name, u.type) for u in ctx.child_units] == [
        (111, "Green Level Ward", "WARD"), (222, "Highlands Ward", "WARD")]
    assert ctx.positions == [] and ctx.roles == []  # LCR-only concepts; re-checked at enroll
    assert context_from_sync({"units": []}) is None


class _StopProbe(Exception):
    pass


def test_sync_stake_falls_back_to_payload_context_when_lcr_dead(monkeypatch):
    # When the delegated LCR session is dead, sync_stake uses the Member Tools-derived ctx_override
    # instead of raising — so the data sync still completes (the bulk data came from the token). We
    # stop at the FIRST DB write (upsert_stake) and assert the identity resolved from the override.
    import backend.db as dbmod
    from backend import sync as bsync
    from lcr_client.models import UnitRef, UserContext

    class _DeadClient:
        def user_context(self):
            raise RuntimeError("LCR returned 401. Session expired")

    override = UserContext(individual_id=None, active_position=None, unit_name="Test Stake",
                           unit_number=999001, positions=[], roles=[],
                           child_units=[UnitRef("Test Ward", 999002, "WARD")], raw={})
    captured = {}

    def _upsert_stake(conn, unit_number, name):
        captured["stake"] = (unit_number, name)
        raise _StopProbe()  # identity resolved → stop before the rest of the (DB-heavy) sync
    monkeypatch.setattr(dbmod, "upsert_stake", _upsert_stake)

    try:
        bsync.sync_stake(_DeadClient(), [], object(), ctx_override=override)
    except _StopProbe:
        pass
    except RuntimeError as e:
        if "401" in str(e):
            raise AssertionError("sync_stake raised on the dead LCR user_context instead of using "
                                 "the Member Tools ctx_override") from e
        raise
    assert captured.get("stake") == (999001, "Test Stake")  # identity came from the override


# --- E8: needs-reauth classification (2026-06-12 "Ken" fix) --------------------------------------
# A stake that can't sync headlessly because it has NO Member Tools 45-day token AND its LCR session
# either is dead OR is an OTP/passwordless (IDX) session that can't silently mint one (login_required)
# is in the EXPECTED "leader must re-authorize with a password" state — NOT an infra failure. It must
# NOT red-fail the daily workflow (which would go red every scheduled hour until the leader acts); it
# is flagged for the ops table + the app banner + a once-per-streak email. Real infra failures (an
# LCR/Member Tools outage, a code bug) are NOT re-auth cases and still red-fail.


@pytest.mark.parametrize("msg", [
    "silent authorize did not return a code (HTTP 302, error=login_required) — Okta session not live",
    "SSO did not complete — landed back on Okta",
    "no active credential for this stake",
    "Unexpected IDX state; remediations=['select-authenticator-authenticate']",
    "needs re-authorization",
])
def test_is_needs_reauth_true_for_reauth_signals(msg):
    assert ds._is_needs_reauth(RuntimeError(msg)) is True


@pytest.mark.parametrize("msg", [
    "/api/v5/sync 503 Service Unavailable",
    "LCR returned 500 on one-work",
    "connection reset by peer",
    "KeyError: 'covenantPathMembers'",
])
def test_is_needs_reauth_false_for_real_failures(msg):
    # An infrastructure outage or a bug is NOT a re-auth case — it must still red-fail the workflow.
    assert ds._is_needs_reauth(RuntimeError(msg)) is False


def test_flag_needs_reauth_does_not_raise_without_db(monkeypatch):
    # The flag is fully guarded: a DB hiccup must never turn a graceful "needs re-auth" into a crash
    # (the caller returns exit 0 on it). With no DB it logs and returns — never raises.
    import backend.db as dbmod
    monkeypatch.setattr(dbmod, "connect", lambda: (_ for _ in ()).throw(RuntimeError("no DB")))
    ds._flag_needs_reauth(999001, "login_required — Okta session not live")  # must not raise
