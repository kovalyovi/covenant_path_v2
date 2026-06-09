"""
Offline tests for the per-endpoint controller in tools/rate_finder.py.

No network, deterministic (a FakeClock + a simulated RecoveringServer): we assert the two-timescale
logic — (1) the AIMD gold-spot search + the 100%-stability (zero-error) rate, and (2) outage
EPISODES with active recovery probing that measures exactly how long a 500-storm lasts and how many
requests it takes to get out. Run: python tools/test_rate_finder.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rate_finder import EndpointController, Episode, Sample  # noqa: E402

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


class FakeClock:
    """Deterministic monotonic clock the controller reads via its injected `clock`."""
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class RecoveringServer:
    """A server that 500s for `recovery_s` after it's tripped, then serves 200s again — so we can
    test that the recovery prober measures the outage length and the request count."""
    def __init__(self, clock: FakeClock, recovery_s: float) -> None:
        self.clock = clock
        self.recovery_s = recovery_s
        self.tripped_at: float | None = None

    def trip(self) -> None:
        self.tripped_at = self.clock()

    def _down(self) -> bool:
        return self.tripped_at is not None and self.clock() < self.tripped_at + self.recovery_s

    def probe(self) -> Sample:
        return Sample(503, 100.0) if self._down() else Sample(200, 80.0)


def _ctrl(**kw) -> EndpointController:
    defaults = dict(success_target=0.99, p95_cap_ms=None, max_concurrency=6,
                    min_delay=0.2, max_delay=30.0, window=10, confirm=3,
                    cooldown_s=900.0, kill_after=4, stability_confirm=5,
                    recovery_min=30.0, recovery_max=600.0, recovery_confirm=2)
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
    c.observe(_ok(), elapsed_s=1.0)
    c.observe(_ok(), elapsed_s=1.0)
    check("no gold before the confirmation streak completes", c.gold is None)
    check("pressure unchanged before confirm", c.delay_s == start_delay and c.concurrency == 1)
    c.observe(_ok(), elapsed_s=1.0)
    check("gold spot credited after confirm clean rounds", c.gold is not None)
    check("gold records the throughput", c.gold and c.gold.per_min > 0)
    check("pressure increased (delay reduced) after gold", c.delay_s < start_delay)


def test_stable_rate_zero_errors() -> None:
    # The 100%-stability headline: the highest rate sustained with ZERO errors over stability_confirm
    # rounds. One transient error resets the streak so a flake never gets called "stable".
    c = _ctrl(stability_confirm=5)
    for _ in range(4):
        c.observe(_ok(n=10), elapsed_s=1.0)  # 600/min, clean
    check("no stable rate before the zero-error streak completes", c.stable_rate_per_min is None)
    c.observe(_ok(n=10), elapsed_s=1.0)  # 5th clean round
    check("stable rate banked after the zero-error streak", c.stable_rate_per_min == 600.0)
    s = c.summary()
    check("stable_interval_s is the reciprocal (1 per 0.1s @ 600/min)", s["stable_interval_s"] == 0.1)
    # A single error resets the streak.
    c.observe(_transient(n=10), elapsed_s=1.0)
    check("zero-error streak resets on a transient error", c.zero_streak == 0)


def test_backoff_on_transient() -> None:
    c = _ctrl()
    c.concurrency = 3
    c.observe(_transient(), elapsed_s=1.0)
    check("transient error backs concurrency off", c.concurrency == 2)
    check("first_error_per_min recorded", c.first_error_per_min is not None)
    check("healthy streak reset on error", c.healthy_streak == 0)


def test_permanent_404_is_not_load_failure() -> None:
    c = _ctrl()
    rnd = c.observe(_permanent(), elapsed_s=1.0)
    check("all-404 round is SLO-OK (not a transient failure)", rnd["slo_ok"] is True)
    check("404 round does not set first_error", c.first_error_per_min is None)


def test_p95_cap_enforced() -> None:
    c = _ctrl(p95_cap_ms=200.0)
    slow = [Sample(200, 500.0) for _ in range(10)]
    rnd = c.observe(slow, elapsed_s=1.0)
    check("round over the p95 cap is NOT SLO-OK", rnd["slo_ok"] is False)
    check("no gold credited when latency cap is breached", c.gold is None)


def test_outage_opens_episode_at_floor() -> None:
    clock = FakeClock()
    c = _ctrl(kill_after=2, clock=clock)
    c.concurrency = 1
    c.delay_s = c.max_delay  # at the gentlest config (the floor)
    check("not in an outage initially", not c.in_episode())
    c.observe(_transient(), elapsed_s=1.0)
    c.observe(_transient(), elapsed_s=1.0)  # kill_after reached at the floor
    check("outage episode opens when even the floor fails", c.in_episode())
    check("is_parked() True during an outage (normal rounds suspended)", c.is_parked())
    check("recovery probe NOT due immediately (waits recovery_min)", not c.due_for_recovery_probe())
    clock.advance(30.0)
    check("recovery probe due after recovery_min elapses", c.due_for_recovery_probe())


def test_recovery_measures_outage_duration_and_requests() -> None:
    # The headline recovery question: a 500-storm starts; how long until it recovers? Server is down
    # for 300s. The prober single-probes at widening intervals and must measure ~300s + count probes.
    clock = FakeClock()
    server = RecoveringServer(clock, recovery_s=300.0)
    # recovery_max caps the probe spacing → bounds the measurement granularity (here ≤60s late).
    c = _ctrl(kill_after=2, clock=clock, recovery_min=30.0, recovery_max=60.0, recovery_confirm=2)
    c.concurrency = 1
    c.delay_s = c.max_delay
    onset = clock()
    server.trip()
    c.observe(_transient(), elapsed_s=1.0)
    c.observe(_transient(), elapsed_s=1.0)
    check("episode open at outage onset", c.in_episode())

    guard = 0
    while c.in_episode() and guard < 1000:
        guard += 1
        clock.t = c.next_probe_at      # jump to the next scheduled probe
        c.record_recovery_probe(server.probe())
    check("outage eventually declared recovered", not c.in_episode())
    ep = c.episodes[-1]
    check("recovery duration measured at/after the true 300s outage", ep.duration_s >= 300.0)
    check("recovery duration is reasonably tight (within a few probe intervals)", ep.duration_s <= 420.0)
    check("the outage recorded its probe count", ep.probes > 0)
    check("episode recorded onset rate", ep.onset_rate_per_min is not None)
    check("after recovery the controller resumes gently (c=1)", c.concurrency == 1)
    check("recovery stats expose median outage length", c.summary()["recovery"]["median_s"] is not None)


def test_recovery_probe_interval_widens_on_continued_failure() -> None:
    # A LONG outage (10 min vs 10 hours): the probe interval must widen so we don't hammer a dead
    # endpoint, capped at recovery_max.
    clock = FakeClock()
    c = _ctrl(kill_after=1, clock=clock, recovery_min=30.0, recovery_max=240.0, recovery_confirm=2)
    c.concurrency = 1
    c.delay_s = c.max_delay
    c.observe(_transient(), elapsed_s=1.0)  # opens the episode
    intervals = []
    for _ in range(8):
        clock.t = c.next_probe_at
        c.record_recovery_probe(Sample(503, 100.0))  # still down
        intervals.append(c._recovery_interval)
    check("probe interval grows while the outage persists", intervals[0] < intervals[-1])
    check("probe interval is capped at recovery_max", max(intervals) <= 240.0)


def test_total_requests_counted() -> None:
    clock = FakeClock()
    c = _ctrl(kill_after=1, clock=clock)
    c.observe(_ok(n=10), elapsed_s=1.0)         # 10
    c.concurrency = 1
    c.delay_s = c.max_delay
    c.observe(_transient(n=5), elapsed_s=1.0)   # +5 -> opens episode
    clock.advance(30.0)
    c.record_recovery_probe(Sample(503, 100.0))  # +1
    check("total_requests counts rounds and recovery probes", c.total_requests == 16)


def test_resume_seeds_stability_and_episodes() -> None:
    c = _ctrl()
    c.seed({
        "gold_spot": {"concurrency": 3, "delay_s": 0.5, "per_min": 240.0,
                      "success": 1.0, "p50_ms": 120, "p95_ms": 300},
        "stable_rate_per_min": 120.0,
        "observed_ceiling_per_min": 240.0,
        "first_error_per_min": 300.0,
        "episodes": [{"onset_iso": "2026-06-09T02:00:00+00:00", "onset_rate_per_min": 300.0,
                      "requests_before": 5, "probes": 4, "duration_s": 280.0,
                      "recovered_iso": "2026-06-09T02:04:40+00:00"}],
        "success_by_hour": {"2": 1.0},
    })
    check("resume adopts the prior gold spot", c.gold is not None and c.gold.per_min == 240.0)
    check("resume carries the 100%-stable rate", c.stable_rate_per_min == 120.0)
    check("resume carries prior outage episodes", len(c.episodes) == 1 and c.episodes[0].duration_s == 280.0)
    check("resume carries first_error rate", c.first_error_per_min == 300.0)


def main() -> int:
    print("rate_finder controller tests")
    test_sample_classification()
    test_gold_spot_after_confirmation()
    test_stable_rate_zero_errors()
    test_backoff_on_transient()
    test_permanent_404_is_not_load_failure()
    test_p95_cap_enforced()
    test_outage_opens_episode_at_floor()
    test_recovery_measures_outage_duration_and_requests()
    test_recovery_probe_interval_widens_on_continued_failure()
    test_total_requests_counted()
    test_resume_seeds_stability_and_episodes()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
