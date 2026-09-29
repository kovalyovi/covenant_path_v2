#!/usr/bin/env python3
"""Quick stake person lookup: LCR roster + Callings List in one shot.

Identifies a person from a partial name ("Sis. Guthrie") and shows their
calling, ward, and tracking status — the 30-second answer for "who is this
and what is their calling".

Usage:
    python3 scripts/find_person.py "Guthrie"
    python3 scripts/find_person.py "Tara Guthrie"
"""
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROSTER = REPO / "tools" / "output" / "stake_data.json"
CL_ID = "1UVFCtCygB1-oPZ5aCwnhsnFe6SXqXLivD-2B60J5MMs"
# Tabs of the Callings List worth searching (Sync Log excluded).
TABS = [
    "Callings", "App/Sus", "MP Ordain 78", "March 9", "Ratify",
    "CS Missionaries", "May 21", "PEs 6", "OE 91", "FT Missionaries",
    "Sealing 21", "Temple", "Welfare & Self Reliance", "Sheet23",
    "S&I", "Sheet3", "Completed",
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


def gws(*args: str):
    p = subprocess.run(
        ["hatch_gws_cli"] + list(args),
        capture_output=True, text=True, timeout=180,
    )
    if p.returncode != 0:
        raise RuntimeError(f"gws failed: {p.stderr.strip()[:300]}")
    return json.loads(p.stdout)


def matches(query_tokens: set[str], query: str, text: str) -> bool:
    t = norm(text)
    return query in t or query_tokens <= set(t.split())


def main() -> None:
    query = norm(" ".join(sys.argv[1:]).replace("sis.", "").replace("bro.", ""))
    if not query:
        sys.exit("usage: find_person.py <name>")
    qtok = set(query.split())

    print(f"--- Roster: '{query}' ---")
    roster = json.loads(ROSTER.read_text())
    seen = set()
    for m in roster.get("members", []):
        if matches(qtok, query, m.get("full_name", "")):
            key = (m.get("full_name"), m.get("unit_name"))
            if key in seen:
                continue
            seen.add(key)
            print(
                f"- {m.get('full_name')} | {m.get('unit_name')} | "
                f"{m.get('sex', '')} | b.{m.get('birth_date')}"
            )
    if not seen:
        print("(no roster match)")

    print(f"--- Callings List: '{query}' ---")
    ranges = [f"'{t}'!A1:Z2000" for t in TABS]
    d = gws(
        "sheets", "spreadsheets", "values", "batchGet", "--params",
        json.dumps({"spreadsheetId": CL_ID, "ranges": ranges}),
    )
    hits = 0
    for vr, tab in zip(d.get("valueRanges", []), TABS):
        vals = vr.get("values", [])
        for i, row in enumerate(vals[1:], start=2):
            if not any(matches(qtok, query, c) for c in row):
                continue
            hits += 1
            unit = row[0] if len(row) > 0 else ""
            name = row[1] if len(row) > 1 else ""
            calling = row[2] if len(row) > 2 else ""
            # Pull Called / Sustained / Set Apart markers wherever they sit.
            extra = " | ".join(c for c in row[3:] if str(c).strip().lower() not in ("", "n/a"))
            line = f"- [{tab} r{i}] {unit} | {name} | {calling}"
            if extra:
                line += f" | {extra}"
            print(line)
    if not hits:
        print("(no Callings List match)")


if __name__ == "__main__":
    main()
