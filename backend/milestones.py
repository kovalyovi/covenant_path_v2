"""
Pure (no-DB) covenant-path milestone logic — the single source of truth for "which integration
steps is this convert eligible for, and which are still missing." Shared by the mailer (weekly
reminders / handoff pings) AND the auth-broker's report builder, which has NO psycopg2 in its slim
image — so this module must stay dependency-free (re + datetime only). Mirrors the app's
golden_hour milestones + eligibility (see apps/viewer/lib/golden_hour.dart).
"""

from __future__ import annotations

import re
from datetime import datetime


_MONTHS: dict[str, int] = {}
for _i, _full in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"], 1):
    _MONTHS[_full] = _i
    _MONTHS[_full[:3]] = _i  # abbreviation too ("Sep", "Jul") — LCR uses "20 Sep 2016"


def year(v) -> int | None:
    m = re.search(r"(\d{4})", str(v or ""))
    return int(m.group(1)) if m else None


def _year_month(v) -> tuple[int, int | None] | None:
    """(year, month|None) from 'YYYY-MM-DD', 'YYYY', or '15 March 1990' style strings."""
    s = str(v or "")
    iso = re.search(r"(\d{4})-(\d{1,2})", s)
    if iso:
        return int(iso.group(1)), int(iso.group(2))
    y = re.search(r"(\d{4})", s)
    if not y:
        return None
    mo = next((idx for name, idx in _MONTHS.items() if name in s.lower()), None)
    return int(y.group(1)), mo


def turns_at_least(m: dict, age: int) -> bool:
    """Turns at least [age] by the END of this calendar year (the Church's by-year rule):
    currentYear - birthYear >= age. Used for Aaronic Priesthood, calling, ministering assignment."""
    y = year(m.get("birth_date"))
    return y is not None and (datetime.now().year - y) >= age


def age_now(m: dict) -> int | None:
    """Actual current age (best-effort; uses birth month when present, else by-year)."""
    ym = _year_month(m.get("birth_date"))
    if not ym:
        return None
    y, mo = ym
    now = datetime.now()
    age = now.year - y
    if mo and now.month < mo:  # birthday hasn't occurred yet this year
        age -= 1
    return age


def is_at_least_now(m: dict, age: int) -> bool:
    a = age_now(m)
    return a is not None and a >= age


def member_months(m: dict) -> int | None:
    """Whole months since baptism (best-effort)."""
    ym = _year_month(m.get("baptism_date"))
    if not ym:
        return None
    y, mo = ym
    now = datetime.now()
    return (now.year - y) * 12 + (now.month - (mo or 1))


def member_one_year(m: dict) -> bool:
    """At least 12 months since baptism."""
    mm = member_months(m)
    return mm is not None and mm >= 12


# (label, is-complete, is-eligible) — the single source of milestone eligibility. Confirmed rules
# (2026-05-30): turning-N-this-year = currentYear-birthYear>=N; "now" = actual current age.
#   Aaronic = male & turning-12;  calling = turning-12;  gives-ministering = turning-14 (both sexes);
#   has-ministers = everyone;  Melchizedek = male & age>=18 NOW & member>=1yr.
# Mirrored in apps/viewer/lib/golden_hour.dart — keep in sync.
MILESTONES = [
    ("a friend in the ward", lambda m: m.get("friends") == "Yes", lambda m: True),
    ("a calling", lambda m: m.get("calling") == "Yes", lambda m: turns_at_least(m, 12)),
    ("ministers assigned to them", lambda m: m.get("ministering_brothers_sisters") == "Yes", lambda m: True),
    ("a ministering assignment", lambda m: m.get("ministering_assignment") == "Yes", lambda m: turns_at_least(m, 14)),
    ("the Aaronic Priesthood", lambda m: m.get("aaronic_priesthood") == "Yes",
     lambda m: m.get("sex") == "M" and turns_at_least(m, 12)),
    ("the Melchizedek Priesthood", lambda m: m.get("melchizedek_priesthood") == "Yes",
     lambda m: m.get("sex") == "M" and is_at_least_now(m, 18) and member_one_year(m)),
]


def member_missing(m: dict) -> list[str]:
    """The eligible-but-incomplete integration steps for one member dict."""
    return [label for label, complete, elig in MILESTONES if elig(m) and not complete(m)]
