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
    "record": "7f2ccb08ceed847752296703e86519aa152df6ea90",
    "recommend": "7f17b3fc0f8bfa0f970314557b20af32fb0e0346b5",
    "ministering": "7fbf523f92fbc2ee6ce8e2384cd3413a82c1bdbf8b",
    # /mlt/orgs leadership-directory action (args ["eng"]) — names every calling +
    # who holds it; used to enrich the role-name catalog (lcr_client/leadership.py).
    "leadership": "7fd95d267e8d08de09a673e270e4d0bc5f384ce7d8",
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
