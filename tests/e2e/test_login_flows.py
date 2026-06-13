"""Password-login scenarios against the REAL broker (mock Okta/LCR + Supabase stub).

Covers spec scenarios (a) happy path, (b) bad password, (c) LCR 5xx outage after a good
password, (d) the no-calling gate, and (l)'s no-raw-IDX-leakage guarantee for the locked
account. All personas/units are fictional (Testvale / example.org)."""

from __future__ import annotations

from tests.mock_lcr.personas import PERSONAS, STAKE_NAME, STAKE_UNIT

PRESIDENT = PERSONAS["president.complete"]
WARD_LEADER = PERSONAS["wardleader.partial"]
NOCALLING = PERSONAS["member.nocalling"]


def test_password_login_happy_path_mints_session_and_audits(stack):
    res = stack.login(PRESIDENT.username, PRESIDENT.password)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["identity_name"] == PRESIDENT.name

    # the minted OTP round-trips into a real (stub) Supabase session, like the app does
    session = body["session"]
    assert session["email"] == PRESIDENT.email
    verified = stack.verify_minted_session(session)
    assert verified["access_token"]
    assert verified["user"]["email"] == PRESIDENT.email

    enroll = body["enroll"]
    assert enroll["authorized"] is True
    assert enroll["unit_number"] == STAKE_UNIT
    assert enroll["stake"] == STAKE_NAME
    assert body["timing"]["lane"] == "full"

    audits = stack.audit_rows(outcome="allowed", email=PRESIDENT.email)
    assert audits, "expected a login_audit row for the allowed login"
    assert audits[-1]["phase"] == "full"


def test_ward_leader_partial_access_reports_missing_with_who_to_ask(stack):
    res = stack.login(WARD_LEADER.username, WARD_LEADER.password)
    assert res.status_code == 200, res.text
    enroll = res.json()["enroll"]
    assert enroll["authorized"] is True       # some access -> in (rank > 0)
    assert enroll["complete"] is False        # ...but not the full covenant-path dataset
    # A WARD-level leader (Bishop) is NEVER offered enrollment — daily sync is a STAKE concept, and a
    # ward leader's Member Tools token would point at the parent stake (the Green Level Ward incident,
    # 2026-06-13). They see their unit via their provisioned ward_leader role; no setup.
    assert enroll["can_enroll"] is False
    assert enroll["ward_scoped"] is True
    # ...but the coverage / who-to-ask is still reported (informational).
    missing = {m["feature"]: m for m in enroll["missing"]}
    temple = missing.get("Temple recommend status")
    assert temple, f"temple recommend must be missing for a bishop; got {sorted(missing)}"
    assert "Stake President" in temple["granted_by"]  # the who-to-ask names resolve
    assert "Stake Clerk" in temple["granted_by"]


def test_bad_password_is_401_friendly_and_audited_with_raw_cause(stack):
    res = stack.login("nobody.fictional", "not-the-password")
    assert res.status_code == 401
    detail = res.json()["detail"]
    assert "incorrect" in detail.lower()
    assert "IDX" not in detail  # the raw Okta error must never reach the member

    audits = stack.audit_rows(outcome="okta_failed", email="nobody.fictional")
    assert audits, "okta-stage failures must be visible in login_audit"
    row = audits[-1]
    assert "Authentication failed" in (row["error"] or "")
    assert row["phase"] == "okta:bad_credentials"


def test_lcr_5xx_outage_after_good_password_is_503_with_root_cause_audit(stack):
    stack.scenario("lcr_5xx")
    res = stack.login(PRESIDENT.username, PRESIDENT.password)  # fresh user: no cached identity
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "isn't about your account" in detail
    assert "LCR" in detail
    assert "IDX" not in detail

    audits = stack.audit_rows(outcome="lcr_identity_failed")
    assert audits, "identity-leg failures must be audited"
    row = audits[-1]
    assert "502" in (row["error"] or ""), "audit must keep the raw root cause (auth/me 502)"
    assert row["phase"] == "identity:lcr_5xx"


def test_no_calling_member_is_blocked_in_the_login_response(stack):
    res = stack.login(NOCALLING.username, NOCALLING.password)
    assert res.status_code == 200, res.text
    body = res.json()
    # The broker still answers ok + session (RLS is the data gate) but the synchronous
    # calling gate must say authorized=false IN THE RESPONSE so the client refuses adoption.
    assert body["status"] == "ok"
    assert body["session"]["email"] == NOCALLING.email
    assert body["enroll"]["authorized"] is False
    assert body["enroll"]["stored"] is False

    audits = stack.audit_rows(outcome="blocked", email=NOCALLING.email)
    assert audits, "the gate decision must be audited"
    assert audits[-1]["phase"] in ("gate-sync", "gate", "gate-cached")


def test_locked_account_message_is_friendly_with_no_idx_leakage(stack):
    res = stack.login("user.locked", "any-password")
    assert res.status_code == 401
    detail = res.json()["detail"]
    assert "locked" in detail.lower()
    assert "churchofjesuschrist.org" in detail  # tells the member where to unlock
    assert "IDX" not in detail and "IDX step" not in detail

    audits = stack.audit_rows(outcome="okta_failed", email="user.locked")
    assert audits and "locked" in (audits[-1]["error"] or "").lower()
    assert audits[-1]["phase"] == "okta:account_locked"
