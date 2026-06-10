"""
Per-endpoint "gold spot" finder for the flaky LCR endpoints.

WHY (companion to tools/endpoint_probe.py): `endpoint_probe.py` ramps a *single global* rate
across the GET endpoints. But the diagnostics that motivated this (details/{id} ~14% errors →
54/69 field parity, progress-record 21s/flaky, profile POSTs going BLOCKED) showed the real
500-generators are the **per-member** endpoints — the one-work `details/{id}` GET and the
member-profile **POST server actions** — and that each endpoint tolerates a *very different*
request rate. A single global rate is too blunt: it either crawls (pacing for the worst
endpoint) or it floods the flaky ones.

So this tool runs an **independent adaptive controller per endpoint** on TWO timescales:

  • seconds↔1/min — it converges each endpoint on the **100%-STABLE RATE**: the highest sustained
    throughput that holds ZERO errors over N rounds, reported as requests/min AND its reciprocal
    "1 request per X seconds" (the direct answer to "how often can we call without 500s?"). It also
    banks a looser GOLD SPOT (max throughput at ≥target success) and the rate where 500s first bite.

  • minutes↔hours — when even the gentlest rate keeps failing, the endpoint is in an OUTAGE. Instead
    of guessing a cooldown, it opens an EPISODE and single-probes at widening intervals to MEASURE
    exactly how long the 500-storm lasts (10 min? 10 hours?) and how many requests it took to get
    out, then resumes gently. Across days this yields the recovery-time distribution per endpoint.

Designed to run 24h–several days; the output is meant to be read straight into the sync's pacing.

It is deliberately CONSERVATIVE and polite (this hits the real Church servers for days):
  • One endpoint is exercised at a time (round-robin) — total server pressure stays modest and
    the per-endpoint signal isn't confounded by the others stacking on top.
  • AIMD: additive-increase pressure only after a full confirmation window stays clean;
    MULTIPLICATIVE back-off the instant a 5xx/429/timeout appears (TCP-congestion style).
  • Honors `Retry-After`; hard caps on max concurrency and a minimum inter-request delay floor.
  • KILL SWITCH: if an endpoint keeps erroring even at the gentlest config, it's PARKED for a
    long cooldown instead of being hammered.
  • Re-auths if a whole round looks logged-out.
  • Ctrl-C-safe; writes incrementally so a days-long run is never lost.

PII-safe: records endpoint names, unit numbers, member UUIDs (already opaque), status codes and
latencies only — never member data. Reads only: the GETs are reads; the /mlt profile POSTs are
read-via-POST Next.js *server actions* (they fetch profile data, they do not mutate). Pass
`--no-post` to exclude them if you want GET-only.

    python tools/rate_finder.py --hours 48
    python tools/rate_finder.py --hours 72 --p95-cap-ms 8000 --only progress_record,details
    python tools/rate_finder.py --hours 24 --no-post --max-concurrency 4

Output (tools/output/rate_finder/):
    requests_<ts>.jsonl       every request (endpoint, unit/uuid, status, ms, retry_after)
    recommendation_<ts>.json  rolling per-endpoint GOLD SPOT + ceiling + hour-of-day health
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python tools/rate_finder.py` from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client import LcrClient, action_config, member_profile  # noqa: E402
from lcr_client.logging_setup import get_logger  # noqa: E402

logger = get_logger()
LCR = "https://lcr.churchofjesuschrist.org"
OUT = Path(__file__).resolve().parent / "output" / "rate_finder"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------------------------------
# One request's outcome, classified the same way the sync's http_util classifies failures.
# --------------------------------------------------------------------------------------------------

@dataclass
class Sample:
    status: int          # HTTP status, or 0 for a transport error (timeout/conn reset)
    ms: float
    retry_after: int | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def auth_bad(self) -> bool:
        # 401/403 = our SESSION expired/insufficient — NOT an LCR outage. Must trigger a re-auth and
        # be excluded from both the stability denominator and the outage logic, else an expired
        # session masquerades as a permanent "500 storm" and strands the endpoint forever.
        return self.status in (401, 403)

    @property
    def transient_bad(self) -> bool:
        # Retryable failure: server overload / throttle / transport error. These are what we must
        # NOT provoke — the gold spot is the rate that keeps this at zero.
        return self.status in (429, 500, 502, 503, 504, 408) or self.status == 0

    @property
    def permanent_bad(self) -> bool:
        # A deterministic 4xx that is NOT auth (e.g. member-list 404). Not load-related, not session.
        return 400 <= self.status < 500 and self.status not in (429, 408, 401, 403)


# --------------------------------------------------------------------------------------------------
# A probe target: how to fire one request for an endpoint.
# --------------------------------------------------------------------------------------------------

@dataclass
class Target:
    name: str
    is_post: bool
    fire: object  # Callable[(sess, ctx) -> Sample]; ctx = {"unit": int, "member": (uuid, cmis)}
    needs_member: bool = False


def _get(sess, path: str, params: dict | None) -> Sample:
    t0 = time.monotonic()
    try:
        r = sess.get(f"{LCR}{path}", params=params, timeout=45, allow_redirects=False)
        ms = (time.monotonic() - t0) * 1000
        ra = r.headers.get("Retry-After")
        return Sample(r.status_code, ms, int(ra) if str(ra or "").isdigit() else None)
    except Exception:  # noqa: BLE001
        return Sample(0, (time.monotonic() - t0) * 1000)


def _profile_post(sess, uuid: str, action_id: str, args: list) -> Sample:
    """One RAW member-profile server-action POST (no internal retry — we want the true per-call
    outcome). Mirrors member_profile.call_action's request construction exactly."""
    url = member_profile.PROFILE_URL.format(uuid=uuid)
    headers = {
        "Accept": "text/x-component",
        "Content-Type": "text/plain;charset=UTF-8",
        "Next-Action": action_id,
        "Next-Router-State-Tree": member_profile._state_tree(uuid),
        "Origin": LCR,
        "Referer": url,
    }
    body = json.dumps(args, separators=(",", ":"))
    t0 = time.monotonic()
    try:
        r = sess.post(url, headers=headers, data=body, timeout=60, allow_redirects=False)
        ms = (time.monotonic() - t0) * 1000
        ra = r.headers.get("Retry-After")
        return Sample(r.status_code, ms, int(ra) if str(ra or "").isdigit() else None)
    except Exception:  # noqa: BLE001
        return Sample(0, (time.monotonic() - t0) * 1000)


