"""
Mock LCR + Okta identity hosts for the e2e harness (CP_TEST_MODE seam, lcr_client/hosts.py).

Two FastAPI apps over ONE shared state object:
  - identity app: the Okta IDX login flow + /authorize SSO hop (+ control plane)
  - LCR app:      /api/auth/*, /api/user-context, /other/access-table (+ control plane)

They must be served on DIFFERENT netlocs (ports) — establish_lcr_session treats a final URL
on the identity netloc as the SSO-failure signal.

Run standalone:  python -m tests.mock_lcr  [--identity-port 8901 --lcr-port 8902]
Embed in tests:  build_state(...) + create_identity_app(state) + create_lcr_app(state)
"""

from tests.mock_lcr.identity_app import create_identity_app
from tests.mock_lcr.lcr_app import create_lcr_app
from tests.mock_lcr.personas import (
    MFA_CODE, PERSONAS, STAKE_NAME, STAKE_UNIT, WARD1_NAME, WARD1_UNIT,
    WARD2_NAME, WARD2_UNIT,
)
from tests.mock_lcr.state import MockChurchState


def build_state(identity_base: str, lcr_base: str) -> MockChurchState:
    return MockChurchState(identity_base=identity_base, lcr_base=lcr_base)


__all__ = [
    "MFA_CODE", "PERSONAS", "STAKE_NAME", "STAKE_UNIT", "WARD1_NAME", "WARD1_UNIT",
    "WARD2_NAME", "WARD2_UNIT", "MockChurchState", "build_state",
    "create_identity_app", "create_lcr_app",
]
