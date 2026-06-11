"""
Fictional test personas + the LCR response payloads the real parsers consume.

ALL DATA HERE IS INVENTED (public repo): "Testvale" units 999001/999101/999102 and
example.org people. Shapes, however, are faithful to the real endpoints' schemas
(verified against lcr_client/models.py, lcr_client/access.py and the HAR-derived
schema report) so the production parsers exercise their real code paths:

  /api/auth/me        -> AuthMe.from_api + okta_flow._identity (email/name/churchCMISID/
                         churchCMISUUID/preferred_username/personalEmail)
  /api/user-context   -> UserContext.from_api (activePosition*/unit.children/positions)
                         AND access.runner_positions (platformUserContext.user.targetUser)
  /other/access-table -> access.fetch_access_matrix (__NEXT_DATA__ ->
                         props.pageProps.initialProps.accessTableData.membership + rolesData)
"""

from __future__ import annotations

import json
from dataclasses import dataclass

STAKE_UNIT = 999001
WARD1_UNIT = 999101
WARD2_UNIT = 999102
STAKE_NAME = "Testvale North Stake"
WARD1_NAME = "Testvale 1st Ward"
WARD2_NAME = "Testvale 2nd Ward"

PASSWORD_AUTH_ID = "aut-mock-password-0001"
EMAIL_AUTH_ID = "aut-mock-email-0001"
PHONE_AUTH_ID = "aut-mock-phone-0001"
PHONE_ENROLLMENT_ID = "pae-mock-phone-0001"
WEBAUTHN_AUTH_ID = "aut-mock-webauthn-0001"
MFA_CODE = "123456"

# FULLSTACK-LANE ALIGNMENT: the no-MFA personas' /api/auth/me emails EQUAL the seeded
# rls.* accounts in tests/seed.py (rls.president / rls.bishop / rls.norole @example.org).
# A Church login through the REAL broker mints a Supabase session for the auth/me email —
# against the real TEST project that session must land on an existing RLS scope
# (user_roles row), or the browser e2e (apps/web/e2e/fullstack) would always see zero rows.
# Change them together or the fullstack lane breaks.


@dataclass(frozen=True)
class Persona:
    username: str
    password: str
    name: str            # display name (fictional)
    first_name: str
    last_name: str
    email: str
    cmis_id: str
    cmis_uuid: str
    mfa: str | None      # None | "shape_a" | "shape_b"
    role_id: int | None  # positionType id (None = no calling at all)
    calling: str | None
    unit_number: int
    unit_name: str
    is_stake: bool = False


# Persona.mfa values: None | "shape_a" | "shape_b" | "shape_a_webauthn" (the 2026-06-11 menu —
# a security key ALONGSIDE code factors; the broker must offer only the code factors).
PERSONAS: dict[str, Persona] = {p.username: p for p in [
    Persona("president.complete", "pw-president", "Avery Example", "Avery", "Example",
            "rls.president@example.org", "1000000001",
            "11111111-1111-4111-8111-111111111111", None,
            1, "Stake President", STAKE_UNIT, STAKE_NAME, is_stake=True),
    Persona("wardleader.partial", "pw-ward", "Blair Sample", "Blair", "Sample",
            "rls.bishop@example.org", "1000000002",
            "22222222-2222-4222-8222-222222222222", None,
            4, "Bishop", WARD1_UNIT, WARD1_NAME),
    Persona("member.nocalling", "pw-member", "Casey Specimen", "Casey", "Specimen",
            "rls.norole@example.org", "1000000003",
            "33333333-3333-4333-8333-333333333333", None,
            None, None, WARD1_UNIT, WARD1_NAME),
    Persona("member.mfa", "pw-mfa", "Drew Placeholder", "Drew", "Placeholder",
            "drew.placeholder@example.org", "1000000004",
            "44444444-4444-4444-8444-444444444444", "shape_a",
            57, "Ward Clerk", WARD2_UNIT, WARD2_NAME),
    Persona("member.mfab", "pw-mfab", "Ellis Fixture", "Ellis", "Fixture",
            "ellis.fixture@example.org", "1000000005",
            "55555555-5555-4555-8555-555555555555", "shape_b",
            57, "Ward Clerk", WARD2_UNIT, WARD2_NAME),
    Persona("member.mfaw", "pw-mfaw", "Finley Archetype", "Finley", "Archetype",
            "finley.archetype@example.org", "1000000006",
            "66666666-6666-4666-8666-666666666666", "shape_a_webauthn",
            57, "Ward Clerk", WARD2_UNIT, WARD2_NAME),
]}

LOCKED_USERNAME = "user.locked"


