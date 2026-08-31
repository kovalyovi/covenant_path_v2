"""
Shared HTTP resilience for the LCR client — so every endpoint (GET *and* the
member-profile POST server actions) recovers from LCR's flaky 500s the same way,
without hammering an endpoint that is permanently dead.

Two pieces:

  • `is_transient(exc_or_status)` — classify a failure as RETRYABLE (5xx, 429,
    timeouts, connection resets) vs PERMANENT (a deterministic 404 means the route
    moved/was removed — retrying can't conjure it; an auth redirect is handled
    elsewhere). This is what keeps us from retrying the dead `member-list` endpoint
    while still retrying the flaky `progress-record` / `details` / profile POSTs.

  • `CircuitBreaker` — a per-PROCESS, per-endpoint latch. Once an endpoint returns a
    PERMANENT failure (e.g. member-list 404s) the breaker `open()`s it; subsequent
    units short-circuit instantly instead of re-issuing the same doomed request 69×
    (8 calls / 8 errors in the diagnostics). Transient failures never open it — those
    we WANT to retry next time.

  • `retry_call(fn, ...)` — exponential backoff + jitter, transient-only, with a
    hard cap on total wall-time so a single member can't blow the per-stake job
    budget. Returns `None` (caller decides the sentinel) after exhausting attempts.

All pure-Python and deterministic under a patched `sleep`/`time` so the stress
tests run offline with zero network.
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable

import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()

# HTTP statuses worth a retry: server-side overload (5xx) and explicit throttling (429).
# 404 is deliberately NOT here — it's a deterministic "this route is gone" (the dead
# member-list endpoint), so we let the breaker latch it instead of retrying.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 408})


def status_of(exc: BaseException) -> int | None:
    """The HTTP status carried by a requests error, if any (else None for transport errors)."""
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) is not None:
        return int(resp.status_code)
    return None


def is_transient(exc: BaseException) -> bool:
    """True iff `exc` is a RETRYABLE failure (flaky 5xx/429/timeout/conn reset), False for a
    permanent one (a 4xx like 404 'route gone', or a non-HTTP programming error)."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    st = status_of(exc)
    if st is not None:
        return st in _RETRYABLE_STATUS
    # An HTTPError with a 4xx (other than 408/429) is permanent; everything else (a bare
    # RuntimeError raised by our own parsers on a 500 body, etc.) is treated as transient so a
    # genuinely-flaky endpoint still gets its retries. A truly-dead endpoint surfaces a 404
    # HTTPError (permanent) and the breaker latches it.
    if isinstance(exc, requests.HTTPError):
        return False
    return True


def is_permanent(exc: BaseException) -> bool:
    return not is_transient(exc)


class CircuitBreaker:
    """Per-process, per-endpoint latch: once an endpoint fails PERMANENTLY we stop calling it for the
    rest of the run (so a dead route isn't re-hit once per unit/member). Thread-safe enough for the
    single-threaded sync; a plain set is sufficient and trivially testable."""

    def __init__(self) -> None:
        self._open: set[str] = set()

    def is_open(self, key: str) -> bool:
        return key in self._open

    def open(self, key: str) -> None:
        if key not in self._open:
            self._open.add(key)
            logger.warning("circuit OPEN for %s — endpoint looks permanently down this run; "
                           "skipping further calls (degrading gracefully)", key)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._open.clear()
        else:
            self._open.discard(key)


# Module-level breaker shared across the client for one process/run. `reset()` it at the start of a
# fresh run (the daily sync does metrics.reset(); call breaker.reset() alongside).
breaker = CircuitBreaker()


def retry_call(
    fn: Callable[[], Any],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    max_total: float = 90.0,
    label: str = "",
    breaker_key: str | None = None,
    on_auth_expired=None,
    on_permanent=None,
) -> Any:
    """Call `fn` with transient-only retry (exp backoff + jitter). Returns fn()'s value, or None
    once retries are exhausted / the breaker is open / a PERMANENT failure occurs.

    - `breaker_key`: when set, a PERMANENT failure OPENs the breaker for that key and an already-open
      breaker short-circuits to None without calling `fn` (so a dead endpoint is hit at most once).
    - `on_permanent`: called with the exception on a PERMANENT failure. Returning None to the caller
      throws away WHY we gave up, and the reason matters: a 404 on one member's profile page ("this
      person has no record") and a 307 to the login host ("the session died") both surface as None,
      but only the second is fixable by re-authorizing. Callers that must tell them apart pass this.
    - `on_auth_expired`: a callable taking the AuthExpiredError; if it re-raises, auth expiry
      propagates (the session layer handles a one-time relogin). Default re-raises.
    - `max_total`: wall-clock budget across all attempts+sleeps, so one member can't stall the run.
    """
    from lcr_client.auth import AuthExpiredError

    if breaker_key and breaker.is_open(breaker_key):
        logger.debug("skip %s: circuit open for %s", label, breaker_key)
        return None

    started = time.perf_counter()
    for i in range(attempts):
        try:
            return fn()
        except AuthExpiredError:
            # Auth expiry is NOT a transient endpoint failure — let the session relogin path own it.
            if on_auth_expired is not None:
                on_auth_expired()
            raise
        except Exception as exc:  # noqa: BLE001
            permanent = is_permanent(exc)
            last = i == attempts - 1
            if permanent:
                if breaker_key:
                    breaker.open(breaker_key)
                logger.warning("giving up on %s (permanent failure, not retried): %s", label, exc)
                if on_permanent is not None:
                    on_permanent(exc)
                return None
            if last:
                logger.warning("giving up on %s after %d attempt(s): %s", label, attempts, exc)
                return None
            sleep_s = min(base_delay * (2 ** i) + random.uniform(0, base_delay), max_delay)
            # Honor the total budget: if the next sleep would blow it, stop now.
            if (time.perf_counter() - started) + sleep_s > max_total:
                logger.warning("giving up on %s: retry budget (%.0fs) exhausted", label, max_total)
                return None
            logger.debug("retry %s in %.2fs (attempt %d/%d): %s", label, sleep_s, i + 1, attempts, exc)
            time.sleep(sleep_s)
    return None
