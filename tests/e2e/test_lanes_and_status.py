"""The cached zero-LCR fast lane (j) and /auth/enrollment-status states + sync-now (k).

The cached-lane test runs with scenario lcr_5xx ON: the whole point of church_identities
(ADR-009) is that a routine repeat sign-in no longer depends on LCR weather — so the lane
must answer "cached" while LCR is hard-down, and the LCR mock's /api/user-context hit
counter must stay at zero."""

from __future__ import annotations

from tests.e2e.seed_helpers import (
    PRESIDENT, STAKE_ID, credential_row, identity_row, role_row, stake_row,
)


def test_cached_fast_lane_answers_without_touching_lcr(stack):
    stack.seed(
        stakes=[stake_row()],
        stake_credentials=[credential_row()],            # ACTIVE credential on file
        church_identities=[identity_row(has_calling=True)],
    )
    stack.scenario("lcr_5xx")  # LCR down — the cached lane must not care

    res = stack.login(PRESIDENT.username, PRESIDENT.password)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["timing"]["lane"] == "cached"
    enroll = body["enroll"]
    assert enroll["authorized"] is True
    assert enroll.get("fast") is True

    hits = stack.mock_state()["hits"]
    assert hits.get("/api/user-context", 0) == 0, \
        f"cached lane must be zero-LCR for user-context; hits={hits}"

    audits = stack.audit_rows(outcome="allowed", email=PRESIDENT.email)
    assert audits and audits[-1]["phase"] == "fast-lane"


def _status(stack, token: str):
    r = stack.http.get(f"{stack.broker_base}/auth/enrollment-status",
                       headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_enrollment_status_states_and_sync_now_conflict_on_revoked(stack):
    token = stack.user_token(PRESIDENT.email)

    # state: none — role + stake exist, no credential at all
    stack.seed(stakes=[stake_row()], user_roles=[role_row(PRESIDENT.email)],
               stake_credentials=[], members=[])
    none_status = _status(stack, token)
    assert none_status["stake_id"] == STAKE_ID
    assert none_status["credential"]["state"] == "none"
    assert none_status["member_count"] == 0 and none_status["has_data"] is False

    # state: active — credential present, healthy
    stack.seed(stake_credentials=[credential_row()])
    active_status = _status(stack, token)
    assert active_status["credential"]["state"] == "active"
    assert active_status["credential"]["is_provider"] is True
    assert active_status["credential"]["complete"] is True

    # state: stale — the last delegated sync failed (last_failed_at set)
    stack.seed(stake_credentials=[credential_row(
        last_failed_at="2026-06-09T12:00:00+00:00", last_error="LCR session expired")])
    stale_status = _status(stack, token)
    assert stale_status["credential"]["state"] == "stale"
    assert stale_status["credential"]["last_error"] == "LCR session expired"

    # state: revoked — and "Sync now" must be refused with 409, not silently dispatched
    stack.seed(stake_credentials=[credential_row(
        revoked=True, revoked_at="2026-06-10T00:00:00+00:00")])
    revoked_status = _status(stack, token)
    assert revoked_status["credential"]["state"] == "revoked"

    sync = stack.http.post(f"{stack.broker_base}/auth/sync-now",
                           headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert sync.status_code == 409
    assert "revoked" in sync.json()["detail"].lower()
