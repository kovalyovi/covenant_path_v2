"""MFA scenarios: shape A (factor menu) and shape B (straight code challenge), including a
wrong-code-then-correct retry (the pending IDX state must survive the failure) and the
friendly-message guarantee (spec scenarios e, f, l). The webauthn persona replays the
2026-06-11 incident end-to-end: a security key on the menu (must be filtered), then a wrong
code whose 401 carries the message at the FIELD level (must still classify friendly)."""

from __future__ import annotations

import time

from tests.mock_lcr.personas import MFA_CODE, PERSONAS

MFA_A = PERSONAS["member.mfa"]
MFA_B = PERSONAS["member.mfab"]
MFA_W = PERSONAS["member.mfaw"]


def test_mfa_shape_a_two_factors_select_then_wrong_then_correct_code(stack):
    res = stack.login(MFA_A.username, MFA_A.password)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "mfa_required"
    login_id = body["login_id"]
    factors = body["factors"]
    assert len(factors) == 2
    labels = {f["label"] for f in factors}
    assert labels == {"Email", "Phone"}
    # the wire shape stays id/label/method — no internal fields leak to the client
    assert all(set(f) == {"id", "label", "method"} for f in factors)
    email_factor = next(f for f in factors if f["label"] == "Email")
    phone_factor = next(f for f in factors if f["label"] == "Phone")
    assert email_factor["method"] == "email"
    assert phone_factor["method"] == "sms"  # nested methodType defaulted to the first option

    sel = stack.mfa_select(login_id, email_factor["id"])
    assert sel.status_code == 200 and sel.json()["status"] == "code_sent"

    wrong = stack.mfa_verify(login_id, "000000")
    assert wrong.status_code == 401
    detail = wrong.json()["detail"]
    assert "code wasn't accepted" in detail or "Invalid" in detail
    assert "IDX" not in detail

    # the pending login must survive a wrong code — the corrected code completes
    ok = stack.mfa_verify(login_id, MFA_CODE)
    assert ok.status_code == 200, ok.text
    done = ok.json()
    assert done["status"] == "ok"
    assert done["session"]["email"] == MFA_A.email
    assert done["enroll"]["authorized"] is True  # ward clerk holds a real calling

    audits = stack.audit_rows(outcome="mfa_failed")
    assert audits and "Invalid Passcode" in (audits[-1]["error"] or "")
    # phase now also names the factor type; the row carries the USERNAME (was who="")
    assert audits[-1]["phase"] == "okta:mfa_bad_code:okta_email"
    assert audits[-1]["email"] == MFA_A.username


def test_mfa_webauthn_filtered_and_field_level_invalid_code(stack):
    """The 2026-06-11 incident, replayed end-to-end through the REAL broker:
    1. the account's menu has a security key alongside Email/Phone → the response offers ONLY
       the code factors (the webauthn dead-end is no longer reachable);
    2. an mfa_pending audit row attributes the hand-off and names offered + dropped factors;
    3. a wrong code answers 401 with the message at the FIELD level (no top-level messages) →
       the member sees friendly retry text, never raw IDX JSON;
    4. the pending login survives — the corrected code completes."""
    res = stack.login(MFA_W.username, MFA_W.password)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "mfa_required"
    labels = {f["label"] for f in body["factors"]}
    assert labels == {"Email", "Phone"}  # the security key is filtered, not offered

    # the mfa_pending audit is written off the response path (background pool) — poll briefly
    pending: list[dict] = []
    for _ in range(20):
        pending = stack.audit_rows(outcome="mfa_pending", email=MFA_W.username)
        if pending:
            break
        time.sleep(0.25)
    assert pending, "mfa_required must leave an attributed audit row"
    assert "webauthn" in (pending[-1]["error"] or "")  # the dropped factor is named

    login_id = body["login_id"]
    phone = next(f for f in body["factors"] if f["label"] == "Phone")
    sel = stack.mfa_select(login_id, phone["id"])
    assert sel.status_code == 200 and sel.json()["status"] == "code_sent"

    wrong = stack.mfa_verify(login_id, "999999")
    assert wrong.status_code == 401
    detail = wrong.json()["detail"]
    assert "code wasn't accepted" in detail
    assert "{" not in detail and "IDX" not in detail  # the raw-JSON wall is gone

    audits = stack.audit_rows(outcome="mfa_failed", email=MFA_W.username)
    assert audits and audits[-1]["phase"] == "okta:mfa_bad_code:phone_number"

    ok = stack.mfa_verify(login_id, MFA_CODE)
    assert ok.status_code == 200, ok.text
    assert ok.json()["session"]["email"] == MFA_W.email


def test_mfa_shape_b_immediate_challenge_verify_completes(stack):
    res = stack.login(MFA_B.username, MFA_B.password)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "mfa_required"
    # shape B surfaces one generic pending factor so the app shows the code field
    assert body["factors"] == [{"id": "pending", "label": "your verification method",
                                "method": "otp"}]
    login_id = body["login_id"]

    # selecting the pending factor is a no-op (the code is already pending)
    sel = stack.mfa_select(login_id, "pending")
    assert sel.status_code == 200 and sel.json()["status"] == "code_sent"

    ok = stack.mfa_verify(login_id, MFA_CODE)
    assert ok.status_code == 200, ok.text
    done = ok.json()
    assert done["status"] == "ok"
    assert done["session"]["email"] == MFA_B.email
