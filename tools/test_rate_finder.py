"""
Offline tests for the per-endpoint gold-spot controller in tools/rate_finder.py.

No network: we feed synthetic Sample rounds into EndpointController and assert the AIMD logic —
gold-spot crediting only after a confirmation streak, immediate back-off on a transient 5xx,
permanent-404 (dead route) NOT treated as a load failure, and the kill switch parking an endpoint
that keeps erroring at the floor. Run: python tools/test_rate_finder.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rate_finder import EndpointController, Sample  # noqa: E402

_PASS = 0
_FAIL = 0


def check(name: str, cond: bool) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  ok   {name}")
    else:
        _FAIL += 1
        print(f"  FAIL {name}")


def _ctrl(**kw) -> EndpointController:
    defaults = dict(success_target=0.99, p95_cap_ms=None, max_concurrency=6,
                    min_delay=0.2, max_delay=30.0, window=10, confirm=3,
                    cooldown_s=900.0, kill_after=4)
    defaults.update(kw)
    return EndpointController("test", **defaults)


def _ok(n=10):
    return [Sample(200, 100.0) for _ in range(n)]


def _transient(n=10):
    return [Sample(500, 100.0) for _ in range(n)]


def _permanent(n=10):
    return [Sample(404, 50.0) for _ in range(n)]


def test_sample_classification() -> None:
    check("200 is ok", Sample(200, 1).ok and not Sample(200, 1).transient_bad)
    check("500 is transient", Sample(500, 1).transient_bad and not Sample(500, 1).permanent_bad)
    check("429 is transient", Sample(429, 1).transient_bad)
    check("timeout(0) is transient", Sample(0, 1).transient_bad)
    check("404 is permanent, not transient",
          Sample(404, 1).permanent_bad and not Sample(404, 1).transient_bad)


def test_gold_spot_after_confirmation() -> None:
    c = _ctrl(confirm=3)
    start_delay = c.delay_s
    # Two clean rounds: not yet confirmed -> no gold, no pressure change.
    c.observe(_ok(), elapsed_s=1.0)
    c.observe(_ok(), elapsed_s=1.0)
    check("no gold before the confirmation streak completes", c.gold is None)
    check("pressure unchanged before confirm", c.delay_s == start_delay and c.concurrency == 1)
    # Third clean round completes the streak -> gold credited + pressure increased.
    c.observe(_ok(), elapsed_s=1.0)
    check("gold spot credited after confirm clean rounds", c.gold is not None)
    check("gold records the throughput", c.gold and c.gold.per_min > 0)
    check("pressure increased (delay reduced) after gold", c.delay_s < start_delay)


def test_backoff_on_transient() -> None:
    c = _ctrl()
    c.concurrency = 3  # pretend we'd ramped up
    c.observe(_transient(), elapsed_s=1.0)
    check("transient error backs concurrency off", c.concurrency == 2)
    check("first_error_per_min recorded", c.first_error_per_min is not None)
    check("healthy streak reset on error", c.healthy_streak == 0)


def test_permanent_404_is_not_load_failure() -> None:
    # The dead member-list route: a clean 404 must read as SLO-OK (it's not overload) and never
    # trigger a back-off — otherwise the control endpoint would drag the others down.
    c = _ctrl()
    rnd = c.observe(_permanent(), elapsed_s=1.0)
    check("all-404 round is SLO-OK (not a transient failure)", rnd["slo_ok"] is True)
    check("404 round does not set first_error", c.first_error_per_min is None)


def test_p95_cap_enforced() -> None:
    c = _ctrl(p95_cap_ms=200.0)
    slow = [Sample(200, 500.0) for _ in range(10)]  # success but over the latency cap
    rnd = c.observe(slow, elapsed_s=1.0)
    check("round over the p95 cap is NOT SLO-OK", rnd["slo_ok"] is False)
    check("no gold credited when latency cap is breached", c.gold is None)


def test_kill_switch_parks_endpoint() -> None:
    c = _ctrl(kill_after=4, cooldown_s=900.0, max_delay=30.0)
    c.concurrency = 1
    c.delay_s = c.max_delay  # already at the gentlest config (the floor)
    check("not parked initially", not c.is_parked())
    for _ in range(4):  # kill_after consecutive bad rounds at the floor
        c.observe(_transient(), elapsed_s=1.0)
    check("endpoint parked after sustained errors at the floor", c.is_parked())
    check("parked_until is in the future", c.parked_until > time.monotonic())


def main() -> int:
    print("rate_finder controller tests")
    test_sample_classification()
    test_gold_spot_after_confirmation()
    test_backoff_on_transient()
    test_permanent_404_is_not_load_failure()
    test_p95_cap_enforced()
    test_kill_switch_parks_endpoint()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