def auth_me(p: Persona) -> dict:
    """GET /api/auth/me body — key set mirrors the HAR-captured schema (sub/name/email/ver/
    jti/amr/idp/preferred_username/churchCMISID/firstName/lastName + the CMIS uuid)."""
    return {
        "sub": f"00umock{p.cmis_id}",
        "name": p.name,
        "email": p.email,
        "personalEmail": p.email,
        "ver": 1,
        "jti": f"ID.mock.{p.cmis_id}",
        "amr": ["pwd"],
        "idp": "00omockidp0000000001",
        "preferred_username": p.username,
        "churchCMISID": p.cmis_id,
        "churchCMISUUID": p.cmis_uuid,
        "firstName": p.first_name,
        "lastName": p.last_name,
    }


def _platform_positions(p: Persona) -> dict:
    if p.role_id is None:
        return {"currentPosition": None, "supportedPositions": None}
    return {
        "currentPosition": {
            "positionType": {"id": p.role_id, "name": p.calling},
            "unit": {"name": p.unit_name, "unitNumber": p.unit_number},
            "positionStatus": "ACTIVE_POSITION",
        },
        "supportedPositions": [],
    }


def user_context(p: Persona) -> dict:
    """GET /api/user-context body. One payload serves BOTH consumers:
      - UserContext.from_api: individualId / activePosition(English) / unit{unitName,
        unitNumber, children[]} / positions / roles
      - access.runner_positions: platformUserContext.user.targetUser.currentPosition/
        supportedPositions (positionType {id, name})
    The no-calling persona mirrors the HAR-verified real shape: activePosition /
    activePositionEnglish / positions / roles all null, no child units."""
    if p.role_id is None:
        return {
            "individualId": f"ind-{p.cmis_id}",
            "activePosition": None,
            "activePositionEnglish": None,
            "unit": {"unitName": p.unit_name, "unitNumber": p.unit_number, "children": None},
            "positions": None,
            "roles": None,
            "platformUserContext": {"user": {"targetUser": _platform_positions(p)}},
        }
    children = []
    if p.is_stake:
        children = [
            {"unitName": WARD1_NAME, "unitNumber": WARD1_UNIT, "type": "WARD"},
            {"unitName": WARD2_NAME, "unitNumber": WARD2_UNIT, "type": "WARD"},
        ]
    return {
        "individualId": f"ind-{p.cmis_id}",
        "activePosition": p.role_id,
        "activePositionEnglish": p.calling,
        "unit": {"unitName": p.unit_name, "unitNumber": p.unit_number, "children": children},
        "positions": [{
            "positionTypeId": p.role_id, "positionTypeName": p.calling,
            "unitNumber": p.unit_number, "unitName": p.unit_name,
        }],
        "roles": [p.calling.upper().replace(" ", "_")],
        "platformUserContext": {"user": {"targetUser": _platform_positions(p)}},
    }


# The calling -> feature matrix (GLOBAL in real LCR — personas differ only by the role ids
# their user-context carries). Drawn so the personas land where the tests need them:
#   role 1  (Stake President): every data feature           -> can_pull_all
#   role 4  (Bishop):          partial (no temple/patriarchal) -> missing + who-to-ask
#   role 57 (Ward Clerk):      progress + member list only
FEATURE_ROLES: dict[str, list] = {
    "menu.progress.record":              [1, 4, 52, 53, 57],
    "menu.member.list":                  [1, 4, 52, 53, 57],
    "menu.view.member.profiles":         [1, 4, 52, 53],
    "menu.temple.recommend.status":      [1, 52, "ECC_ONLY_9001"],
    "menu.patriarchal.blessing.status":  [1, 52],
    "menu.ward.leadership":              [1, 52, 53],   # stake's view of ward leadership
    "menu.stake.leadership":             [4, 57],       # ward's view of stake leadership
    # extra non-covenant-path features for realism (ignored by covenant_path_access):
    "menu.classes.quorums.attendance":   [1, 4, 52, 53, 57],
    "menu.unit.statistics":              [1, 4, 52],
}

ROLES_DATA = {
    "1": "Stake President",
    "4": "Bishop",
    "52": "Stake Clerk",
    "53": "Stake Assistant Clerk",
    "57": "Ward Clerk",
}


def access_table_html() -> str:
    """The /other/access-table page: HTML with the __NEXT_DATA__ script blob exactly where
    access._NEXT_DATA_RE expects it (props.pageProps.initialProps.{accessTableData,rolesData})."""
    next_data = {
        "props": {"pageProps": {"initialProps": {
            "accessTableData": {
                "membership": [{
                    "name": "accessTable.section.membershipRecords",
                    "features": [{"name": k, "roles": v} for k, v in FEATURE_ROLES.items()],
                }],
                # the real page also has a finance side; present-but-empty keeps the shape honest
                "finance": [],
            },
            "rolesData": ROLES_DATA,
        }}},
        "page": "/other/access-table",
    }
    return (
        "<!doctype html><html><head><title>Access Table</title></head><body>"
        '<div id="__next">Mock LCR access table</div>'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )
