"""
LCR API health check.

Exercises every endpoint we depend on and reports pass/fail with detail. The
profile checks self-heal (auto-discover action ids) on a miss. Failures are
logged and dumped to tools/output/debug/ for triage; a machine-readable
report is written to tools/output/health_report.json.

Usage:
  python tools/health_check.py
Exit code is non-zero if any critical check fails.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client import LcrClient
from lcr_client.auth import AuthExpiredError
from lcr_client.logging_setup import dump_debug, get_logger
from lcr_client.member_profile import fetch_member_profile, fetch_ministering, fetch_recommend

logger = get_logger()
OUT = Path(__file__).resolve().parent / "output"


def main() -> int:
    client = LcrClient()
    results = []

    def check(name, critical, fn):
        start = time.perf_counter()
        try:
            detail = fn()
            ok = True
        except AuthExpiredError as exc:
            ok, detail = False, f"AUTH EXPIRED: {exc}"
            dump_debug("auth_expired", check=name, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
            dump_debug(f"check_{name}", check=name, error=str(exc))
        ms = int((time.perf_counter() - start) * 1000)
        results.append({"check": name, "critical": critical, "ok": ok,
                        "detail": str(detail)[:200], "ms": ms})
        logger.info(f"[{'PASS' if ok else 'FAIL'}] {name} ({ms}ms) {detail if not ok else ''}")

    ctx = client.user_context()
    unit = next((u for u in ctx.child_units if u.type in ("WARD", "BRANCH")), None)
    members = client.member_list(unit.unit_number) if unit else []
    pr = client.progress_record(unit.unit_number) if unit else None
    new_people = (pr.raw.get("newMemberList") if pr else []) or []
    sample_uuid = next((m.raw.get("personUuid") for m in members if m.raw.get("personUuid")), None)

    check("auth_me", True, lambda: f"as {client.whoami().name}"
          if client.whoami().cmis_uuid else (_ for _ in ()).throw(ValueError("no cmis_uuid")))
    check("user_context", True, lambda: f"{ctx.unit_name}, {len(ctx.child_units)} child units"
          if ctx.unit_number else (_ for _ in ()).throw(ValueError("no unit_number")))
    check("member_list", True, lambda: f"{len(members)} members"
          if members and members[0].uuid else (_ for _ in ()).throw(ValueError("empty/malformed")))
    check("unit_org", False, lambda: f"{len(client.unit_orgs(unit.unit_number))} orgs")
    check("progress_record", True, lambda: f"{len(new_people)} new members"
          if pr and "newMemberList" in pr.raw else (_ for _ in ()).throw(ValueError("no newMemberList")))
    if new_people:
        p = new_people[0]
        check("one_work_details", True, lambda: f"got {client.progress_details(p['id'], p.get('cmisId')).get('name')}")
    if sample_uuid:
        check("profile_record", True, lambda: f"baptism {fetch_member_profile(client.session, sample_uuid).get('ordinances') and 'ok'}")
        check("profile_recommend", False, lambda: f"recommend keys: {list(fetch_recommend(client.session, sample_uuid).keys())}")
        check("profile_ministering", False, lambda: f"has_assignment={fetch_ministering(client.session, sample_uuid)['has_assignment']}")

    passed = sum(1 for r in results if r["ok"])
    crit_fail = [r for r in results if r["critical"] and not r["ok"]]
    report = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "passed": passed, "total": len(results),
              "critical_failures": len(crit_fail), "checks": results}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "health_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n=== health: {passed}/{len(results)} passed, {len(crit_fail)} critical failures ===")
    for r in results:
        print(f"  [{'OK ' if r['ok'] else 'FAIL'}] {r['check']:20} {r['detail']}")
    print(f"\n-> {OUT/'health_report.json'}")
    return 1 if crit_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
