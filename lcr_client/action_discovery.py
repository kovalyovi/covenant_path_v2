"""
Auto-discovery of the member-profile server-action ids (self-healing).

When LCR redeploys the /mlt app, the action-id hashes change and profile fetches
stop returning data (the POSTs 404). Discovery is now pure HTTP first
(`discover_http`): GET the profile page with the caller's LIVE session, harvest
the build's JS chunks, and read the `createServerReference("<id>", …, "<name>")`
registrations out of them — the 2026-07 Turbopack rebuild names its data actions
(getMemberData / getRecommendData / getMinisteringData / getCallingsAndClassesData,
plus getUnitOrgWrapper and getFullTimeMissionaryWrapper on the /mlt/orgs pages).
The name-mapped ids are then VERIFIED with a real POST against the response-shape
detectors before being persisted to action_config. No browser, no operator login —
this runs fine inside the auth broker off a freshly-captured enroll session
(where the old Playwright path could never run: no playwright on Render, and a
headless operator login is MFA-blocked anyway).

The Playwright lane (`discover`) remains as the last-ditch fallback for a future
build that drops the name strings: log in, open a profile, watch the server-action
POSTs, and detect which `Next-Action` id returns each shape.

Run manually any time with: `python -m lcr_client.action_discovery [person_uuid]`
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from lcr_client import action_config
from lcr_client.hosts import LCR_BASE
from lcr_client.logging_setup import get_logger
from lcr_client.member_profile import _find, flight_objects

logger = get_logger()
BASE = LCR_BASE
STATE = Path(__file__).resolve().parent.parent / "tools" / "output" / "storage_state.json"
PROFILE_CACHE = Path(__file__).resolve().parent.parent / "tools" / "output" / "profile_cache.json"

# target -> the action's registered NAME in the current /mlt build (first match wins; earlier
# builds' names kept as fallbacks). The build registers every client-callable server action as
# createServerReference("<hex id>", callServer, void 0, findSourceMapURL, "<name>") inside its JS
# chunks — the name survives minification, so it's the stable key across redeploys.
ACTION_NAMES = {
    "record": ("getMemberData", "getMemberProfileData", "getMemberProfile"),
    "recommend": ("getRecommendData",),
    "ministering": ("getMinisteringData",),
    "callings": ("getCallingsAndClassesData", "getIndividualCallings"),
    "leadership": ("getUnitOrgWrapper",),
    "missionary": ("getFullTimeMissionaryWrapper",),
}

# The /mlt pages whose chunk graphs register each target's action. The profile page carries the
# four member-profile actions; the orgs pages carry leadership + missionary.
_ORGS_URL = BASE + "/mlt/orgs?unitTypeId=7,8&list=true&leadership=true&lang=eng"
_MISSIONARY_URL = BASE + "/mlt/orgs/missionary?lang=eng"

_CHUNK_REF_RE = re.compile(r'static/chunks/[^"\'\\\s\)\(]+?\.js')
_SCRIPT_SRC_RE = re.compile(r'src="/mlt/_next/(static/chunks/[^"]+?\.js)"')
_SERVER_REF_RE = re.compile(
    r'createServerReference\)\(\s*["\']([0-9a-f]{40,42})["\'][^)]*?,\s*["\']([A-Za-z0-9_$]+)["\']\s*\)')


def _unescape_js(text: str) -> str:
    """Undo the flight-payload escaping so chunk paths embedded in inline RSC data match too."""
    return text.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")


def _chunk_refs(text: str) -> set[str]:
    """Every static-chunk path referenced by a page's HTML (script tags + inline flight rows) or by
    another chunk's text."""
    t = _unescape_js(text)
    return set(_CHUNK_REF_RE.findall(t)) | set(_SCRIPT_SRC_RE.findall(t))


def _server_refs(js_text: str) -> dict[str, str]:
    """{action name -> action id} registrations found in one chunk's minified JS."""
    return {m.group(2): m.group(1) for m in _SERVER_REF_RE.finditer(_unescape_js(js_text))}


def _targets_from_names(named: dict[str, str]) -> dict[str, str]:
    """Map harvested {name -> id} registrations onto our config targets."""
    out: dict[str, str] = {}
    for target, names in ACTION_NAMES.items():
        for n in names:
            if n in named:
                out[target] = named[n]
                break
    return out


def _harvest_page(session, url: str, max_chunks: int = 200) -> dict[str, str]:
    """GET a /mlt page with the live session and walk its chunk graph, returning every
    {action name -> id} server-action registration reachable from it."""
    resp = session.session.get(url, timeout=60, allow_redirects=False)
    if resp.status_code != 200:
        raise RuntimeError(f"page GET {resp.status_code} (session not live?) for {url}")
    todo, done, named = _chunk_refs(resp.text), set(), {}
    while todo and len(done) < max_chunks:
        chunk = todo.pop()
        done.add(chunk)
        try:
            cr = session.session.get(f"{BASE}/mlt/_next/{chunk}", timeout=30)
            if cr.status_code != 200:
                continue
            named.update(_server_refs(cr.text))
            todo |= (_chunk_refs(cr.text) - done)
        except Exception:  # noqa: BLE001 — a missing chunk shouldn't sink the harvest
            continue
    return named


