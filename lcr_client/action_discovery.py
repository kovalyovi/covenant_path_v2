"""
Auto-discovery of the member-profile server-action ids (self-healing).

When LCR redeploys the /mlt app, the action-id hashes change and profile fetches
stop returning data. A pure-requests GET of the profile only yields a loading
shell (the route's JS chunk isn't referenced), so discovery uses a brief
Playwright run: log in, open a profile, watch the server-action POSTs, and detect
which `Next-Action` id returns the record / recommend / ministering shape. The
winners are persisted to action_config, and storage_state is refreshed (so the
caller's cookie session is renewed too).

This is the ONLY place a browser is used for data — and only on breakage. Run
manually any time with: `python -m lcr_client.action_discovery [person_uuid]`
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from lcr_client import action_config
from lcr_client.logging_setup import get_logger
from lcr_client.member_profile import _find, flight_objects

logger = get_logger()
BASE = "https://lcr.churchofjesuschrist.org"
STATE = Path(__file__).resolve().parent.parent / "tools" / "output" / "storage_state.json"

# target -> predicate over a flight response's parsed rows
DETECTORS = {
    "record": lambda objs: bool(_find(objs, "uuid", "ordinances")),
    "recommend": lambda objs: bool(_find(objs, "hasNewRecommendInProcess")),
    "ministering": lambda objs: bool(_find(objs, "ministeringBrothersAssignments")
                                     or _find(objs, "ministeringSistersAssignments")),
}


def discover(uuid: str) -> dict:
    from dotenv import load_dotenv
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from lcr_crawler import attempt_login

    load_dotenv()
    found: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        attempt_login(page, os.getenv("LCR_LOGIN"), os.getenv("LCR_PASSWORD"))

        def on_response(resp):
            req = resp.request
            if req.method != "POST" or "member-profile" not in req.url:
                return
            na = req.headers.get("next-action")
            if not na or na in found.values():
                return
            try:
                objs = flight_objects(resp.text())
            except Exception:
                return
            for target, detect in DETECTORS.items():
                if target not in found and detect(objs):
                    found[target] = na
                    logger.info(f"discovered {target} action -> {na}")

        ctx.on("response", on_response)
        page.goto(f"{BASE}/mlt/records/member-profile/{uuid}?lang=eng",
                  wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        ctx.storage_state(path=str(STATE))  # refresh the cookie session too
        browser.close()

    missing = set(DETECTORS) - set(found)
    if missing:
        logger.warning(f"discovery could not resolve: {sorted(missing)}")
    return found


def heal(session, uuid: str) -> dict:
    """Discover + persist action ids and refresh the caller's cookie session."""
    found = discover(uuid)
    ids = action_config.load()
    ids.update(found)
    action_config.save(ids, meta={"healed_with": uuid, "resolved": sorted(found),
                                  "method": "playwright"})
    try:
        session.reload()
    except Exception:
        pass
    return ids


if __name__ == "__main__":
    from lcr_client import LcrClient

    uuid = sys.argv[1] if len(sys.argv) > 1 else None
    client = LcrClient()
    if not uuid:
        ctx = client.user_context()
        unit = next(u for u in ctx.child_units if u.type in ("WARD", "BRANCH"))
        uuid = client.member_list(unit.unit_number)[0].raw.get("personUuid")
    print("discovered + persisted:", heal(client.session, uuid)["record"])
