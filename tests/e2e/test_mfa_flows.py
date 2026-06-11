"""MFA scenarios: shape A (factor menu) and shape B (straight code challenge), including a
wrong-code-then-correct retry (the pending IDX state must survive the failure) and the
friendly-message guarantee (spec scenarios e, f, l)."""

from __future__ import annotations

from tests.mock_lcr.personas import MFA_CODE, PERSONAS

MFA_A = PERSONAS["member.mfa"]
MFA_B = PERSONAS["member.mfab"]


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
    assert audits[-1]["phase"] == "okta:mfa_bad_code"


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
