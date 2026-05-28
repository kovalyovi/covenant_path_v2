"""
In-process LCR request metrics — latency + status for every JSON call, so a sync (or the
probe bot) can report per-endpoint performance and exactly where 500s / timeouts happen.

Cheap and thread-safe; `reset()` at the start of a run, `snapshot()` at the end. Endpoints
are normalized (ids/uuids/numbers -> {id}) so all calls to e.g. one-work/details aggregate.
"""

from __future__ import annotations

import re
import threading
from urllib.parse import urlparse

_lock = threading.Lock()
_events: list[dict] = []

_UUID = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_NUM = re.compile(r"/\d+")


def normalize(url: str) -> str:
    path = urlparse(url).path
    path = _UUID.sub("/{id}", path)
    path = _NUM.sub("/{id}", path)
    return path or url


def record(url: str, status: int, ms: float, error: str | None = None) -> None:
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 0
    with _lock:
        _events.append({"endpoint": normalize(url), "status": status,
                        "ms": round(ms), "ok": 200 <= status < 400 and error is None,
                        "error": error})


def reset() -> None:
    with _lock:
        _events.clear()


def snapshot() -> dict:
    """Aggregate per endpoint: calls, ok, errors, status histogram, avg/max latency."""
    with _lock:
        events = list(_events)
    by: dict[str, dict] = {}
    for e in events:
        a = by.setdefault(e["endpoint"], {"calls": 0, "ok": 0, "errors": 0,
                                          "statuses": {}, "ms_sum": 0, "ms_max": 0})
        a["calls"] += 1
        a["ok"] += 1 if e["ok"] else 0
        a["errors"] += 0 if e["ok"] else 1
        a["statuses"][str(e["status"])] = a["statuses"].get(str(e["status"]), 0) + 1
        a["ms_sum"] += e["ms"]
        a["ms_max"] = max(a["ms_max"], e["ms"])
    endpoints = []
    total_calls = total_errors = 0
    for ep, a in sorted(by.items()):
        total_calls += a["calls"]
        total_errors += a["errors"]
        endpoints.append({
            "endpoint": ep, "calls": a["calls"], "ok": a["ok"], "errors": a["errors"],
            "statuses": a["statuses"],
            "avg_ms": round(a["ms_sum"] / a["calls"]) if a["calls"] else 0,
            "max_ms": a["ms_max"],
        })
    return {
        "total_calls": total_calls,
        "total_errors": total_errors,
        "success_pct": round(100 * (total_calls - total_errors) / total_calls, 1) if total_calls else 100.0,
        "endpoints": endpoints,
    }