def discover_http(session, uuid: str) -> dict:
    """Discover the current action ids over pure HTTP using the caller's LIVE session — no browser,
    no operator login, broker-safe. Harvests the createServerReference registrations from the
    profile + orgs chunk graphs, maps them by ACTION NAME, then VERIFIES the canary (`record`) with
    a real POST against the record-shape detector so a renamed-but-wrong id is never persisted.
    Returns {} when the harvest finds nothing (caller falls back to the Playwright lane)."""
    from lcr_client.member_profile import PROFILE_URL, call_action

    named = _harvest_page(session, PROFILE_URL.format(uuid=uuid))
    for org_url in (_ORGS_URL, _MISSIONARY_URL):
        try:
            named.update(_harvest_page(session, org_url))
        except Exception as exc:  # noqa: BLE001 — orgs pages are best-effort extras
            logger.debug("orgs harvest skipped (%s): %s", org_url, exc)
    found = _targets_from_names(named)
    logger.info("http discovery: %d server actions harvested, mapped %s",
                len(named), sorted(found))

    if "record" not in found:
        # Names rotated too — fall back to shape-testing every harvested id against the detectors.
        for aid in list(named.values())[:60]:
            if aid in found.values():
                continue
            try:
                objs = call_action(session, uuid, aid, [uuid, "eng"])
            except Exception:  # noqa: BLE001 — 404/5xx candidates are just wrong ids
                continue
            for target, detect in DETECTORS.items():
                if target not in found and detect(objs):
                    found[target] = aid
                    logger.info("http discovery (shape probe): %s -> %s", target, aid[:10])
        return found

    # Verify the canary before trusting the whole name-mapped set.
    try:
        objs = call_action(session, uuid, found["record"], [uuid, "eng"])
        if not DETECTORS["record"](objs):
            logger.warning("http discovery: name-mapped record id failed shape verify — discarding")
            return {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("http discovery: record verify POST failed (%s) — discarding", exc)
        return {}
    return found


# target -> predicate over a flight response's parsed rows
DETECTORS = {
    "record": lambda objs: bool(_find(objs, "uuid", "ordinances")),
    "recommend": lambda objs: bool(_find(objs, "hasNewRecommendInProcess")
                                   or _find(objs, "recommend", "status")),
    # The ministering action's response shape changed — it now returns inbound `ministeringBrothers`
    # (not only `*Assignments`). Match either, but exclude the record response (which also carries
    # ministering) so the record action isn't misclassified.
    "ministering": lambda objs: bool(
        (_find(objs, "ministeringBrothersAssignments") or _find(objs, "ministeringSistersAssignments")
         or _find(objs, "ministeringBrothers") or _find(objs, "ministeringSisters"))
        and not _find(objs, "uuid", "ordinances")),
    # The callings action returns `individualCallings` (the per-member calling list). Distinct shape,
    # so a plain key check identifies it.
    "callings": lambda objs: bool(_find(objs, "individualCallings")),
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
        # The recommend / ministering panels POST their action only when their section RENDERS — a
        # passive load misses them (the reason discovery kept failing on those two). Scroll through to
        # lazy-render every section, settling between, so their POSTs fire and get captured.
        try:
            for _ in range(8):
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(700)
            page.wait_for_load_state("networkidle", timeout=10000)
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
    """Discover + persist action ids. HTTP discovery first (works everywhere the caller's session is
    live — including the broker, where Playwright can't run); the browser lane only as fallback."""
    method = "http"
    try:
        found = discover_http(session, uuid)
    except Exception as exc:  # noqa: BLE001 — e.g. dead session: page GET != 200
        logger.warning("http discovery failed: %s", exc)
        found = {}
    if not found.get("record"):
        method = "playwright"
        found = discover(uuid)
    ids = action_config.load()
    ids.update(found)
    action_config.save(ids, meta={"healed_with": uuid, "resolved": sorted(found),
                                  "method": method})
    # Action ids changed → the profile cache holds values fetched with the OLD ids; drop it so the
    # next run re-fetches with the new ids. Otherwise cached stale data masks the heal — the
    # "temple_recommend stayed 'No' after a re-sync because 67 cache hits served old data" trap.
    if found:
        try:
            PROFILE_CACHE.unlink(missing_ok=True)
            logger.info("cleared profile cache after action-id heal (%s)", sorted(found))
        except Exception:  # noqa: BLE001
            pass
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