def build_targets(include_post: bool, only: set[str] | None) -> list[Target]:
    acts = action_config.load()
    targets = [
        Target("progress_record", False,
               lambda s, c: _get(s, "/api/report/one-work/progress-record",
                                 {"unitNumber": c["unit"]})),
        Target("details", False, needs_member=True,
               fire=lambda s, c: _get(s, f"/api/report/one-work/details/{c['member'][0]}",
                                      {"legacyCmisId": c["member"][1]})),
        Target("org_callings", False,
               fire=lambda s, c: _get(s, "/mlt/api/orgs", {"unitNumber": c["unit"]})),
        # member-list is the known-dead route — keep it as a CONTROL: it should stay a clean,
        # load-independent 404 (proves the breaker/classification logic, never a back-off trigger).
        Target("member_list", False,
               fire=lambda s, c: _get(s, "/api/umlu/report/member-list",
                                      {"unitNumber": c["unit"]})),
    ]
    if include_post:
        targets += [
            Target("profile_record_POST", True, needs_member=True,
                   fire=lambda s, c: _profile_post(s, c["member"][0], acts["record"],
                                                   [c["member"][0], "eng"])),
            Target("profile_recommend_POST", True, needs_member=True,
                   fire=lambda s, c: _profile_post(s, c["member"][0], acts["recommend"],
                                                   [c["member"][0]])),
        ]
    if only:
        targets = [t for t in targets if t.name in only]
    return targets


# --------------------------------------------------------------------------------------------------
# Per-endpoint adaptive controller — the heart of the gold-spot search.
# --------------------------------------------------------------------------------------------------

@dataclass
class GoldSpot:
    concurrency: int
    delay_s: float
    per_min: float
    success: float
    p50_ms: float
    p95_ms: float


@dataclass
class Episode:
    """A 500-storm/outage: the endpoint is failing even at the gentlest rate. We don't blindly wait a
    fixed cooldown — we actively single-probe at widening intervals to measure EXACTLY how long it
    stays down (recovery could be 10 min or 10 hours) and how many requests it took to get out."""
    onset_iso: str
    onset_rate_per_min: float   # throughput at the moment it broke
    requests_before: int        # requests in the round that tripped it
    probes: int = 0             # recovery single-probes sent during the outage
    duration_s: float | None = None     # measured outage length (None = still ongoing)
    recovered_iso: str | None = None
    gave_up: bool = False       # closed by the probe cap (still failing) rather than a clean recovery
    flaky: bool = False         # saw interspersed successes (chronic flakiness, not a clean storm)


