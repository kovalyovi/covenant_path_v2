#!/usr/bin/env python3
"""Query the local stake repository (tools/output/stake_data.json) — no login needed.

First pull the data once (needs Church credentials)::
    LCR_LOGIN='you@example.com' LCR_PASSWORD='...' python scripts/pull_stake_data.py

Then query any time::

    python scripts/stake.py find "nathan reading"   # find a person
    python scripts/stake.py ward "cary 1st"          # ward roster summary
    python scripts/stake.py leadership              # all leadership, by unit
    python scripts/stake.py leadership "cary 1st"   # one unit's leadership
    python scripts/stake.py units                   # unit list with headcounts

Flags:
    --data PATH   use a different stake_data.json (default: tools/output/stake_data.json)
    --refresh     re-pull from the Church first (needs LCR_LOGIN / LCR_PASSWORD)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "tools" / "output" / "stake_data.json"


def load(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"[!] {path} not found — run scripts/pull_stake_data.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def display_name(full: str | None, preferred: str | None = None) -> str:
    """'Last, First Middle' -> 'First Middle Last' (preferred first name when known)."""
    if not full:
        return "?"
    if "," in full:
        last, rest = full.split(",", 1)
        rest = rest.strip()
        if preferred:
            # preferred is usually just the first name; keep any middle names.
            parts = rest.split()
            rest = " ".join([preferred] + parts[1:]) if parts else preferred
        return f"{rest} {last.strip()}".strip()
    return full


def calling_index(data: dict) -> dict[str, list[str]]:
    """person_uuid -> ['Position (Unit)', ...]."""
    unit_by_num = {str(u["unit_number"]): u["name"] for u in data["units"]}
    idx: dict[str, list[str]] = {}
    for unum, rows in data["leadership"].items():
        uname = unit_by_num.get(str(unum), "")
        for r in rows:
            label = r["position"] + (f" ({uname})" if uname else "")
            idx.setdefault(r["person_uuid"], []).append(label)
    return idx


def cmd_find(data: dict, query: str) -> int:
    q = query.strip().lower()
    callings = calling_index(data)

    def _hay(m: dict) -> str:
        return " ".join(filter(None, [
            (m["full_name"] or "").lower(),
            display_name(m["full_name"], m["preferred_name"]).lower(),
            (m["preferred_name"] or "").lower(),
        ]))

    hits = [m for m in data["members"] if q in _hay(m)]
    if not hits:
        print(f"No matches for {query!r}.")
        return 1
    for m in sorted(hits, key=lambda m: m["full_name"] or ""):
        print(f"- {display_name(m['full_name'], m['preferred_name'])}"
              f"  [{m['unit_name'] or 'unit?'}]")
        for c in callings.get(m["uuid"], []):
            print(f"    * {c}")
    return 0


def _match_unit(data: dict, query: str) -> dict | None:
    q = query.strip().lower()
    cands = [u for u in data["units"] if q in u["name"].lower()]
    if not cands:
        print(f"No unit matches {query!r}. Try: scripts/stake.py units")
        return None
    if len(cands) > 1:
        print(f"Ambiguous {query!r}; matches: " + ", ".join(u["name"] for u in cands))
        return None
    return cands[0]


def cmd_ward(data: dict, query: str) -> int:
    unit = _match_unit(data, query)
    if not unit:
        return 1
    unum = unit["unit_number"]
    members = [m for m in data["members"] if m["unit_number"] == unum]
    print(f"{unit['name']} — {len(members)} members")
    rows = data["leadership"].get(str(unum), [])
    if rows:
        print("Leadership:")
        for r in rows:
            mark = " (set apart)" if r.get("set_apart") else ""
            print(f"  - {r['position']}: {display_name(r['person'])}{mark}")
    return 0


def cmd_leadership(data: dict, query: str | None) -> int:
    unit_by_num = {str(u["unit_number"]): u["name"] for u in data["units"]}
    items = data["leadership"].items()
    if query:
        unit = _match_unit(data, query)
        if not unit:
            return 1
        items = [(str(unit["unit_number"]), data["leadership"].get(str(unit["unit_number"]), []))]
    for unum, rows in sorted(items, key=lambda kv: unit_by_num.get(kv[0], "")):
        print(f"== {unit_by_num.get(unum, unum)} ==")
        for r in sorted(rows, key=lambda r: r["position"]):
            print(f"  - {r['position']}: {display_name(r['person'])}")
    return 0


def cmd_units(data: dict) -> int:
    counts: dict[int, int] = {}
    for m in data["members"]:
        if m["unit_number"] is not None:
            counts[m["unit_number"]] = counts.get(m["unit_number"], 0) + 1
    meta = data["meta"]
    print(f"{meta.get('stake', 'Stake')} — pulled {meta.get('pulled_at', '?')}")
    for u in sorted(data["units"], key=lambda u: u["name"]):
        n = counts.get(u["unit_number"], 0)
        print(f"  - {u['name']}: {n} members")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Query the local stake data repository.")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="path to stake_data.json")
    ap.add_argument("--refresh", action="store_true",
                    help="re-pull from the Church first (needs LCR_LOGIN/LCR_PASSWORD)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find", help="find a person by name")
    p.add_argument("query")
    p = sub.add_parser("ward", help="ward roster summary + leadership")
    p.add_argument("query")
    p = sub.add_parser("leadership", help="leadership roster, optionally one ward")
    p.add_argument("query", nargs="?")
    sub.add_parser("units", help="unit list with headcounts")
    args = ap.parse_args()

    if args.refresh:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pull_stake_data.py")])
        if r.returncode != 0:
            return r.returncode

    data = load(Path(args.data))
    if args.cmd == "find":
        return cmd_find(data, args.query)
    if args.cmd == "ward":
        return cmd_ward(data, args.query)
    if args.cmd == "leadership":
        return cmd_leadership(data, args.query)
    if args.cmd == "units":
        return cmd_units(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
