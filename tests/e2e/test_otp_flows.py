"""Passwordless (emailed-code) Church login — OTP as the PRIMARY factor, no password.

Two realities, both proven end to end through the REAL broker:
  - `leader.passwordless` models an account whose Okta policy lists Email on the PRIMARY
    authenticator menu: /auth/otp/start sends the code, /auth/otp/verify completes, and a
    consented enroll STORES the stake credential (the same 0041 RPC semantics the password
    enroll tests assert).
  - Every other account (the Church default — password-first) must get an HONEST, actionable
    401 from /auth/otp/start. The original bug this suite was written against: the UI said
    "a code was just sent to your email" while no code was ever sent (and verify always died
    on a broker ImportError).
"""

from __future__ import annotations

from tests.mock_lcr.personas import MFA_CODE, PERSONAS, STAKE_UNIT

PASSWORDLESS = PERSONAS["leader.passwordless"]
PRESIDENT = PERSONAS["president.complete"]
MFA_MEMBER = PERSONAS["member.mfa"]


def test_otp_enroll_full_flow_stores_credential(stack):
    """start -> code -> verify(enroll=True): authorized, credential stored, session mintable."""
    start = stack.otp_start(PASSWORDLESS.username, enroll=True)
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["status"] == "code_sent"
    assert body.get("sent_to"), "the client shows where the code went"

    res = stack.otp_verify(PASSWORDLESS.username, MFA_CODE, enroll=True)
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "ok"
    assert done["session"]["email"] == PASSWORDLESS.email
    enroll = done["enroll"]
    assert enroll["authorized"] is True
    assert enroll["stored"] is True
    assert enroll["unit_number"] == STAKE_UNIT

    # The minted OTP is adoptable exactly the way the apps do it (verifyOtp -> session).
    session = stack.verify_minted_session(done["session"])
    assert session.get("access_token")

    creds = stack.stub_rows("stake_credentials")
    assert len(creds) == 1
    cred = creds[0]
    assert cred["principal_email"] == PASSWORDLESS.email
    assert cred["revoked"] is False
    assert cred["coverage"]["complete"] is True
    assert cred["access_rank"] == 1000  # Stake President — same access as the password enroll

    audits = stack.audit_rows(outcome="enrolled", email=PASSWORDLESS.email)
    assert audits, "a consented OTP enroll must audit outcome=enrolled"


def test_otp_plain_login_does_not_store(stack):
    """Without consent (enroll=False) an OTP login authorizes but must never store a credential."""
    assert stack.otp_start(PASSWORDLESS.username).status_code == 200
    res = stack.otp_verify(PASSWORDLESS.username, MFA_CODE)
    assert res.status_code == 200, res.text
    assert res.json()["enroll"]["stored"] is False
    assert stack.stub_rows("stake_credentials") == [], "a plain OTP login must never store"


def test_otp_wrong_code_then_correct_code_survives(stack):
    """A rejected code answers a friendly 401 and the pending login SURVIVES for the retry."""
    assert stack.otp_start(PASSWORDLESS.username).status_code == 200

    wrong = stack.otp_verify(PASSWORDLESS.username, "000000")
    assert wrong.status_code == 401
    detail = wrong.json()["detail"]
    assert "code wasn't accepted" in detail or "Invalid" in detail
    assert "IDX" not in detail and "{" not in detail  # friendly text, never raw protocol JSON

    ok = stack.otp_verify(PASSWORDLESS.username, MFA_CODE)
    assert ok.status_code == 200, ok.text
    assert ok.json()["session"]["email"] == PASSWORDLESS.email


def test_otp_start_password_first_account_gets_honest_error(stack):
    """The Church default, in BOTH post-identify shapes: a direct password challenge
    (president.complete) and a Password-only select menu (member.mfa). otp/start must say
    passwordless isn't available — never a phantom code_sent — and audit the attempt."""
    for username in (PRESIDENT.username, MFA_MEMBER.username):
        res = stack.otp_start(username, enroll=True)
        assert res.status_code == 401, f"{username}: {res.text}"
        detail = res.json()["detail"]
        assert "password" in detail.lower(), detail
        assert "code_sent" not in res.text

    audits = stack.audit_rows(outcome="otp_start_failed")
    assert len(audits) >= 2, "both refused starts must be visible in login_audit"
    assert any(a.get("email") == PRESIDENT.username for a in audits)
    assert any("primary factors offered" in (a.get("error") or "") for a in audits)


def test_otp_verify_without_start_is_expired(stack):
    """verify with no pending start (or after TTL) answers the standard expired message."""
    res = stack.otp_verify("nobody.started@example.org", MFA_CODE)
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_passwordless_account_can_still_use_password_lane(stack):
    """The same passwordless-enabled account signing in the classic way (username+password)
    still works — the primary menu's Password option keeps the old lane intact."""
    res = stack.login(PASSWORDLESS.username, PASSWORDLESS.password)
    assert res.status_code == 200, res.text
    assert res.json()["session"]["email"] == PASSWORDLESS.email
