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


def test_membertools_rotation_repersists_new_refresh_token(monkeypatch):
    # #0 fix F2: if a renew ever returns a ROTATED refresh token, persist it (the old one is now dead)
    # — without it the NEXT run gets invalid_grant and falsely flags needs-reauth. No mint: the renew
    # succeeded. (Fails pre-fix: the old code read only .access_token and never re-saved.)
    monkeypatch.setattr(ds, "_membertools_token", lambda u: {"refresh_token": "R"})
    calls = _patch_membertools(
        monkeypatch, refresh_result={"access_token": "AT", "refresh_token": "R-ROTATED"})
    tok = ds._membertools_access_token(_FakeMTClient(), 503991)
    assert tok == "AT"
    assert calls["mint"] == 0
    assert calls["saved"] == [(503991, "R-ROTATED")]


def test_membertools_same_refresh_token_not_repersisted(monkeypatch):
    # The normal (rotation-off) case: the same refresh token comes back → no needless re-write.
    monkeypatch.setattr(ds, "_membertools_token", lambda u: {"refresh_token": "R"})
    calls = _patch_membertools(
        monkeypatch, refresh_result={"access_token": "AT", "refresh_token": "R"})
    tok = ds._membertools_access_token(_FakeMTClient(), 503991)
    assert tok == "AT"
    assert calls["mint"] == 0 and calls["saved"] == []


def test_membertools_token_store_db_error_raises_not_empty(monkeypatch):
    # #0 fix F5: a DB read FAILURE must NOT masquerade as 'no token' (which would mint off a possibly-
    # dead Okta session and, on failure, falsely flag needs-reauth). With nothing in the file store
    # either, _membertools_token RAISES so the caller skips and retries next run.
    from backend import db
    from lcr_client import token_store

    def _raise_db(*a, **k):
        raise RuntimeError("DB pooler unreachable")

    monkeypatch.setattr(db, "connect", _raise_db)
    monkeypatch.setattr(token_store, "get_membertools_token", lambda u: None)
    with pytest.raises(ds._TokenStoreUnavailable):
        ds._membertools_token(503991)


def test_membertools_token_db_error_falls_back_to_file_store(monkeypatch):
    # The dev fallback stays intact: a DB read failure with a token still in the local file store uses
    # it (no raise) — only an UNREADABLE store with nothing anywhere is fatal.
    from backend import db
    from lcr_client import token_store

    def _raise_db(*a, **k):
        raise RuntimeError("DB pooler unreachable")

    monkeypatch.setattr(db, "connect", _raise_db)
    monkeypatch.setattr(token_store, "get_membertools_token", lambda u: {"refresh_token": "FILE-R"})
    assert ds._membertools_token(503991) == {"refresh_token": "FILE-R"}


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


# --- E9: credential-scope guard — a ward credential can NEVER sync a stake (Green Level Ward, -----
#     2026-06-13). A WARD/BRANCH leader's Member Tools token returns the PARENT stake as its org root
#     while exposing covenant-path data for only their ward, so ctx_override names the stake. Without
#     the guard, sync_stake upserts that one ward's handful of members onto the WHOLE stake and
#     reconciles every other ward's members away (Raleigh 93 -> 7, all "Green Level Ward"). The guard
#     fires when the credential's REGISTERED unit is a CHILD of the Member Tools root — BEFORE any write.


def _raleigh_override():
    from lcr_client.models import UnitRef, UserContext
    return UserContext(individual_id=None, active_position=None,
                       unit_name="Raleigh North Carolina West Stake", unit_number=503991,
                       positions=[], roles=[],
                       child_units=[UnitRef("Green Level Ward", 1102966, "WARD"),
                                    UnitRef("Cary 1st Ward", 127833, "WARD")], raw={})


class _DeadLCRClient:
    def user_context(self):
        raise RuntimeError("LCR returned 401. Session expired")


class _LiveClient:
    """A client whose LCR session is ALIVE and resolves to a given stake context — the case the
    cross-stake DATA guard must police (a live, correctly-registered session paired with a Member
    Tools token that returned a DIFFERENT stake's members)."""
    def __init__(self, ctx):
        self._ctx = ctx

    def user_context(self):
        return self._ctx


