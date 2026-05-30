"""
Full-time missionaries assigned to a unit, via the /mlt/orgs/missionary server action.

The Member Tools "Full-Time Missionaries" table loads its roster through a Next.js server action:
`POST /mlt/orgs/missionary` carrying a `Next-Action` header and a body of `[unitNumber, "eng"]`
(selecting a ward in the dropdown sends that ward's unit number). The flight response groups the
missionaries into three buckets:

    {"assignedToUnit": [...], "servingFromUnit": [...], "returnedFromUnit": [...]}

We read **assignedToUnit** — the full-time missionaries currently assigned to that ward/branch.
Each record: {uuid, name ("Elder/Sister X"), nameSort, missionName, missionId, phoneNumber, email}.

The action id is build-specific (rotates when LCR redeploys /mlt); seeded in action_config and
overridable by the local config. Same React-flight transport as lcr_client.member_profile.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from lcr_client import action_config
from lcr_client.logging_setup import get_logger
from lcr_client.member_profile import _find, flight_objects

logger = get_logger()

MISSIONARY_URL = "https://lcr.churchofjesuschrist.org/mlt/orgs/missionary?lang=eng"


def _state_tree() -> str:
    """The Next-Router-State-Tree for the /mlt/orgs/missionary page (from the live request)."""
    tree = ["", {"children": ["orgs", {"children": ["missionary", {
        "children": ["__PAGE__", {}, None, None, 0]}, None, None, 0]}, None, None, 0]}, None, None, 20]
    return quote(json.dumps(tree, separators=(",", ":")))


def fetch_unit_missionaries(session, unit_number: int, mission_id: int | None = None) -> list[dict]:
    """Full-time missionaries ASSIGNED to one unit (ward/branch). Optionally restrict to one mission
    (mission_id) so only e.g. the North Carolina Raleigh Mission's missionaries are returned.

    Returns a list of {uuid, name, phone, email, mission_name, mission_id}. Empty list on no
    assignment or a parse miss (the record action stays the canary for a stale build, as elsewhere).
    """
    action_id = action_config.load().get("missionary") or action_config.DEFAULTS["missionary"]
    headers = {
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "Next-Action": action_id,
        "Next-Router-State-Tree": _state_tree(),
        "Origin": "https://lcr.churchofjesuschrist.org",
        "Referer": "https://lcr.churchofjesuschrist.org/",
    }
    resp = session.session.post(
        MISSIONARY_URL,
        headers=headers,
        data=json.dumps([unit_number, "eng"], separators=(",", ":")),
        timeout=60,
        allow_redirects=False,
    )
    obj = _find(flight_objects(resp.text), "assignedToUnit") or {}
    out = []
    for m in (obj.get("assignedToUnit") or []):
        if not isinstance(m, dict):
            continue
        if mission_id is not None and m.get("missionId") != mission_id:
            continue
        out.append({
            "uuid": m.get("uuid"),
            "name": m.get("name"),                # "Elder Trendon Guymon"
            "phone": m.get("phoneNumber"),
            "email": m.get("email"),
            "mission_name": m.get("missionName"),
            "mission_id": m.get("missionId"),
        })
    # PII-safe: log the COUNT only, never names/emails/phones.
    logger.debug("unit %s: %d assigned missionaries", unit_number, len(out))
    return out
