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
    # Refreshed 2026-06-09 via live action-discovery (all three had rotated → temple_recommend was
    # "No" for everyone and ministering used the old shape). action_discovery now self-heals these
    # (scrolls the profile so the recommend/ministering panels fire + matches the current shapes),
    # but DEFAULTS are the CI seed, so keep them current here when LCR redeploys.
    "record": "60222763f6b2a0789a1082f23e8b873eee7fffce76",
    "recommend": "605d8832fe1e750fa97f025e0343e9b20c32c10f29",
    "ministering": "60b620883e890b14734d5eb38c5ad29c9df43d9328",
    # /mlt member-profile callings action (args [uuid, "eng"]) — returns individualCallings
    # [{positionName, organization, customCalling, sustainedDate, ...}]. The per-member AUTHORITATIVE
    # calling list: the unit org-aggregate (backend.roles._ward_positions) MISSES sub-org callings like
    # "Relief Society Service Committee Member" → members showed "No calling" (the Terry Stoner bug,
    # 2026-06-09). Build-specific; action_discovery self-heals it (detects the individualCallings shape).
    "callings": "6064bcb1a1cf344b1eb5f6223bdbf364e638cdb7a9",
    # /mlt/orgs leadership-directory action (args ["eng"]) — names every calling +
    # who holds it; used to enrich the role-name catalog (lcr_client/leadership.py) and as the
    # fallback for stake-leader provisioning. Build-specific; rotates on LCR redeploys.
    "leadership": "40cd2d72827a201fcf11e15751b6e76283d1019c2c",
    # /mlt/orgs/missionary action (args [unitNumber, "eng"]) — full-time missionaries grouped into
    # assignedToUnit / servingFromUnit / returnedFromUnit for that ward/branch (HAR 2026-05-30).
    "missionary": "60c73e23e06abb917261d5299c6554b5093707ac2f",
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
