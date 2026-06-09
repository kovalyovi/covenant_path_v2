"""
Per-endpoint "gold spot" finder for the flaky LCR endpoints.

WHY (companion to tools/endpoint_probe.py): `endpoint_probe.py` ramps a *single global* rate
across the GET endpoints. But the diagnostics that motivated this (details/{id} ~14% errors →
54/69 field parity, progress-record 21s/flaky, profile POSTs going BLOCKED) showed the real
500-generators are the **per-member** endpoints — the one-work `details/{id}` GET and the
member-profile **POST server actions** — and that each endpoint tolerates a *very different*
request rate. A single global rate is too blunt: it either crawls (pacing for the worst
endpoint) or it floods the flaky ones.

So this tool runs an **independent adaptive controller per endpoint** and converges each on its
own GOLD SPOT: the highest sustained throughput (concurrency + inter-request delay) that holds
the success SLO (default ≥99% success, no 5xx/429/timeout, optional p95 latency cap) across a
multi-window confirmation — i.e. the safe rate that *satisfies our needs without tripping 500s*.
Designed to run 24–72h; the output is meant to be read straight into the sync's pacing config.

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
    def transient_bad(self) -> bool:
        # Retryable failure: server overload / throttle / transport error. These are what we must
        # NOT provoke — the gold spot is the rate that keeps this at zero.
        return self.status in (429, 500, 502, 503, 504, 408) or self.status == 0

    @property
    def permanent_bad(self) -> bool:
        # A deterministic 4xx (e.g. member-list 404). Not load-related — never back off for it.
        return 400 <= self.status < 500 and self.status not in (429, 408)


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


class EndpointController:
    """AIMD search for one endpoint's safe operating point.

    State = (concurrency, delay_s). Each ROUND issues `window` requests at the current state and is
    judged against the SLO (success ≥ target, no transient errors, optional p95 cap). `confirm`
    consecutive clean rounds at a state CREDIT it as a candidate gold spot and push pressure up
    (less delay, then more concurrency). Any transient error backs pressure off immediately. Sticking
    at the gentlest state while still erroring trips the kill switch → park for a cooldown.
    """

    def __init__(self, name: str, *, success_target: float, p95_cap_ms: float | None,
                 max_concurrency: int, min_delay: float, max_delay: float,
                 window: int, confirm: int, cooldown_s: float, kill_after: int):
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

        # current pressure — start gentle
        self.concurrency = 1
        self.delay_s = max(min_delay, 1.5)

        self.gold: GoldSpot | None = None
        self.ceiling_per_min: float | None = None        # highest throughput ever attempted clean
        self.first_error_per_min: float | None = None     # throughput where errors first appeared
        self.healthy_streak = 0
        self.bad_streak = 0
        self.parked_until = 0.0
        self.rounds: list[dict] = []
        # rolling per-hour health (diurnal: is LCR healthier at 2am? schedule the sync there)
        self.by_hour_ok: dict[int, int] = defaultdict(int)
        self.by_hour_total: dict[int, int] = defaultdict(int)

    # -- scheduling ----------------------------------------------------------
    def is_parked(self) -> bool:
        return time.monotonic() < self.parked_until

    # -- evaluate one round of samples --------------------------------------
    def observe(self, samples: list[Sample], elapsed_s: float) -> dict:
        n = len(samples)
        ok = sum(1 for s in samples if s.ok)
        transient = sum(1 for s in samples if s.transient_bad)
        permanent = sum(1 for s in samples if s.permanent_bad)
        lat = sorted(s.ms for s in samples if s.ok)
        p50 = lat[len(lat) // 2] if lat else 0.0
        p95 = lat[int(len(lat) * 0.95)] if lat else 0.0
        per_min = n / elapsed_s * 60 if elapsed_s else 0.0
        # Success is measured over NON-PERMANENT responses: a deterministic 404 (dead member-list
        # route) is load-independent, so an all-404 round is "clean" (no overload) and must not drag
        # the SLO down or trigger back-off. Only transient 5xx/429/timeout signal that we pushed too
        # hard.
        non_permanent = n - permanent
        success = ok / non_permanent if non_permanent else 1.0
        hour = datetime.now().hour
        self.by_hour_total[hour] += n
        self.by_hour_ok[hour] += ok
        max_ra = max((s.retry_after for s in samples if s.retry_after), default=0)

        # SLO: a 404-only endpoint (member-list control) is "clean" — permanent != load failure.
        slo_ok = (success >= self.success_target and transient == 0
                  and (self.p95_cap_ms is None or not lat or p95 <= self.p95_cap_ms))

        rnd = {
            "t": _now(), "endpoint": self.name, "concurrency": self.concurrency,
            "delay_s": round(self.delay_s, 2), "sent": n, "ok": ok, "success": round(success, 3),
            "transient_err": transient, "permanent": permanent, "p50_ms": round(p50),
            "p95_ms": round(p95), "per_min": round(per_min, 1), "slo_ok": slo_ok,
            "retry_after": max_ra or None,
        }
        self.rounds.append(rnd)
        self._adapt(slo_ok, transient, per_min, success, p50, p95, max_ra)
        return rnd

    def _adapt(self, slo_ok, transient, per_min, success, p50, p95, max_ra):
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
            if self._at_floor() and self.bad_streak >= self.kill_after:
                self.parked_until = time.monotonic() + self.cooldown_s
                self.bad_streak = 0
                logger.warning("[%s] still erroring at the floor — PARKING for %.0fs (kill switch)",
                               self.name, self.cooldown_s)

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

    def summary(self) -> dict:
        hourly = {str(h): round(self.by_hour_ok[h] / self.by_hour_total[h], 3)
                  for h in sorted(self.by_hour_total) if self.by_hour_total[h]}
        return {
            "gold_spot": None if not self.gold else self.gold.__dict__,
            "observed_ceiling_per_min": self.ceiling_per_min,
            "first_error_per_min": self.first_error_per_min,
            "current": {"concurrency": self.concurrency, "delay_s": round(self.delay_s, 2)},
            "parked": self.is_parked(),
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
            cooldown_s=args.cooldown, kill_after=args.kill_after) for t in self.targets}

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
        logger.info("[%s] c=%d delay=%.2fs -> %.0f%% ok, %d transient, p95=%dms, %.0f/min%s",
                    target.name, rnd["concurrency"], rnd["delay_s"], rnd["success"] * 100,
                    rnd["transient_err"], rnd["p95_ms"], rnd["per_min"],
                    "  SLO-OK" if rnd["slo_ok"] else "")
        # Re-auth guard: a whole round of redirects/401s means the session lapsed.
        if rnd["success"] == 0 and rnd["transient_err"] == 0 and rnd["permanent"] < n:
            logger.warning("[%s] round fully unauthenticated — refreshing session", target.name)
            try:
                self.client = LcrClient()
            except Exception as exc:  # noqa: BLE001
                logger.error("re-auth failed: %s", exc)
        self.persist()

    def persist(self) -> None:
        with self._lock:
            doc = {
                "updated": _now(),
                "note": "gold_spot = highest sustained throughput holding the SLO (success>=target, "
                        "no 5xx/429/timeout, p95<=cap). Use concurrency+delay_s as the sync's "
                        "per-endpoint pacing. first_error_per_min = where 500s began.",
                "slo": {"success_target": self.args.success_target,
                        "p95_cap_ms": self.args.p95_cap_ms},
                "endpoints": {name: c.summary() for name, c in self.ctrls.items()},
            }
            self.rec_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    def loop(self, hours: float) -> None:
        deadline = time.monotonic() + hours * 3600
        i = 0
        try:
            while time.monotonic() < deadline:
                active = [t for t in self.targets if not self.ctrls[t.name].is_parked()]
                if not active:
                    logger.info("all endpoints parked — sleeping 60s")
                    time.sleep(60)
                    continue
                target = active[i % len(active)]
                i += 1
                self.run_round(target, self.ctrls[target.name])
        except KeyboardInterrupt:
            logger.info("interrupted — writing final recommendation")
        finally:
            self.persist()
            self.jsonl.close()
            logger.info("done. recommendation -> %s", self.rec_path)
            for name, c in self.ctrls.items():
                g = c.gold
                logger.info("  %-22s gold=%s ceiling=%.0f/min first_error=%s",
                            name, f"{g.per_min:.0f}/min c={g.concurrency} d={g.delay_s}s" if g else "none",
                            c.ceiling_per_min or 0.0, c.first_error_per_min)


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
    ap.add_argument("--cooldown", type=float, default=900.0, help="park duration after kill switch (s)")
    ap.add_argument("--kill-after", type=int, default=4, help="bad rounds at floor before parking")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("rate finder: %.1fh, target≥%.0f%% success, max c=%d, delay floor %.2fs",
                args.hours, args.success_target * 100, args.max_concurrency, args.min_delay)
    Harness(ts, args).loop(args.hours)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
