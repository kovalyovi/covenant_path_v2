"""Enrollment scenarios: consented store (g), re-enroll over a REVOKED credential — the
2026-06-10 regression (h) — and the plain-login can_enroll offer (i). Asserts against the
stub's stake_credentials rows, i.e. the 0041 RPC semantics end to end."""

from __future__ import annotations

from tests.e2e.seed_helpers import (
    PARTIAL_COVERAGE, STAKE_ID, WARD_LEADER, credential_row, stake_row,
)
from tests.mock_lcr.personas import PERSONAS, STAKE_NAME, STAKE_UNIT

PRESIDENT = PERSONAS["president.complete"]


def test_enroll_with_consent_stores_credential_and_kicks_audit(stack):
    res = stack.login(PRESIDENT.username, PRESIDENT.password, enroll=True)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    assert enroll["authorized"] is True
    assert enroll["stored"] is True
    assert enroll["complete"] is True
    assert enroll["unit_number"] == STAKE_UNIT

    stakes = stack.stub_rows("stakes")
    assert [s["unit_number"] for s in stakes] == [STAKE_UNIT]
    assert stakes[0]["name"] == STAKE_NAME

    creds = stack.stub_rows("stake_credentials")
    assert len(creds) == 1
    cred = creds[0]
    assert cred["stake_id"] == stakes[0]["id"]
    assert cred["revoked"] is False
    assert cred["coverage"]["complete"] is True
    assert cred["principal_email"] == PRESIDENT.email
    assert cred["access_rank"] == 1000
    assert cred["has_refresh_token"] is True  # the interaction-code exchange ran for enroll
    assert cred["credential_enc"].startswith('{"v": 2') or '"wrapped_key"' in cred["credential_enc"]

    audits = stack.audit_rows(outcome="enrolled", email=PRESIDENT.email)
    assert audits, "a consented enroll must audit outcome=enrolled"


def test_reenroll_after_revoke_unrevokes_and_clears_failure_state(stack):
    """The 2026-06-10 regression scenario: a REVOKED credential exists; a fresh consented
    enroll must un-revoke it and clear last_failed_at/last_error (0041 WHERE arm #1)."""
    stack.seed(
        stakes=[stake_row()],
        stake_credentials=[credential_row(
            principal_name=WARD_LEADER.name, principal_email=WARD_LEADER.email,
            access_rank=4, coverage=PARTIAL_COVERAGE, has_refresh_token=False,
            revoked=True, revoked_at="2026-06-09T08:00:00+00:00",
            last_failed_at="2026-06-09T07:00:00+00:00", last_error="LCR session expired",
            stale_notified_at="2026-06-09T07:30:00+00:00",
        )],
    )
    res = stack.login(PRESIDENT.username, PRESIDENT.password, enroll=True)
    assert res.status_code == 200, res.text
    assert res.json()["enroll"]["stored"] is True

    creds = stack.stub_rows("stake_credentials")
    assert len(creds) == 1, "re-enroll must update the existing row, not add a second"
    cred = creds[0]
    assert cred["stake_id"] == STAKE_ID, "the seeded stake row must be reused (upsert by unit)"
    assert cred["revoked"] is False
    assert cred["revoked_at"] is None
    assert cred["last_failed_at"] is None
    assert cred["last_error"] is None
    assert cred["stale_notified_at"] is None
    assert cred["principal_email"] == PRESIDENT.email
    assert cred["access_rank"] == 1000
    assert cred["coverage"]["complete"] is True


def test_plain_login_offers_can_enroll_when_stake_has_no_credential(stack):
    res = stack.login(PRESIDENT.username, PRESIDENT.password)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    assert enroll["authorized"] is True
    assert enroll["can_enroll"] is True, "no usable credential -> offer to set up sync"
    assert enroll["stored"] is False
    assert stack.stub_rows("stake_credentials") == [], "a plain login must never store"
