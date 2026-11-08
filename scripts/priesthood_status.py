#!/usr/bin/env python3
"""Recorded priesthood status for named members, from tools/output/stake_data.json.

Reads ONLY the local pull — it never logs in. The priesthood office in the
file is the LCR-recorded signal: POST https://membertools-api.churchofjesuschrist.org/api/v5/sync,
households[].members[].priesthood (ELDER/HIGH_PRIEST/..., absent = no office),
preserved by scripts/pull_stake_data.py (2026-11-08 fix; earlier pulls dropped
it, so they cannot answer this at all).

Usage:
    python scripts/priesthood_status.py "Nathaniel Petty" "Joy Datta" ...
    python scripts/priesthood_status.py --all-mp   # the 8 MP candidates + Neuenschwander

Always prints the pull timestamp first, so a stale file is never mistaken
for fresh data. If the file has no "priesthood" key for a member, the pull
predates the fix — re-run pull_stake_data.py (needs a live LCR login).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tools" / "output" / "stake_data.json"

MP_CANDIDATES = [
    "Nathaniel Petty", "Evan Hall", "Joy Datta", "Asher Dart",
    "Noah Marcellino", "Alec Judd", "Drew Holman", "Cole Finley Batchelor",
    "Kyle Neuenschwander",
]


def main() -> int:
    args = sys.argv[1:]
    names = MP_CANDIDATES if "--all-mp" in args else [a for a in args if not a.startswith("--")]
    if not names:
        print("usage: priesthood_status.py <name ...> | --all-mp", file=sys.stderr)
        return 2
    if not DATA.exists():
        print(f"no local pull at {DATA} — run scripts/pull_stake_data.py first", file=sys.stderr)
        return 1
    data = json.loads(DATA.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    print(f"pulled_at: {meta.get('pulled_at')}  members: {meta.get('members')}  "
          f"source: POST membertools-api.churchofjesuschrist.org/api/v5/sync")
    by_last = {}
    for m in data.get("members", []):
        last = (m.get("full_name") or "").split(",")[0].strip().lower()
        by_last.setdefault(last, []).append(m)
    for name in names:
        last = name.split()[-1].lower()
        hits = [m for m in by_last.get(last, [])
                if name.split()[0].lower() in (m.get("full_name") or "").lower()]
        if not hits:
            print(f"{name}: NOT FOUND in local pull")
            continue
        for m in hits:
            has_key = "priesthood" in m
            ords = ", ".join(f"{o.get('type')} {o.get('date') or ''}".strip()
                             for o in m.get("ordinances") or []) or "-"
            print(f"{m.get('full_name')} | {m.get('unit_name')} | "
                  f"priesthood office: {m.get('priesthood') or 'NONE (no office)'}"
                  f"{'' if has_key else '  [STALE PULL — priesthood field not captured, re-pull]'}"
                  f" | ordinances: {ords}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
