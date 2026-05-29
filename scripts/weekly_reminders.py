"""
Weekly "what's missing" reminders — the Saturday-evening nudge.

Reads Supabase (no LCR scrape needed — the morning sync already loaded the data), computes
each leader's converts with outstanding *eligible* integration steps, diffs against last week's
snapshot to congratulate finished steps, and emails a per-leader digest (suppressed when there's
nothing to nudge and nothing to celebrate). See backend/mailer.send_weekly_reminders.

  python scripts/weekly_reminders.py          # manual run (always sends)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client.logging_setup import get_logger

logger = get_logger()


def _should_run_now() -> tuple[bool, str]:
    """Scheduled runs proceed only Saturday ~21:00 ET (fixed for the week). Manual always runs."""
    if os.getenv("GITHUB_EVENT_NAME") != "schedule":
        return True, "manual run"
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception as exc:  # noqa: BLE001
        return True, f"tz lookup failed ({exc}); running anyway"
    if now.weekday() == 5 and now.hour == 21:  # Saturday 9pm ET
        return True, f"Saturday 21:00 ET ({now:%a %H:%M %Z})"
    return False, f"off-target ET time ({now:%a %H:%M %Z})"


def main() -> int:
    ok, why = _should_run_now()
    logger.info("weekly-reminders gate: %s", why)
    if not ok:
        print(f"[skip] {why}")
        return 0
    from backend import db, mailer
    conn = db.connect()
    try:
        sent = mailer.send_weekly_reminders(conn)
        handoffs = mailer.send_handoff_pings(conn)
    finally:
        conn.close()
    print(f"[+] sent {sent} weekly reminder(s), {handoffs} handoff ping(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