def test_ward_credential_refuses_to_sync_a_stake(monkeypatch):
    # Jesse (WML): credential registered for ward 1102966; the MT org root is the parent stake 503991.
    # Must raise CredentialScopeMismatch and NEVER reach a DB write.
    import backend.db as dbmod
    from backend import sync as bsync
    monkeypatch.setattr(dbmod, "upsert_stake",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))
    with pytest.raises(bsync.CredentialScopeMismatch) as ei:
        bsync.sync_stake(_DeadLCRClient(), [{"person_uuid": "p1"}], object(),
                         ctx_override=_raleigh_override(), expected_stake_unit=1102966)
    assert ei.value.expected_unit == 1102966 and ei.value.stake_unit == 503991


def test_stake_credential_passes_the_scope_guard(monkeypatch):
    # ILYA: credential unit == the MT root 503991 -> the guard must NOT fire; it proceeds to the
    # first DB write (which we intercept to prove the guard let it through).
    import backend.db as dbmod
    from backend import sync as bsync
    monkeypatch.setattr(dbmod, "upsert_stake", lambda *a, **k: (_ for _ in ()).throw(_StopProbe()))
    with pytest.raises(_StopProbe):
        bsync.sync_stake(_DeadLCRClient(), [], object(),
                         ctx_override=_raleigh_override(), expected_stake_unit=503991)


def test_scope_guard_inert_without_expected_unit(monkeypatch):
    # The operator's own self-sync passes no expected unit -> the guard never fires (it can't, and the
    # operator's MT root IS their stake anyway).
    import backend.db as dbmod
    from backend import sync as bsync
    monkeypatch.setattr(dbmod, "upsert_stake", lambda *a, **k: (_ for _ in ()).throw(_StopProbe()))
    with pytest.raises(_StopProbe):
        bsync.sync_stake(_DeadLCRClient(), [], object(),
                         ctx_override=_raleigh_override(), expected_stake_unit=None)


def test_cross_stake_credential_refuses_to_sync(monkeypatch):
    # ilia (2026-06-25): the "Raleigh" stake_credentials row holds the operator's OWN token, whose
    # real Member Tools stake is Springville Utah (462373) — an ENTIRELY DIFFERENT stake, NOT a ward
    # beneath Raleigh (503991). The daily Raleigh job (expected_stake_unit=503991) pulls Springville's
    # members; the guard must REFUSE so they are never stamped with Raleigh's stake_id. Regresses the
    # original guard, which only caught wards beneath the MT root and silently re-leaked Springville
    # into Raleigh (34 Utah members surfaced in a "Raleigh" leader's directory).
    import backend.db as dbmod
    from backend import sync as bsync
    from lcr_client.models import UnitRef, UserContext
    springville = UserContext(
        individual_id=None, active_position=None, unit_name="Springville Utah West Stake",
        unit_number=462373, positions=[], roles=[],
        child_units=[UnitRef("Springville  9th Ward", 427098, "WARD"),
                     UnitRef("Grasslands 7th Ward (Spanish)", 2161265, "WARD")], raw={})
    monkeypatch.setattr(dbmod, "upsert_stake",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))
    with pytest.raises(bsync.CredentialScopeMismatch) as ei:
        bsync.sync_stake(_DeadLCRClient(), [{"person_uuid": "p1"}], object(),
                         ctx_override=springville, expected_stake_unit=503991)
    assert ei.value.expected_unit == 503991 and ei.value.stake_unit == 462373


# --- E15: cross-stake DATA guard — the member ROWS must belong to the stake we write them under -----
#     (Springville-under-Raleigh recurrence, 2026-06-27). The 2026-06-25 guard above compares only the
#     resolved IDENTITY (ctx_override's `units` tree, else the live session) vs the registered stake. It
#     has a hole: when the Member Tools payload carries NO `units` tree, ctx_override is None and the
#     guard falls back to the LIVE session's stake. For an operator who is a leader in the registered
#     stake (Raleigh) but whose Member Tools token returns their HOME stake's roster (Springville),
#     identity == registered, the guard passes, and 34 Springville members get stamped under Raleigh.
#     The DATA guard keys off the MEMBERS' OWN units, so a missing unit_context can't blind it.


def _raleigh_live_ctx():
    from lcr_client.models import UnitRef, UserContext
    return UserContext(individual_id=None, active_position=None,
                       unit_name="Raleigh North Carolina West Stake", unit_number=503991,
                       positions=[], roles=[],
                       child_units=[UnitRef("Raleigh 1st Ward", 44911, "WARD"),
                                    UnitRef("Cary 1st Ward", 127833, "WARD")], raw={})


