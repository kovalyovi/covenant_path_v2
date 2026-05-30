"""
Incremental profile cache — the main lever for cutting LCR calls on repeat runs.

The expensive part of a report is the 3 member-profile server actions per member
(record + recommend + ministering). Most members don't change day to day, so for a
DAILY job we cache each member's profile fields keyed by personUuid with a fetch
timestamp and reuse them within a freshness window. Steady-state, a daily run with
a 7-day window re-fetches only ~1/7 of members → ~85% fewer profile calls.

Tradeoff: a cached field can be up to `max_age_days` stale. Covenant-path fields
change slowly (recommends, ordinations), so this is safe; force a full refresh any
time with max_age_days=0 (or delete the cache file).

In the cloud (GitHub Actions, ephemeral runners) the local file doesn't persist —
there, the Supabase `members.updated_at` column plays the same role (skip members
synced within the window). This local cache covers local/dev runs and is a clean
drop-in the daily job can swap for the DB-backed check.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "tools" / "output" / "profile_cache.json"

# Bump when the set of profile fields changes, so stale-shaped cache entries (e.g. missing a
# newly-added field like sex / priesthood_office / ministering_brothers_sisters) are treated as
# misses and refetched instead of served with gaps. v2 = added sex + priesthood-office + received
# ministering (2026-05-30).
SCHEMA_VERSION = 2


class ProfileCache:
    def __init__(self, path: str | Path = DEFAULT_PATH, max_age_days: float = 7.0,
                 enabled: bool = True) -> None:
        self.path = Path(path)
        self.max_age = max_age_days * 86400
        self.enabled = enabled
        self._data: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0
        if enabled and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._data = {}

    def get(self, uuid: str) -> dict | None:
        """Return cached profile fields if present and fresh, else None."""
        if not self.enabled or not uuid:
            return None
        entry = self._data.get(uuid)
        if not entry:
            self.misses += 1
            return None
        # Different field schema (old cache) -> refetch so new fields aren't served as gaps.
        if entry.get("_v") != SCHEMA_VERSION:
            self.misses += 1
            return None
        # max_age <= 0 means "always refresh" -> treat every entry as stale on read
        # (we still keep/refresh the stored value via put()).
        age = time.time() - entry.get("_ts", 0)
        if self.max_age <= 0 or age > self.max_age:
            self.misses += 1
            return None
        self.hits += 1
        return {k: v for k, v in entry.items() if k not in ("_ts", "_v")}

    def put(self, uuid: str, fields: dict) -> None:
        if not self.enabled or not uuid:
            return
        self._data[uuid] = {**fields, "_ts": time.time(), "_v": SCHEMA_VERSION}

    def prune(self, live_uuids: set[str]) -> int:
        """Drop entries for members no longer in the report (left the stake)."""
        stale = set(self._data) - set(live_uuids)
        for u in stale:
            del self._data[u]
        return len(stale)

    def save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    @property
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._data),
                "hit_rate": round(self.hits / total, 3) if total else 0.0}
