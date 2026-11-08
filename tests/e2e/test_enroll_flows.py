"""Enrollment scenarios: consented store (g), re-enroll over a REVOKED credential — the
2026-06-10 regression (h) — and the plain-login can_enroll offer (i). Asserts against the
stub's stake_credentials rows, i.e. the 0041 RPC semantics end to end.
(The passwordless Church email-code lane was removed 2026-06-12 — ADR-011 — so enrollment is
username+password only; see tests/test_web_session.py for the token-minting capture flow.)"""

from __future__ import annotations

from tests.e2e.seed_helpers import (
    COMPLETE_COVERAGE, PARTIAL_COVERAGE, STAKE_ID, WARD_LEADER, credential_row, stake_row,
)
from tests.mock_lcr.personas import PERSONAS, STAKE_NAME, STAKE_UNIT

PRESIDENT = PERSONAS["president.complete"]
CLERK = PERSONAS["assistantclerk.stake"]


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
    """The 2026-06-10 regression scenario: a REVOKED credential exists for THIS leader; a fresh
    consented enroll must un-revoke it and clear last_failed_at/last_error (0068 per-email upsert —
    the old 0041 WHERE arm #1, now scoped to the leader's own row)."""
    stack.seed(
        stakes=[stake_row()],
        stake_credentials=[credential_row(
            principal_name=PRESIDENT.name, principal_email=PRESIDENT.email,
            access_rank=1000, coverage={"complete": True}, has_refresh_token=True,
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


def test_enroll_over_other_leaders_revoked_row_keeps_it_as_history(stack):
    """0068: a REVOKED credential belonging to ANOTHER leader is dead history, not something a new
    enroll "takes over" — the new leader gets their own row, and the revoked row stays (revoked).
    The stake ends up with one live credential: the enroller's, effective at once."""
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
    assert len(creds) == 2, "the other leader's revoked row is retained, not replaced"
    live = [c for c in creds if not c.get("revoked")]
    assert len(live) == 1 and live[0]["principal_email"] == PRESIDENT.email
    assert live[0]["revoked"] is False
    assert live[0]["last_failed_at"] is None
    assert live[0]["last_error"] is None
    dead = [c for c in creds if c.get("revoked")]
    assert len(dead) == 1 and dead[0]["principal_email"] == WARD_LEADER.email
    assert live[0]["access_rank"] == 1000
    assert live[0]["coverage"]["complete"] is True


def test_plain_login_offers_can_enroll_when_stake_has_no_credential(stack):
    res = stack.login(PRESIDENT.username, PRESIDENT.password)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    assert enroll["authorized"] is True
    assert enroll["can_enroll"] is True, "no usable credential -> offer to set up sync"
    assert enroll["stored"] is False
    assert stack.stub_rows("stake_credentials") == [], "a plain login must never store"


def test_narrower_reauth_stored_as_backup(stack):
    """D82 / 2026-11-08 live incident: the stake's effective credential belongs to the
    president (rank 1000, complete); a stake assistant clerk re-authorizes with a strictly
    weaker session (rank 4, partial). The clerk's credential must be STORED as a standby —
    never refused — the sync keeps running on the president, and the response names the
    effective provider so the dialog can say so."""
    stack.seed(
        stakes=[stake_row()],
        stake_credentials=[credential_row(
            principal_name=PRESIDENT.name, principal_email=PRESIDENT.email,
            access_rank=1000, coverage=COMPLETE_COVERAGE, has_refresh_token=True,
        )],
    )
    res = stack.login(CLERK.username, CLERK.password, enroll=True)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    assert enroll["authorized"] is True
    assert enroll["stored"] is True
    assert enroll["stored_as_backup"] is True
    assert enroll["is_effective"] is False
    assert enroll["effective_provider"] == PRESIDENT.name

    creds = stack.stub_rows("stake_credentials")
    assert len(creds) == 2, "the clerk gets their own row; the president's row stays"
    live = [c for c in creds if not c.get("revoked")]
    assert len(live) == 2
    effective = max(live, key=lambda c: c["access_rank"])
    assert effective["principal_email"] == PRESIDENT.email, \
        "the sync still runs on the president's broader credential"
    clerk_rows = [c for c in live if c["principal_email"] == CLERK.email]
    assert len(clerk_rows) == 1
    assert clerk_rows[0]["access_rank"] == 4
    assert clerk_rows[0]["coverage"]["complete"] is False
    history = stack.stub_rows("stake_credential_history")
    assert any(h["action"] == "stored_backup" for h in history)


def test_undetermined_access_enroll_surfaces_error(stack):
    """2026-11-08 re-auth incident: LCR returns no callings for the session (platform
    positions empty) while the classic context still shows the calling — the eval lands
    'undetermined' (authorized=None). A consented enroll must then carry a non-empty error
    so the dialog says WHY nothing was stored, never a bare 'could not be set up'."""
    stack.scenario("empty_positions")
    res = stack.login(PRESIDENT.username, PRESIDENT.password, enroll=True)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    assert enroll["authorized"] is None
    assert enroll["stored"] is False
    assert isinstance(enroll.get("error"), str) and enroll["error"], \
        "a consented enroll that stores nothing must say why"
    assert "callings" in enroll["error"]
    assert stack.stub_rows("stake_credentials") == [], "nothing stored on undetermined access"
    audits = stack.audit_rows(outcome="undetermined", email=PRESIDENT.email)
    assert audits, "the undetermined eval must still be audited"


def test_enroll_rpc_failure_surfaces_error(stack):
    """A failing enroll RPC must surface its reason end to end: the response carries a
    non-empty `error`, nothing is stored, and the dialog can say why instead of a bare
    'could not be set up'."""
    stack.stub_control(fail_rpc="enroll_stake_credential")
    res = stack.login(PRESIDENT.username, PRESIDENT.password, enroll=True)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    # NB: the exception path returns {"error": ...} with no "stored" key at all — .get, not [].
    assert enroll.get("stored") is not True
    assert isinstance(enroll.get("error"), str) and enroll["error"]
    assert "enroll RPC failed" in enroll["error"]
    assert stack.stub_rows("stake_credentials") == []