def test_cross_stake_members_refused_when_unit_context_absent(monkeypatch):
    # The hole that re-leaked Springville into Raleigh on 2026-06-27: a LIVE Raleigh session (the
    # operator is a Raleigh stake clerk) + a Member Tools token that returned SPRINGVILLE's roster, with
    # NO `units` tree in the payload (ctx_override=None). The id-guard sees identity(503991)==expected
    # and passes; the DATA guard must see the members' units are Springville's and REFUSE before any
    # write. FAILS against the pre-fix code (it reaches upsert_stake and raises AssertionError, not
    # CredentialScopeMismatch).
    import backend.db as dbmod
    from backend import sync as bsync
    springville_members = [
        {"person_uuid": "p1", "unit_number": 427098, "unit": "Springville  9th Ward"},
        {"person_uuid": "p2", "unit_number": 2161265, "unit": "Grasslands 7th Ward (Spanish)"}]
    monkeypatch.setattr(dbmod, "upsert_stake",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))
    with pytest.raises(bsync.CredentialScopeMismatch) as ei:
        bsync.sync_stake(_LiveClient(_raleigh_live_ctx()), springville_members, object(),
                         ctx_override=None, expected_stake_unit=503991)
    assert ei.value.expected_unit == 503991  # refusal is labeled with the registered stake


def test_cross_stake_members_refused_by_name_when_no_unit_numbers(monkeypatch):
    # Same hole, but the member rows carry only unit NAMES (no numbers) — the guard falls back to
    # normalized-name comparison and still refuses wholly-foreign data.
    import backend.db as dbmod
    from backend import sync as bsync
    springville_members = [{"person_uuid": "p1", "unit": "Springville  9th Ward"},
                           {"person_uuid": "p2", "unit": "Grasslands 7th Ward (Spanish)"}]
    monkeypatch.setattr(dbmod, "upsert_stake",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))
    with pytest.raises(bsync.CredentialScopeMismatch):
        bsync.sync_stake(_LiveClient(_raleigh_live_ctx()), springville_members, object(),
                         ctx_override=None, expected_stake_unit=503991)


def test_orphan_members_do_not_trip_cross_stake_guard(monkeypatch):
    # False-positive guard: a few moved-ward orphans must NOT look like a foreign roster. As long as
    # ANY member belongs to one of this stake's own units, the DATA guard stands down (overlap > 0) and
    # the sync proceeds to the first DB write (intercepted to prove it was let through).
    import backend.db as dbmod
    from backend import sync as bsync
    members = [{"person_uuid": "a", "unit_number": 44911, "unit": "Raleigh 1st Ward"},
               {"person_uuid": "b", "unit_number": 127833, "unit": "Cary 1st Ward"},
               {"person_uuid": "c", "unit_number": 999999, "unit": "A Stray Orphan Ward"}]
    monkeypatch.setattr(dbmod, "upsert_stake", lambda *a, **k: (_ for _ in ()).throw(_StopProbe()))
    with pytest.raises(_StopProbe):
        bsync.sync_stake(_LiveClient(_raleigh_live_ctx()), members, object(),
                         ctx_override=None, expected_stake_unit=503991)


def test_matching_members_pass_cross_stake_guard(monkeypatch):
    # The healthy steady state: the member rows belong to this stake's units -> the guard lets the sync
    # through. Proves the new guard adds no false refusal to a normal sync.
    import backend.db as dbmod
    from backend import sync as bsync
    members = [{"person_uuid": "a", "unit_number": 44911, "unit": "Raleigh 1st Ward"},
               {"person_uuid": "b", "unit_number": 127833, "unit": "Cary 1st Ward"}]
    monkeypatch.setattr(dbmod, "upsert_stake", lambda *a, **k: (_ for _ in ()).throw(_StopProbe()))
    with pytest.raises(_StopProbe):
        bsync.sync_stake(_LiveClient(_raleigh_live_ctx()), members, object(),
                         ctx_override=None, expected_stake_unit=503991)


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
    # A 5xx at the Member Tools /authorize is a TRANSIENT OUTAGE, not a dead session — membertools.py
    # now phrases it without "Okta session not live" so it does NOT match the re-auth signals (it must
    # red-fail + alert the operator, never silently ask the leader to re-authorize).
    "Member Tools /authorize returned HTTP 500 — transient outage; retry",
    "Member Tools /authorize returned HTTP 503 — transient outage; retry",
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
