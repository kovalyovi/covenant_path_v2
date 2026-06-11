"""Control-plane scenarios beyond the core list: sso_reject driven through the REAL broker
(the "Okta accepted the password but LCR refused the session" mode), and the
identity_timeout mechanism verified at mock level (the full-broker version would need to
out-wait the production 60s client timeouts — too slow for the default lane)."""

from __future__ import annotations

import pytest
import requests

from tests.mock_lcr.personas import PERSONAS

PRESIDENT = PERSONAS["president.complete"]


def test_sso_reject_surfaces_session_not_accepted_503(stack):
    stack.scenario("sso_reject")
    res = stack.login(PRESIDENT.username, PRESIDENT.password)
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "did not accept the session" in detail
    assert "IDX" not in detail

    audits = stack.audit_rows(outcome="lcr_identity_failed")
    assert audits and audits[-1]["phase"] == "identity:sso_rejected"
    assert "Okta" in (audits[-1]["error"] or "")  # root cause: "SSO landed back on Okta"


def test_identity_timeout_scenario_hangs_identity_endpoints(stack):
    stack.scenario("identity_timeout", sleep_seconds=2)
    with pytest.raises(requests.exceptions.Timeout):
        requests.post(f"{stack.identity_base}/oauth2/default/v1/interact",
                      data={"client_id": "x"}, timeout=0.5)
    # the control plane itself must stay responsive while the scenario is active
    assert stack.mock_state()["scenario"] == "identity_timeout"
