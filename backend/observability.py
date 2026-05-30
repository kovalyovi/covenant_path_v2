"""
Structured observability → Axiom (#51/52/55). One JSON event shape across the sync layer and the
broker, shipped to Axiom's HTTP ingest. Best-effort and no-op without AXIOM_TOKEN, so nothing
breaks when it isn't configured.

PII policy (#55): events carry IDs / correlation_ids / counts / durations / status — NEVER member
names, birthdates, addresses, or emails. The shape: timestamp, level, event, correlation_id, stake
(unit number), unit, endpoint, duration_ms, count, status, message. One correlation_id per sync run
ties an operation end-to-end. Retention is Axiom's (30-day free tier) — see docs/LOGGING_SETUP.md.

Usage:
    from backend import observability as obs
    cid = obs.new_correlation_id()
    obs.event("sync.stake.start", correlation_id=cid, stake=503991)
    ...
    obs.flush()   # send the buffered batch (call at the end of a run; also auto-flushes at 50)
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()

AXIOM_TOKEN = os.environ.get("AXIOM_TOKEN", "")
AXIOM_DATASET = os.environ.get("AXIOM_DATASET", "covenant-path")
AXIOM_URL = f"https://api.axiom.co/v1/datasets/{AXIOM_DATASET}/ingest"

# Fields that must never be shipped (defense-in-depth against accidental PII).
_PII_KEYS = {"name", "email", "birth_date", "birthdate", "address", "phone", "person_name"}

_buffer: list[dict] = []
_BATCH = 50


def enabled() -> bool:
    return bool(AXIOM_TOKEN)


def new_correlation_id() -> str:
    return secrets.token_hex(8)


def event(name: str, *, level: str = "info", correlation_id: str | None = None,
          stake: int | None = None, unit: int | None = None, endpoint: str | None = None,
          duration_ms: float | None = None, count: int | None = None, status: str | None = None,
          message: str | None = None, **extra) -> None:
    """Buffer one structured event. No-op when Axiom isn't configured. Drops any PII-looking keys."""
    if not AXIOM_TOKEN:
        return
    rec = {
        "_time": datetime.now(timezone.utc).isoformat(),
        "level": level, "event": name,
    }
    for k, v in {"correlation_id": correlation_id, "stake": stake, "unit": unit,
                 "endpoint": endpoint, "duration_ms": duration_ms, "count": count,
                 "status": status, "message": message}.items():
        if v is not None:
            rec[k] = v
    for k, v in extra.items():
        if k.lower() not in _PII_KEYS and v is not None:
            rec[k] = v
    _buffer.append(rec)
    if len(_buffer) >= _BATCH:
        flush()


def flush() -> None:
    """Ship the buffered batch to Axiom (best-effort; clears the buffer regardless)."""
    global _buffer
    if not AXIOM_TOKEN or not _buffer:
        _buffer = []
        return
    batch, _buffer = _buffer, []
    try:
        r = requests.post(AXIOM_URL, headers={"Authorization": f"Bearer {AXIOM_TOKEN}",
                                              "Content-Type": "application/json"},
                          json=batch, timeout=10)
        if r.status_code >= 300:
            logger.warning("axiom ingest %s: %s", r.status_code, r.text[:160])
    except Exception as exc:  # noqa: BLE001 — observability must never break the job
        logger.debug("axiom ingest skipped: %s", exc)


class span:  # noqa: N801 — context manager, lowercase reads nicely
    """Time an operation and emit a start/finish (or error) event pair."""
    def __init__(self, name: str, **fields):
        self.name, self.fields, self.t0 = name, fields, 0.0

    def __enter__(self):
        self.t0 = time.time()
        event(f"{self.name}.start", **self.fields)
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = round((time.time() - self.t0) * 1000, 1)
        if exc_type is None:
            event(f"{self.name}.finish", duration_ms=ms, status="ok", **self.fields)
        else:
            event(f"{self.name}.error", level="error", duration_ms=ms, status="error",
                  message=str(exc)[:300], **self.fields)
        return False  # don't suppress
