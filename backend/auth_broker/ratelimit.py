"""
In-memory sliding-window rate limiting for the broker's unauthenticated auth surface.

BACKEND-01: the broker had NO rate limiting, and a failed MFA/OTP verify kept the pending login
alive — so code brute-forcing and login/email flooding were unbounded (account-takeover + a trivial
DoS of the single Render instance). The broker runs single-instance, so an in-process dict suffices
(same rationale as email_relay._COOLDOWN_SECONDS).

Two layers, both raising HTTP 429:
  * limiter(bucket, limit, window)  — a FastAPI dependency: per-CLIENT-IP cap.
  * hit_identifier(bucket, id)       — called inside a handler once the username / login_id / email
                                       is known: per-IDENTIFIER cap (catches a spray across IPs).

All limits are env-tunable (RL_<BUCKET>_LIMIT / _WINDOW, RL_ID_LIMIT / _WINDOW) so a shared egress
IP that trips a false 429 can be loosened without a redeploy. Disabled automatically under tests
(CP_TEST_MODE / pytest) and via RL_DISABLED=1; active by default in production (neither is set on
Render — see docs/TESTING.md).
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException, Request

_LOCK = threading.Lock()
_HITS: dict[str, list[float]] = {}


def _disabled() -> bool:
    return (os.environ.get("RL_DISABLED") == "1"
            or os.environ.get("CP_TEST_MODE") == "1"
            or "PYTEST_CURRENT_TEST" in os.environ)


def _client_ip(request: Request) -> str:
    # Render/Cloudflare put the real client first in X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _check(key: str, limit: int, window: float) -> None:
    """Record a hit for `key`; raise 429 if more than `limit` hits fall inside `window` seconds.
    Always functional (not gated by _disabled) so it is directly unit-testable."""
    if limit <= 0:
        return
    now = time.time()
    with _LOCK:
        hits = [t for t in _HITS.get(key, ()) if now - t < window]
        if len(hits) >= limit:
            raise HTTPException(status_code=429,
                                detail="Too many attempts — please wait a moment and try again.")
        hits.append(now)
        _HITS[key] = hits
        if len(_HITS) > 4096:  # opportunistic prune so the map can't grow unbounded
            for k in [k for k, v in list(_HITS.items()) if not any(now - t < window for t in v)]:
                _HITS.pop(k, None)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def limiter(bucket: str, limit: int, window: float):
    """FastAPI dependency factory: per-client-IP sliding-window cap for `bucket`."""
    lim = _env_int(f"RL_{bucket.upper()}_LIMIT", limit)
    win = _env_float(f"RL_{bucket.upper()}_WINDOW", window)

    def dep(request: Request) -> None:
        if _disabled():
            return
        _check(f"{bucket}:ip:{_client_ip(request)}", lim, win)

    return dep


def hit_identifier(bucket: str, identifier: str) -> None:
    """Per-identifier (username / login_id / email) cap — call inside the handler once known."""
    if _disabled():
        return
    lim = _env_int(f"RL_{bucket.upper()}_ID_LIMIT", _env_int("RL_ID_LIMIT", 15))
    win = _env_float(f"RL_{bucket.upper()}_ID_WINDOW", _env_float("RL_ID_WINDOW", 600.0))
    _check(f"{bucket}:id:{(identifier or '').strip().lower()}", lim, win)