class EndpointController:
    """Two-timescale search for one endpoint's behaviour.

    1. SECONDS↔1/min (normal AIMD rounds): each ROUND issues `window` requests at the current
       (concurrency, delay) and is judged against the SLO. `confirm` clean rounds bank a gold spot
       (max throughput at the target) and push pressure up; a transient error backs off. Crucially we
       also track the STABLE rate — the highest throughput sustained with ZERO errors over
       `stability_confirm` consecutive rounds — which is the "100% stability" answer expressed as
       requests/min (and its reciprocal, 1 request per N seconds).

    2. MINUTES↔HOURS (recovery probing): when even the gentlest round keeps failing, the endpoint is
       in an OUTAGE. Instead of a blind cooldown, we open an Episode and single-probe at widening
       intervals (recovery_min → ×1.5 → recovery_max) so we measure the EXACT recovery time and the
       request count, then resume gently. This is how we learn "after a 500 storm it recovers in ~X".
    """

    def __init__(self, name: str, *, success_target: float, p95_cap_ms: float | None,
                 max_concurrency: int, min_delay: float, max_delay: float,
                 window: int, confirm: int, cooldown_s: float, kill_after: int,
                 stability_confirm: int = 5, recovery_min: float = 30.0,
                 recovery_max: float = 900.0, recovery_confirm: int = 2,
                 max_recovery_probes: int = 24, clock=time.monotonic):
        self.name = name
        self.success_target = success_target
        self.p95_cap_ms = p95_cap_ms
        self.max_concurrency = max_concurrency
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.window = window
        self.confirm = confirm
        self.cooldown_s = cooldown_s
        self.kill_after = kill_after
        self.stability_confirm = stability_confirm   # zero-error rounds to bank a 100%-stable rate
        self.recovery_min = recovery_min             # first recovery-probe interval (s)
        self.recovery_max = recovery_max             # widest recovery-probe interval (s)
        self.recovery_confirm = recovery_confirm     # consecutive probe successes to declare recovery
        self.max_recovery_probes = max_recovery_probes  # cap probes per outage so we never strand
        self.clock = clock                           # injectable for deterministic tests

        # current pressure — start gentle
        self.concurrency = 1
        self.delay_s = max(min_delay, 1.5)

        self.gold: GoldSpot | None = None
        self.stable_rate_per_min: float | None = None    # highest ZERO-error sustained throughput
        self.ceiling_per_min: float | None = None        # highest throughput ever attempted clean
        self.first_error_per_min: float | None = None     # throughput where errors first appeared
        self.total_requests = 0                           # every request this endpoint has issued
        self.healthy_streak = 0
        self.zero_streak = 0                              # consecutive ZERO-error rounds (stability)
        self.bad_streak = 0
        self.parked_until = 0.0                          # coarse bound; episodes are the real gate

        # FLOOR error rate: error % observed at the GENTLEST rate (concurrency=1, max delay). If this
        # is > 0 the endpoint errors even when barely touched → 100% stability is NOT achievable by
        # rate-limiting alone (it needs retries/caching/off-peak). The killer metric for "can we
        # actually hit 100%?".
        self.floor_attempts = 0
        self.floor_errors = 0
        self.needs_reauth = False                         # set when a round/probe sees 401/403

        # outage / recovery state
        self.episodes: list[Episode] = []
        self.current_episode: Episode | None = None
        self._episode_start = 0.0
        self._recovery_interval = 0.0
        self._recovery_ok_streak = 0
        self._recovery_successes = 0                      # total probe successes this episode (flaky)
        self.next_probe_at = 0.0

        self.rounds: list[dict] = []
        # rolling per-hour health (diurnal: is LCR healthier at 2am? schedule the sync there)
        self.by_hour_ok: dict[int, int] = defaultdict(int)
        self.by_hour_total: dict[int, int] = defaultdict(int)

    # -- scheduling ----------------------------------------------------------
    def in_episode(self) -> bool:
        return self.current_episode is not None

    def is_parked(self) -> bool:
        """True while we should NOT run normal rounds — i.e. during an outage episode (recovery
        probing takes over) or the coarse cooldown bound."""
        return self.in_episode() or self.clock() < self.parked_until

    def due_for_recovery_probe(self, now: float | None = None) -> bool:
        now = self.clock() if now is None else now
        return self.in_episode() and now >= self.next_probe_at

    # -- evaluate one round of samples --------------------------------------
    def observe(self, samples: list[Sample], elapsed_s: float) -> dict:
        n = len(samples)
        ok = sum(1 for s in samples if s.ok)
        transient = sum(1 for s in samples if s.transient_bad)
        permanent = sum(1 for s in samples if s.permanent_bad)
        auth = sum(1 for s in samples if s.auth_bad)
        lat = sorted(s.ms for s in samples if s.ok)
        p50 = lat[len(lat) // 2] if lat else 0.0
        p95 = lat[int(len(lat) * 0.95)] if lat else 0.0
        per_min = n / elapsed_s * 60 if elapsed_s else 0.0
        # Success is measured over COUNTABLE responses — excluding a deterministic 404 (dead route,
        # load-independent) AND a 401/403 (our session, not LCR). Only transient 5xx/429/timeout
        # signal that we pushed too hard.
        countable = n - permanent - auth
        success = ok / countable if countable else 1.0
        zero_err = transient == 0 and ok == countable and countable > 0  # truly clean (100% stability)
        if auth:
            self.needs_reauth = True  # the harness re-authenticates before the next call
        self.total_requests += n
        # Floor error rate: are we erroring even at the gentlest rate? (the "is 100% possible" metric)
        if self._at_floor() and countable:
            self.floor_attempts += countable
            self.floor_errors += transient
        hour = datetime.now().hour
        self.by_hour_total[hour] += n
        self.by_hour_ok[hour] += ok
        max_ra = max((s.retry_after for s in samples if s.retry_after), default=0)

        # SLO: a 404-only / 401-only round is "clean" w.r.t. LOAD — neither is overload.
        slo_ok = (success >= self.success_target and transient == 0
                  and (self.p95_cap_ms is None or not lat or p95 <= self.p95_cap_ms))

        rnd = {
            "t": _now(), "endpoint": self.name, "concurrency": self.concurrency,
            "delay_s": round(self.delay_s, 2), "sent": n, "ok": ok, "success": round(success, 3),
            "transient_err": transient, "permanent": permanent, "auth_err": auth, "p50_ms": round(p50),
            "p95_ms": round(p95), "per_min": round(per_min, 1), "slo_ok": slo_ok,
            "retry_after": max_ra or None,
        }
        self.rounds.append(rnd)
        self._adapt(slo_ok, zero_err, transient, per_min, success, p50, p95, max_ra, n)
        return rnd

    def _adapt(self, slo_ok, zero_err, transient, per_min, success, p50, p95, max_ra, n):
        # 100%-stability tracking, independent of the throughput-maximizing gold spot: the highest
        # rate sustained with ZERO errors over `stability_confirm` rounds is the rate we can trust.
        if zero_err:
            self.zero_streak += 1
            if self.zero_streak >= self.stability_confirm and per_min > (self.stable_rate_per_min or 0):
                self.stable_rate_per_min = round(per_min, 1)
                logger.info("[%s] 100%%-stable rate ↑ %.1f/min (1 per %.0fs) over %d clean rounds",
                            self.name, per_min, 60 / per_min if per_min else 0, self.zero_streak)
        else:
            self.zero_streak = 0

        if max_ra:
            # Server explicitly asked us to slow down — honor it and treat as a back-off signal.
            logger.warning("[%s] Retry-After=%ss — honoring + backing off", self.name, max_ra)
            self._backoff(per_min)
            time.sleep(min(max_ra, 120))
            return

        if slo_ok:
            self.bad_streak = 0
            self.healthy_streak += 1
            self.ceiling_per_min = max(self.ceiling_per_min or 0.0, per_min)
            if self.healthy_streak >= self.confirm:
                # Confirmed safe at this state → bank it as the gold spot (if it's our best
                # sustained throughput), then increase pressure to probe for a higher one.
                if not self.gold or per_min > self.gold.per_min:
                    self.gold = GoldSpot(self.concurrency, round(self.delay_s, 2),
                                         round(per_min, 1), round(success, 3),
                                         round(p50), round(p95))
                    logger.info("[%s] gold spot ↑ %.0f/min @ c=%d delay=%.2fs (p95=%.0fms succ=%.0f%%)",
                                self.name, per_min, self.concurrency, self.delay_s, p95, success * 100)
                self._increase_pressure()
                self.healthy_streak = 0
        else:
            # Any transient error (or SLO miss) → record where it first bit, then back off hard.
            if transient and self.first_error_per_min is None:
                self.first_error_per_min = round(per_min, 1)
            self.healthy_streak = 0
            self.bad_streak += 1
            self._backoff(per_min)
            if self._at_floor() and self.bad_streak >= self.kill_after and not self.in_episode():
                self._start_episode(per_min, n)

    # -- outage episodes + active recovery probing ---------------------------
    def _start_episode(self, per_min: float, n: int) -> None:
        now = self.clock()
        self._episode_start = now
        self.current_episode = Episode(onset_iso=_now(), onset_rate_per_min=round(per_min, 1),
                                       requests_before=n)
        self._recovery_interval = self.recovery_min
        self.next_probe_at = now + self.recovery_min
        self._recovery_ok_streak = 0
        self._recovery_successes = 0
        self.bad_streak = 0
        self.parked_until = now + self.cooldown_s  # coarse bound; recovery probing is the real gate
        logger.warning("[%s] OUTAGE — even the gentlest rate fails; probing for recovery every "
                       "%.0fs (was %.1f/min at onset)", self.name, self.recovery_min, per_min)

    def _close_episode(self, ep: "Episode", now: float, *, gave_up: bool) -> None:
        ep.duration_s = round(now - self._episode_start, 1)
        ep.recovered_iso = _now()
        ep.gave_up = gave_up
        ep.flaky = self._recovery_successes > 0 and not gave_up and ep.probes > self.recovery_confirm
        self.episodes.append(ep)
        verb = "GAVE UP probing" if gave_up else ("RECOVERED (flaky)" if ep.flaky else "RECOVERED")
        logger.warning("[%s] %s after %.0fs (%d probes); resuming gently",
                       self.name, verb, ep.duration_s, ep.probes)
        self.current_episode = None
        self._recovery_ok_streak = 0
        self.parked_until = 0.0
        self.concurrency = 1
        self.delay_s = max(self.min_delay, min(self.max_delay, 5.0))  # resume conservatively
        self.bad_streak = 0

    def note_auth_probe(self, now: float | None = None) -> None:
        """A recovery probe returned 401/403 — that's our SESSION, not an LCR outage. The harness
        re-authenticates; here we just retry SOON (don't widen, don't count as recovery progress) so
        an expired session can never masquerade as a never-ending 500-storm."""
        now = self.clock() if now is None else now
        self.needs_reauth = True
        if self.current_episode is not None:
            self.current_episode.probes += 1
            self.total_requests += 1
        self._recovery_interval = self.recovery_min
        self.next_probe_at = now + self.recovery_min

    def record_recovery_probe(self, sample: "Sample", now: float | None = None) -> None:
        """Feed one recovery single-probe. `recovery_confirm` consecutive successes → outage OVER
        (duration measured). A 401/403 → re-auth path (note_auth_probe), never "still down". A
        transient failure widens the interval (×1.5, capped). After `max_recovery_probes` we GIVE UP
        and resume normal slow rounds, so a chronically-failing endpoint is never stranded forever."""
        if sample.auth_bad:
            self.note_auth_probe(now)
            return
        now = self.clock() if now is None else now
        ep = self.current_episode
        if ep is None:
            return
        ep.probes += 1
        self.total_requests += 1
        if sample.ok:
            self._recovery_ok_streak += 1
            self._recovery_successes += 1
            self._recovery_interval = self.recovery_min  # it's coming back — confirm quickly (precision)
            if self._recovery_ok_streak >= self.recovery_confirm:
                self._close_episode(ep, now, gave_up=False)
                return
        else:
            self._recovery_ok_streak = 0
            self._recovery_interval = min(self.recovery_max, self._recovery_interval * 1.5)
        if ep.probes >= self.max_recovery_probes:
            # Still not cleanly recovered after the cap — stop probing and resume normal rounds (they
            # keep measuring; a chronically-flaky endpoint just never banks a stable rate, which IS
            # the finding). Prevents the 401/permanent-storm strand we caught in the live run.
            self._close_episode(ep, now, gave_up=True)
            return
        self.next_probe_at = now + self._recovery_interval

    def _at_floor(self) -> bool:
        return self.concurrency == 1 and self.delay_s >= self.max_delay - 1e-6

    def _increase_pressure(self):
        # Reduce delay first (cheap), then add a worker. Never below the floor / above the cap.
        if self.delay_s > self.min_delay + 1e-6:
            self.delay_s = max(self.min_delay, self.delay_s * 0.8)
        elif self.concurrency < self.max_concurrency:
            self.concurrency += 1

    def _backoff(self, per_min):
        if self.concurrency > 1:
            self.concurrency -= 1
        else:
            self.delay_s = min(self.max_delay, max(self.delay_s, self.min_delay) * 1.6)

    def seed(self, prior: dict) -> None:
        """Resume from a previous run's summary (for tiled GitHub-Actions runs that each last <6h):
        start at the known-good gold spot instead of re-ramping from concurrency=1 every time."""
        g = (prior or {}).get("gold_spot")
        if g:
            self.gold = GoldSpot(int(g["concurrency"]), float(g["delay_s"]), float(g["per_min"]),
                                 float(g["success"]), float(g["p50_ms"]), float(g["p95_ms"]))
            # Resume gently: at the gold config, but verify before pushing past it again.
            self.concurrency = max(1, int(g["concurrency"]))
            self.delay_s = max(self.min_delay, float(g["delay_s"]))
        if prior.get("observed_ceiling_per_min") is not None:
            self.ceiling_per_min = float(prior["observed_ceiling_per_min"])
        if prior.get("first_error_per_min") is not None:
            self.first_error_per_min = float(prior["first_error_per_min"])
        if prior.get("stable_rate_per_min") is not None:
            self.stable_rate_per_min = float(prior["stable_rate_per_min"])
        for ep in (prior.get("episodes") or []):
            self.episodes.append(Episode(
                onset_iso=ep.get("onset_iso", ""), onset_rate_per_min=ep.get("onset_rate_per_min", 0),
                requests_before=ep.get("requests_before", 0), probes=ep.get("probes", 0),
                duration_s=ep.get("duration_s"), recovered_iso=ep.get("recovered_iso")))
        for h, rate in (prior.get("success_by_hour") or {}).items():
            # carry forward as a single weighted point so diurnal coverage accumulates across runs
            self.by_hour_total[int(h)] += 100
            self.by_hour_ok[int(h)] += int(round(float(rate) * 100))

    def _recovery_stats(self) -> dict:
        done = [e.duration_s for e in self.episodes if e.duration_s is not None]
        return {
            "outages": len(self.episodes) + (1 if self.in_episode() else 0),
            "measured": len(done),
            "median_s": round(statistics.median(done), 1) if done else None,
            "max_s": round(max(done), 1) if done else None,
            "min_s": round(min(done), 1) if done else None,
            "ongoing_since": self.current_episode.onset_iso if self.in_episode() else None,
        }

    def floor_error_pct(self) -> float | None:
        """Error % at the GENTLEST rate. None = never reached the floor. 0 = clean even when barely
        touched (100% stability achievable). > 0 = errors persist at the floor → NOT achievable by
        rate alone."""
        return round(100 * self.floor_errors / self.floor_attempts, 1) if self.floor_attempts else None

    def stability_verdict(self) -> str:
        """One-word read on whether 100% stability is reachable for this endpoint by pacing alone."""
        fe = self.floor_error_pct()
        if self.stable_rate_per_min:
            return "achievable"               # found a zero-error sustained rate
        if fe is not None and fe > 0:
            return "not-by-rate"              # errors even at the floor → needs retries/caching/off-peak
        return "unknown"                      # not enough floor data yet

    def summary(self) -> dict:
        hourly = {str(h): round(self.by_hour_ok[h] / self.by_hour_total[h], 3)
                  for h in sorted(self.by_hour_total) if self.by_hour_total[h]}
        stable = self.stable_rate_per_min
        return {
            # THE HEADLINE: the rate that held 100% stability (zero errors), as req/min AND interval.
            "stable_rate_per_min": stable,
            "stable_interval_s": round(60 / stable, 1) if stable else None,
            # can we even reach 100%? error % at the gentlest rate + a one-word verdict.
            "floor_error_pct": self.floor_error_pct(),
            "stability_verdict": self.stability_verdict(),
            "gold_spot": None if not self.gold else self.gold.__dict__,
            "observed_ceiling_per_min": self.ceiling_per_min,
            "first_error_per_min": self.first_error_per_min,
            "total_requests": self.total_requests,
            # recovery: how long 500-storms last once they start (10 min? 10 hours?)
            "recovery": self._recovery_stats(),
            "episodes": [e.__dict__ for e in self.episodes[-20:]],
            "current": {"concurrency": self.concurrency, "delay_s": round(self.delay_s, 2)},
            "in_episode": self.in_episode(),
            "rounds": len(self.rounds),
            "success_by_hour": hourly,
            "recent_rounds": self.rounds[-8:],
        }


# --------------------------------------------------------------------------------------------------
# Harness: bootstrap, schedule round-robin rounds, persist.
# --------------------------------------------------------------------------------------------------

class Harness:
    def __init__(self, ts: str, args):
        self.args = args
        self.jsonl = (OUT / f"requests_{ts}.jsonl").open("a", encoding="utf-8")
        self.rec_path = OUT / f"recommendation_{ts}.json"
        self._lock = threading.Lock()
        self.client = LcrClient()
        me = self.client.whoami()
        logger.info("authenticated as %s", me.preferred_username)
        ctx = self.client.user_context()
        self.units = args.units or [u.unit_number for u in ctx.child_units if u.unit_number] \
            or [ctx.unit_number]
        logger.info("rate-finding across %d unit(s)", len(self.units))
        self.members = self._sample_members(args.members_per_unit)
        self.targets = build_targets(include_post=not args.no_post, only=args.only)
        for t in self.targets:
            if t.needs_member and not self.members:
                logger.warning("no member ids harvested — skipping member endpoint %s", t.name)
        self.targets = [t for t in self.targets if not (t.needs_member and not self.members)]
        self.ctrls = {t.name: EndpointController(
            t.name, success_target=args.success_target, p95_cap_ms=args.p95_cap_ms,
            max_concurrency=args.max_concurrency, min_delay=args.min_delay,
            max_delay=args.max_delay, window=args.window, confirm=args.confirm,
            cooldown_s=args.cooldown, kill_after=args.kill_after,
            stability_confirm=args.stability_confirm, recovery_min=args.recovery_probe_min,
            recovery_max=args.recovery_probe_max, recovery_confirm=args.recovery_confirm,
            max_recovery_probes=args.max_recovery_probes)
            for t in self.targets}
        if args.resume:
            self._resume(args.resume)

    def _resume(self, path_arg: str) -> None:
        """Seed controllers from a prior recommendation.json so tiled (<6h) runs accumulate. Pass a
        path, or 'auto' to pick the most recent recommendation_*.json in the output dir."""
        path = None
        if path_arg == "auto":
            prior = sorted(OUT.glob("recommendation_*.json"))
            path = prior[-1] if prior else None
        else:
            cand = Path(path_arg)
            path = cand if cand.exists() else None
        if not path:
            logger.info("resume: no prior recommendation found (starting fresh)")
            return
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            for name, summ in (doc.get("endpoints") or {}).items():
                if name in self.ctrls:
                    self.ctrls[name].seed(summ)
            logger.info("resumed gold spots from %s", path.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("resume failed (%s) — starting fresh", exc)

    def _sample_members(self, per_unit: int) -> list[tuple[str, object]]:
        """Harvest real (person_uuid, legacyCmisId) pairs from one progress-record per unit — these
        feed the per-member details/profile probes. Bounded so we don't read every unit's whole roster."""
        out: list[tuple[str, object]] = []
        for u in self.units:
            try:
                rec = self.client.progress_record(u)
                people = (rec.new_members + rec.returning_members + rec.investigators)
                ids = [(p.person_uuid, p.cmis_id) for p in people if p.person_uuid][:per_unit]
                out.extend(ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("member harvest failed for unit %s: %s", u, exc)
        logger.info("harvested %d member id(s) for per-member endpoints", len(out))
        return out

    def _ctx(self, target: Target) -> dict:
        return {"unit": random.choice(self.units),
                "member": random.choice(self.members) if (target.needs_member and self.members) else None}

    def run_round(self, target: Target, ctrl: EndpointController) -> None:
        sess = self.client.session.session
        n = ctrl.window
        samples: list[Sample] = []
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=ctrl.concurrency) as ex:
            futures = []
            for _ in range(n):
                futures.append(ex.submit(target.fire, sess, self._ctx(target)))
                time.sleep(ctrl.delay_s)  # pace submissions to the target inter-request delay
            for f in futures:
                samples.append(f.result())
        elapsed = time.monotonic() - start
        with self._lock:
            for s in samples:
                self.jsonl.write(json.dumps({"t": _now(), "endpoint": target.name,
                                             "status": s.status, "ms": round(s.ms)}) + "\n")
        rnd = ctrl.observe(samples, elapsed)
        logger.info("[%s] c=%d delay=%.2fs -> %.0f%% ok, %d transient, %d auth, p95=%dms, %.0f/min%s",
                    target.name, rnd["concurrency"], rnd["delay_s"], rnd["success"] * 100,
                    rnd["transient_err"], rnd["auth_err"], rnd["p95_ms"], rnd["per_min"],
                    "  SLO-OK" if rnd["slo_ok"] else "")
        # 401/403 anywhere → our session lapsed (NOT an LCR outage). Re-authenticate so a dead session
        # never masquerades as a 500-storm. (This was the live bug: 3 endpoints stuck on 401s forever.)
        if ctrl.needs_reauth or (rnd["success"] == 0 and rnd["transient_err"] == 0 and rnd["permanent"] < n):
            self._reauth(target.name)
            ctrl.needs_reauth = False
        self.persist()

    def _reauth(self, who: str) -> None:
        logger.warning("[%s] 401/403 — refreshing the LCR session", who)
        try:
            self.client = LcrClient()
            logger.info("session refreshed")
        except Exception as exc:  # noqa: BLE001
            logger.error("re-auth failed: %s", exc)

    def persist(self) -> None:
        with self._lock:
            doc = {
                "updated": _now(),
                "note": "stable_rate_per_min / stable_interval_s = the rate that held 100%% stability "
                        "(ZERO errors over N rounds) — the safe pace ('1 request per X seconds'). "
                        "floor_error_pct = error %% at the gentlest rate; stability_verdict: "
                        "'achievable' (found a zero-error rate) / 'not-by-rate' (errors even at the "
                        "floor → needs retries/caching/off-peak) / 'unknown'. gold_spot = max "
                        "throughput at the looser SLO. recovery = how long 500-storms last (active "
                        "probing during an outage); episodes carry gave_up/flaky flags.",
                "slo": {"success_target": self.args.success_target,
                        "p95_cap_ms": self.args.p95_cap_ms,
                        "stability_confirm": self.args.stability_confirm},
                "endpoints": {name: c.summary() for name, c in self.ctrls.items()},
            }
            self.rec_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    def run_recovery_probe(self, target: Target, ctrl: EndpointController) -> None:
        """Fire ONE request against an endpoint that's in an outage, to detect/measure recovery."""
        sess = self.client.session.session
        sample = target.fire(sess, self._ctx(target))
        with self._lock:
            self.jsonl.write(json.dumps({"t": _now(), "endpoint": target.name, "probe": True,
                                         "status": sample.status, "ms": round(sample.ms)}) + "\n")
        ctrl.record_recovery_probe(sample)
        if sample.auth_bad:
            # 401 during recovery = our session, not LCR — re-auth so the NEXT probe is real.
            self._reauth(target.name)
            ctrl.needs_reauth = False
            logger.info("[%s] recovery probe: status=%s (auth — re-authed) — retry in %.0fs",
                        target.name, sample.status, ctrl._recovery_interval)
        elif ctrl.in_episode():
            logger.info("[%s] recovery probe: status=%s (still down) — next in %.0fs",
                        target.name, sample.status, ctrl._recovery_interval)
        self.persist()

    def loop(self, hours: float) -> None:
        deadline = time.monotonic() + hours * 3600
        i = 0
        try:
            while time.monotonic() < deadline:
                progressed = False
                # one pass over all endpoints; act on the first that's actionable (a normal round if
                # healthy, or a recovery probe if it's in an outage and a probe is due).
                for k in range(len(self.targets)):
                    target = self.targets[(i + k) % len(self.targets)]
                    ctrl = self.ctrls[target.name]
                    if ctrl.in_episode():
                        if ctrl.due_for_recovery_probe():
                            self.run_recovery_probe(target, ctrl)
                            i = (i + k + 1) % len(self.targets)
                            progressed = True
                            break
                    elif not ctrl.is_parked():
                        self.run_round(target, ctrl)
                        i = (i + k + 1) % len(self.targets)
                        progressed = True
                        break
                if not progressed:
                    # everything is mid-outage and no probe is due yet — sleep until the soonest one.
                    waits = [self.ctrls[t.name].next_probe_at - time.monotonic()
                             for t in self.targets if self.ctrls[t.name].in_episode()]
                    nap = max(2.0, min(30.0, min(waits))) if waits else 15.0
                    time.sleep(nap)
        except KeyboardInterrupt:
            logger.info("interrupted — writing final recommendation")
        finally:
            self.persist()
            self.jsonl.close()
            logger.info("done. recommendation -> %s", self.rec_path)
            for name, c in self.ctrls.items():
                stable = c.stable_rate_per_min
                rec = c._recovery_stats()
                logger.info("  %-22s stable=%-22s floor_err=%s%% verdict=%s  outages=%d (median %ss)",
                            name,
                            f"{stable:.1f}/min (1 per {60 / stable:.0f}s)" if stable else "none-found",
                            c.floor_error_pct(), c.stability_verdict(),
                            rec["outages"], rec["median_s"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--units", type=lambda s: [int(x) for x in s.split(",") if x], default=None,
                    help="comma list of unit numbers (default: all child units)")
    ap.add_argument("--only", type=lambda s: set(x.strip() for x in s.split(",") if x), default=None,
                    help="restrict to these endpoint names")
    ap.add_argument("--no-post", action="store_true", help="exclude the /mlt profile POST actions")
    ap.add_argument("--members-per-unit", type=int, default=8)
    ap.add_argument("--success-target", type=float, default=0.99)
    ap.add_argument("--p95-cap-ms", type=float, default=None, help="optional p95 latency SLO")
    ap.add_argument("--max-concurrency", type=int, default=6)
    ap.add_argument("--min-delay", type=float, default=0.2, help="floor inter-request delay (s)")
    ap.add_argument("--max-delay", type=float, default=30.0, help="gentlest delay before kill switch")
    ap.add_argument("--window", type=int, default=12, help="requests per measurement round")
    ap.add_argument("--confirm", type=int, default=3, help="clean rounds to confirm a gold spot")
    ap.add_argument("--cooldown", type=float, default=900.0, help="coarse park bound after an outage (s)")
    ap.add_argument("--kill-after", type=int, default=4, help="bad rounds at floor before declaring an outage")
    ap.add_argument("--stability-confirm", type=int, default=5,
                    help="consecutive ZERO-error rounds to bank a 100%%-stable rate")
    ap.add_argument("--recovery-probe-min", type=float, default=30.0,
                    help="first recovery-probe interval during an outage (s)")
    ap.add_argument("--recovery-probe-max", type=float, default=900.0,
                    help="widest recovery-probe interval (s) — caps how often we poke a long outage")
    ap.add_argument("--recovery-confirm", type=int, default=2,
                    help="consecutive probe successes to declare an outage recovered")
    ap.add_argument("--max-recovery-probes", type=int, default=24,
                    help="cap probes per outage, then give up + resume normal rounds (never strand)")
    ap.add_argument("--resume", default=None,
                    help="seed gold spots from a prior recommendation.json (path, or 'auto' for the "
                         "latest in the output dir) — for tiled GitHub-Actions runs")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("rate finder: %.1fh, target≥%.0f%% success, max c=%d, delay floor %.2fs",
                args.hours, args.success_target * 100, args.max_concurrency, args.min_delay)
    Harness(ts, args).loop(args.hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
