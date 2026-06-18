"""
Leadership directory via pure HTTP — names every calling and who holds it.

The /mlt/orgs leadership view loads its data through a Next.js Server Action POST
(args ["eng"]) that returns the whole hierarchy's leadership: each org's positions
with `positionType {id, name}` and the person filling it. We replay it with the
cookie session (no browser) to:
  1. ENRICH the role-id -> calling-name catalog (lcr_client/access.role_names cache),
     naming the secondary seats the access-table page's rolesData omits, and
  2. expose who holds each calling (future "who to ask" by name).

The action id is build-specific (lives in action_config under "leadership"); if it
goes stale, re-capture with `python tools/capture_callings.py "<leadership url>"`.
The harvested names persist in the cache regardless, so enrichment is opportunistic.

CLI:  python -m lcr_client.leadership          # enrich the role-name cache
"""

from __future__ import annotations

import json
from urllib.parse import quote

from lcr_client import access, action_config
from lcr_client.hosts import LCR_BASE
from lcr_client.logging_setup import get_logger
from lcr_client.member_profile import flight_objects

logger = get_logger()

ORGS_URL = (f"{LCR_BASE}/mlt/orgs"
            "?unitTypeId=7,8&list=true&leadership=true&lang=eng")
# App-Router state tree for the /mlt/orgs page (captured live).
_ORGS_STATE = ["", {"children": ["orgs", {"children": ["__PAGE__", {}, None, None]},
                                 None, None]}, None, None, True]


def _state_tree() -> str:
    return quote(json.dumps(_ORGS_STATE, separators=(",", ":")))


def _post_leadership(session):
    """POST the leadership server action; return the raw response so callers can tell a DEAD session
    (non-200 / login redirect) from a genuinely stale action id (a 200 whose shape lost positionType)."""
    action = action_config.load().get("leadership", action_config.DEFAULTS["leadership"])
    headers = {
        "Next-Action": action,
        "Next-Router-State-Tree": _state_tree(),
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "Origin": LCR_BASE,
        "Referer": ORGS_URL,
    }
    return session.session.post(ORGS_URL, headers=headers, data='["eng"]',
                                timeout=60, allow_redirects=False)


def fetch_leadership(session) -> list:
    """POST the leadership server action; return parsed React-flight objects."""
    return flight_objects(_post_leadership(session).text)


def harvest_role_names(objs: list) -> dict[int, str]:
    """Pull every positionType {id,name} pair out of the flight response."""
    pairs: dict[int, str] = {}

    def walk(o):
        if isinstance(o, dict):
            pt = o.get("positionType")
            if isinstance(pt, dict) and isinstance(pt.get("id"), int) and pt.get("name"):
                pairs[pt["id"]] = pt["name"]
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(objs)
    return pairs


def enrich_role_names(client) -> int:
    """Fetch the leadership directory and merge discovered calling names into the cache."""
    resp = _post_leadership(client.session)
    pairs = harvest_role_names(flight_objects(resp.text))
    if not pairs:
        # An empty harvest has two very different causes: a genuinely STALE action id (a real 200 whose
        # shape no longer carries positionType), OR — far more common in the steady state — a DEAD
        # delegated LCR session, where this POST (allow_redirects=False) comes back non-200 / redirected
        # to login with no flight rows. Only the former is actionable; the old code warned "re-capture
        # the action id" for BOTH, a false alarm that fired twice per run on a dead session (503991).
        if resp.status_code != 200:
            logger.debug("leadership enrich skipped — LCR session not live (HTTP %s)", resp.status_code)
        else:
            logger.warning("leadership action returned no positionType data — the 'leadership' "
                           "action id may be stale; re-capture with tools/capture_callings.py")
        return 0
    added = access.register_names(pairs)
    logger.info("leadership enrich: %d calling names seen, %d new", len(pairs), added)
    return added


def main() -> int:
    from lcr_client import LcrClient

    added = enrich_role_names(LcrClient())
    print(f"[+] role-name cache enriched: +{added} names "
          f"(total {len(access._load_name_cache())})")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
