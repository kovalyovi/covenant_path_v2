"""
Persisted store for the build-specific Next.js Server Action ids.

The /mlt member-profile data is fetched via Next.js server actions whose ids are
hashes that change on each LCR redeploy. We keep the last-known-good ids in a
local JSON file so a successful auto-discovery survives restarts; the hardcoded
DEFAULTS are the seed/fallback.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "tools" / "output" / "action_ids.json"

DEFAULTS = {
    # Refreshed 2026-07-19 via HTTP action-discovery (action_discovery.discover_http) after LCR's
    # Turbopack rebuild rotated ALL ids and RENAMED the actions (record→getMemberData,
    # recommend→getRecommendData, ministering→getMinisteringData, callings→getCallingsAndClassesData,
    # leadership→getUnitOrgWrapper, missionary→getFullTimeMissionaryWrapper). Every profile POST
    # 404'd from 2026-07-06ish until this refresh — patriarchal/calling gap-fills silently died.
    # discover_http self-heals these off any LIVE session (pure requests, works on the broker);
    # DEFAULTS are the CI seed, so keep them current here when LCR redeploys.
    "record": "60d3d432376be6002cbd1e050593b164c082a0f184",
    "recommend": "60858689751bc52d895ca386437992b6a4970a484d",
    "ministering": "608c0018605ee18d7f2a2fc077a73c2bde17fedb6d",
    # /mlt member-profile callings action (args [uuid, "eng"]) — returns individualCallings
    # [{positionName, organization, customCalling, sustainedDate, ...}]. The per-member AUTHORITATIVE
    # calling list: the unit org-aggregate (backend.roles._ward_positions) MISSES sub-org callings like
    # "Relief Society Service Committee Member" → members showed "No calling" (the Terry Stoner bug,
    # 2026-06-09). Build-specific; action_discovery self-heals it (detects the individualCallings shape).
    "callings": "605bf78aabb9282ce1dc2b30f708a5192763c935a4",
    # /mlt/orgs leadership-directory action (args ["eng"]) — names every calling +
    # who holds it; used to enrich the role-name catalog (lcr_client/leadership.py) and as the
    # fallback for stake-leader provisioning. Build-specific; rotates on LCR redeploys.
    "leadership": "4080757e68f0abac20c59483c41dccd6037f161044",
    # /mlt/orgs/missionary action (args [unitNumber, "eng"]) — full-time missionaries grouped into
    # assignedToUnit / servingFromUnit / returnedFromUnit for that ward/branch (HAR 2026-05-30).
    "missionary": "6066d3e9b556231692bf3bff2158145a6423eeeb12",
}


def load() -> dict:
    ids = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            ids.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("actions", {}))
        except Exception:
            pass
    return ids


def save(actions: dict, meta: dict | None = None) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({
        "actions": actions,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "meta": meta or {},
    }, indent=2), encoding="utf-8")
