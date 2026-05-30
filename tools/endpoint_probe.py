"""
Adaptive LCR endpoint rate-limit probe.

Goal: learn each read endpoint's *sustainable* request rate and the nature of the 404/500s we see
under load (member-list 404, progress-record 500), so the daily sync can pace itself to ~100%
success instead of losing units. Authenticates once, then runs rounds of increasing load against
the operator's own units (read-only GETs), recording every request's status + latency + any
Retry-After to a JSONL. Adaptive: it ramps up while success stays high and backs OFF hard the
moment it sees throttling — so it characterizes the ceiling without hammering past it (which could
trip a lockout). Designed to run for many hours; Ctrl-C-safe; resumable.

    python tools/endpoint_probe.py --hours 12
    python tools/endpoint_probe.py --hours 24 --max-rate 600

PII-safe: records unit numbers, endpoint names, status codes, latencies only — never member data.
Output:
    tools/output/probe/probe_<ts>.jsonl     every request
    tools/output/probe/summary_<ts>.json    rolling per-endpoint/per-rate success table
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Allow `python tools/endpoint_probe.py` from anywhere: put the repo root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client import LcrClient  # noqa: E402
from lcr_client.logging_setup import get_logger  # noqa: E402

logger = get_logger()
LCR = "https://lcr.churchofjesuschrist.org"
OUT = Path(__file__).resolve().parent / "output" / "probe"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Probe:
    """One named read-only request against a unit (or none). Returns a result dict."""

    def __init__(self, name: str, path: str, unit_param: str | None = "unitNumber"):
        self.name = name
        self.path = path
        self.unit_param = unit_param

    def fire(self, sess, unit: int | None) -> dict:
        params = {self.unit_param: unit} if (self.unit_param and unit is not None) else None
        t0 = time.monotonic()
        try:
            r = sess.get(f"{LCR}{self.path}", params=params, timeout=30, allow_redirects=False)
            dt = round((time.monotonic() - t0) * 1000)
            return {"endpoint": self.name, "unit": unit, "status": r.status_code, "ms": dt,
                    "retry_after": r.headers.get("Retry-After"), "bytes": len(r.content),
                    "ratelimit": r.headers.get("X-RateLimit-Remaining") or r.headers.get("RateLimit-Remaining")}
        except Exception as exc:  # noqa: BLE001
            dt = round((time.monotonic() - t0) * 1000)
            return {"endpoint": self.name, "unit": unit, "status": -1, "ms": dt,
                    "error": type(exc).__name__}


PROBES = [
    Probe("member_list", "/api/umlu/report/member-list"),
    Probe("progress_record", "/api/report/one-work/progress-record"),
    Probe("org_callings", "/mlt/api/orgs"),
    Probe("dashboard", "/api/dashboard/data", unit_param=None),
    Probe("user_context", "/api/user-context", unit_param=None),
]


class Controller:
    """Holds the adaptive rate/concurrency + rolling stats; persists a summary."""

    def __init__(self, ts: str, max_rate: float):
        self.rate = 12.0          # requests/min, start gentle
        self.concurrency = 2
        self.max_rate = max_rate
        self.ceiling: float | None = None  # highest rate seen with clean success
        self.first_throttle: float | None = None  # rate at which throttling first appeared
        # per (endpoint, status) counts and per-endpoint latency, plus per-(endpoint,unit) history
        self.counts: dict = defaultdict(int)
        self.lat: dict = defaultdict(list)
        self.unit_status: dict = defaultdict(lambda: defaultdict(int))
        self.rounds: list = []
        self.jsonl = (OUT / f"probe_{ts}.jsonl").open("a", encoding="utf-8")
        self.summary_path = OUT / f"summary_{ts}.json"
        self._lock = threading.Lock()

    def record(self, res: dict, rate: float):
        with self._lock:
            res["t"] = _now()
            res["rate"] = round(rate, 1)
            self.jsonl.write(json.dumps(res) + "\n")
            self.counts[(res["endpoint"], res["status"])] += 1
            if res["status"] != -1:
                self.lat[res["endpoint"]].append(res["ms"])
            if res.get("unit") is not None:
                self.unit_status[res["endpoint"]][f"{res['unit']}:{res['status']}"] += 1

    def adapt(self, round_summary: dict):
        """Ramp up on clean success; back off hard on throttling. Records the ceiling."""
        ok = round_summary["success_rate"]
        throttled = round_summary["throttled"]  # 429 or connection drops
        server_err = round_summary["server_5xx"]
        self.rounds.append(round_summary)
        if throttled:
            self.first_throttle = self.first_throttle or self.rate
            self.ceiling = min(self.ceiling or self.rate, self.rate)
            self.rate = max(6.0, self.rate * 0.5)
        elif ok >= 0.99 and server_err == 0:
            self.ceiling = max(self.ceiling or 0, self.rate)
            self.rate = min(self.max_rate, self.rate * 1.4)
            if self.rate > 60 and self.concurrency < 8:
                self.concurrency += 1
        elif ok < 0.9:
            self.rate = max(6.0, self.rate * 0.7)
        self._persist()

    def _persist(self):
        with self._lock:
            per_ep = {}
            for ep in {e for e, _ in self.counts}:
                total = sum(v for (e, s), v in self.counts.items() if e == ep)
                ok = sum(v for (e, s), v in self.counts.items() if e == ep and 200 <= s < 300)
                by_status = {str(s): v for (e, s), v in self.counts.items() if e == ep}
                lat = sorted(self.lat.get(ep, []))
                per_ep[ep] = {
                    "total": total, "ok": ok,
                    "success_rate": round(ok / total, 3) if total else None,
                    "by_status": by_status,
                    "p50_ms": lat[len(lat) // 2] if lat else None,
                    "p95_ms": lat[int(len(lat) * 0.95)] if lat else None,
                }
            self.summary_path.write_text(json.dumps({
                "updated": _now(),
                "current_rate_per_min": round(self.rate, 1),
                "concurrency": self.concurrency,
                "clean_ceiling_per_min": self.ceiling,
                "first_throttle_per_min": self.first_throttle,
                "per_endpoint": per_ep,
                "recent_rounds": self.rounds[-12:],
                # which specific units consistently 404/500 (deterministic vs load)
                "unit_status": {ep: dict(v) for ep, v in self.unit_status.items()},
            }, indent=2), encoding="utf-8")

    def close(self):
        self._persist()
        self.jsonl.close()


def run_round(sess, probes, units, ctrl: Controller, round_secs: int) -> dict:
    """Fire requests at ctrl.rate for round_secs across probes×units; return the round summary."""
    interval = 60.0 / ctrl.rate
    n = max(1, int(round_secs / interval))
    jobs = []
    for i in range(n):
        p = probes[i % len(probes)]
        u = random.choice(units) if p.unit_param else None
        jobs.append((p, u))
    results = []
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=ctrl.concurrency) as ex:
        futures = []
        for p, u in jobs:
            futures.append(ex.submit(p.fire, sess, u))
            time.sleep(interval)  # pace submissions to hit the target rate
        for f in as_completed(futures):
            res = f.result()
            ctrl.record(res, ctrl.rate)
            results.append(res)
    dur = time.monotonic() - start
    total = len(results)
    ok = sum(1 for r in results if 200 <= r["status"] < 300)
    throttled = sum(1 for r in results if r["status"] in (429, -1))
    server_5xx = sum(1 for r in results if 500 <= r["status"] < 600)
    not_found = sum(1 for r in results if r["status"] == 404)
    retry_after = max((int(r["retry_after"]) for r in results
                       if str(r.get("retry_after") or "").isdigit()), default=0)
    summary = {
        "t": _now(), "rate": round(ctrl.rate, 1), "concurrency": ctrl.concurrency,
        "sent": total, "ok": ok, "success_rate": round(ok / total, 3) if total else 0,
        "throttled": throttled, "server_5xx": server_5xx, "not_found": not_found,
        "actual_per_min": round(total / dur * 60, 1) if dur else 0,
        "max_retry_after": retry_after,
    }
    logger.info("round @%.0f/min c=%d -> ok=%.0f%% sent=%d 429/drop=%d 5xx=%d 404=%d",
                ctrl.rate, ctrl.concurrency, summary["success_rate"] * 100, total,
                throttled, server_5xx, not_found)
    if retry_after:
        logger.warning("Retry-After=%ss -> honoring backoff", retry_after)
        time.sleep(min(retry_after, 120))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=12.0)
    ap.add_argument("--round-secs", type=int, default=90)
    ap.add_argument("--max-rate", type=float, default=600.0, help="cap on requests/min")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("endpoint probe starting: %.1fh budget, max-rate %.0f/min -> %s",
                args.hours, args.max_rate, OUT)

    client = LcrClient()
    me = client.whoami()
    logger.info("authenticated as %s", me.preferred_username)
    units = [u.unit_number for u in client.user_context().child_units if u.unit_number]
    if not units:
        units = [client.user_context().unit_number]
    logger.info("probing %d units", len(units))

    ctrl = Controller(ts, args.max_rate)
    sess = client.session.session
    deadline = time.monotonic() + args.hours * 3600
    rounds = 0
    try:
        while time.monotonic() < deadline:
            summary = run_round(sess, PROBES, units, ctrl, args.round_secs)
            ctrl.adapt(summary)
            rounds += 1
            # periodic re-auth guard: if a whole round failed auth (401/403/redirect heavy), re-login
            if summary["success_rate"] < 0.5 and summary["throttled"] == 0:
                logger.warning("low success without throttling — refreshing session")
                try:
                    client = LcrClient()
                    sess = client.session.session
                except Exception as exc:  # noqa: BLE001
                    logger.error("re-auth failed: %s", exc)
    except KeyboardInterrupt:
        logger.info("interrupted — finalizing summary")
    finally:
        ctrl.close()
    logger.info("probe done: %d rounds. clean ceiling=%s/min, first throttle=%s/min. summary -> %s",
                rounds, ctrl.ceiling, ctrl.first_throttle, ctrl.summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
