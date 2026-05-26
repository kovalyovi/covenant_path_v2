"""
CLI: push the covenant-path report to the master Google Sheet.

Data source: an existing report JSON (output/covenant_path_stake.json) by default,
or --scrape to run the v2 report first.

  python -m sheets_sync.sync --dry-run                  # show changes, write nothing
  python -m sheets_sync.sync --spreadsheet-id <ID>      # write to a sheet
  python -m sheets_sync.sync --scrape --with-profile    # scrape fresh, then sync

The service-account email must have Editor access to the target spreadsheet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lcr_client.logging_setup import get_logger
from sheets_sync.service import SheetsSync

logger = get_logger()
REPORT_JSON = Path(__file__).resolve().parent.parent / "output" / "covenant_path_stake.json"
# The [TEST] COPY of New Member Progress (safe default for experimentation).
TEST_SPREADSHEET_ID = "1JD9EC_SafClaY8cOcRzi5ZI4fUnjOxa-xXJA0lxgJaA"


def _load_members(scrape: bool, with_profile: bool) -> list[dict]:
    if scrape:
        from dataclasses import asdict
        from lcr_client import LcrClient
        from covenant_path.report import build_stake_report
        rows = build_stake_report(LcrClient(), with_profile=with_profile)
        return [asdict(r) for r in rows]
    if not REPORT_JSON.exists():
        raise SystemExit(f"No report at {REPORT_JSON}; run with --scrape or generate it first.")
    return json.loads(REPORT_JSON.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync covenant-path report to Google Sheets")
    ap.add_argument("--spreadsheet-id", default=TEST_SPREADSHEET_ID)
    ap.add_argument("--sheet-name", default="New member progress")
    ap.add_argument("--scrape", action="store_true", help="run the v2 report instead of loading JSON")
    ap.add_argument("--with-profile", action="store_true", help="(with --scrape) include profile fields")
    ap.add_argument("--dry-run", action="store_true", help="compute changes but write nothing")
    ap.add_argument("--no-units", action="store_true", help="skip per-unit tabs")
    ap.add_argument("--copy-formats", action="store_true", help="also copy formatting to unit tabs")
    args = ap.parse_args()

    members = _load_members(args.scrape, args.with_profile)
    sync = SheetsSync(args.spreadsheet_id, args.sheet_name)
    info = sync.diagnose()
    print(f"[*] target: {info['title']} ({len(info['tabs'])} tabs); {len(members)} members")

    summary = sync.sync(members, write=not args.dry_run, units=not args.no_units,
                        copy_formats=args.copy_formats)
    verb = "WROTE" if summary["wrote"] else "DRY-RUN"
    print(f"[{verb}] +{summary['added']} new  -{summary['removed']} removed  "
          f"~{summary['modified']} modified  ({summary['members']} members)")
    if args.dry_run and summary.get("sample_row"):
        print("    sample row:", summary["sample_row"])
    logger.info("sheets sync %s: %s", verb, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
