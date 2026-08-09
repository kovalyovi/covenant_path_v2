"""
LCR endpoint probe — a lightweight watchdog that runs between syncs to profile the
endpoints that flake (progress-record / member-list 500s) and record latency + success
per unit. Writes a 'probe' diagnostics row the admin console trends over time.

Pure-requests login (no browser); hits user-context, each unit's progress-record +
member-list, and the dashboard. Scheduled by .github/workflows/probe-lcr.yml.

  python -m backend.probe
"""

from __future__ import annotations

import sys

from backend import db
from lcr_client.logging_setup import get_logger

logger = get_logger()


def main() -> int:
    from lcr_client import LcrClient, metrics, okta_login

    try:
        okta_login.login()
    except Exception as exc:  # noqa: BLE001 — any auth failure: skip, don't red-fail every 4h
        # The operator account has MFA enabled, so a headless password login can't clear the second
        # factor (Okta returns select-authenticator-authenticate). The daily sync is unaffected — it
        # runs off the stored 45-day Member Tools token — but this probe needs a FRESH LCR session it
        # can no longer obtain in CI. Skip cleanly (same posture as the sync's needs_reauth, which no
        # longer red-fails the run) so a chronic, expected condition doesn't masquerade as a failure.
        logger.warning("probe skipped — could not establish a fresh LCR session "
                       "(operator login is likely MFA-walled): %s", exc)
        print(f"[skip] probe: no LCR session ({exc})")
        return 0
    metrics.reset()
    client = LcrClient()
    ctx = client.user_context()
    units = [u for u in ctx.child_units if u.unit_number and u.type in ("WARD", "BRANCH")]

    per_unit: dict[str, dict] = {}
    for u in units:
        res = {"progress_record": True, "member_list": True}
        for label, call in (("progress_record", lambda: client.progress_record(u.unit_number)),
                            ("member_list", lambda: client.member_list(u.unit_number))):
            try:
                call()
            except Exception as exc:  # noqa: BLE001 — metrics already recorded the status
                res[label] = False
                logger.warning("probe %s %s failed: %s", u.name, label, exc)
        per_unit[u.name] = res
    try:
        client.dashboard_data()
    except Exception as exc:  # noqa: BLE001
        logger.warning("probe dashboard_data failed: %s", exc)

    snap = metrics.snapshot()
    units_ok = sum(1 for r in per_unit.values() if all(r.values()))
    conn = db.connect()
    try:
        try:
            stake_id = db.upsert_stake(conn, ctx.unit_number, ctx.unit_name)
        except db.SubUnitAsStakeError as exc:
            # The operator login resolved to a WARD/BRANCH context (it has happened: 2026-07-22..26).
            # Recording that as a "stake" is what produced the phantom Green Level Ward row, so skip
            # the diagnostics write entirely rather than mint one.
            logger.warning("probe diagnostics skipped — session is ward/branch-scoped: %s", exc)
            print(f"[skip] probe: {exc}")
            return 0
        db.insert_diagnostics(conn, stake_id, "probe", {
            "requests": snap,
            "units_ok": units_ok,
            "units_total": len(units),
            "per_unit": per_unit,
        })
    finally:
        conn.close()
    print(f"[+] probe: {units_ok}/{len(units)} units clean, "
          f"{snap['success_pct']}% request success ({snap['total_errors']} errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
