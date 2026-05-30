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
    # Refreshed 2026-05-30 from a live HAR — LCR had rotated all three (the stale ministering id
    # returned nothing → ministering fields were empty). The `record` action self-heals; recommend
    # and ministering don't, so keep these current (or capture a fresh HAR when LCR redeploys).
    "record": "60d9cea64347f48c3278846ad33af661aa96c7c675",
    "recommend": "6048eedaf1d276c5281af3bc5f2ea364440869390a",
    "ministering": "601fc08b32296e765da7c82db3b0a04d680e34af8b",
    # /mlt/orgs leadership-directory action (args ["eng"]) — names every calling +
    # who holds it; used to enrich the role-name catalog (lcr_client/leadership.py) and as the
    # fallback for stake-leader provisioning. Build-specific; rotates on LCR redeploys.
    "leadership": "40cd2d72827a201fcf11e15751b6e76283d1019c2c",
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
