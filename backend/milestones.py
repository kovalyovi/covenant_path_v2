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


def year(v) -> int | None:
    m = re.search(r"(\d{4})", str(v or ""))
    return int(m.group(1)) if m else None


def turns_at_least(m: dict, age: int) -> bool:
    """Turns at least [age] by the end of this calendar year (the Church's by-year rule)."""
    y = year(m.get("birth_date"))
    return y is not None and (datetime.now().year - y) >= age


def member_one_year(m: dict) -> bool:
    y = year(m.get("baptism_date"))
    return y is not None and (datetime.now().year - y) >= 1


# (label, is-complete, is-eligible) — mirrors the app's golden_hour milestones + eligibility.
MILESTONES = [
    ("a friend in the ward", lambda m: m.get("friends") == "Yes", lambda m: True),
    ("a calling", lambda m: m.get("calling") == "Yes", lambda m: turns_at_least(m, 12)),
    ("ministers assigned to them", lambda m: m.get("ministering_brothers_sisters") == "Yes", lambda m: True),
    ("a ministering assignment", lambda m: m.get("ministering_assignment") == "Yes", lambda m: turns_at_least(m, 12)),
    ("the Aaronic Priesthood", lambda m: m.get("aaronic_priesthood") == "Yes",
     lambda m: m.get("sex") == "M" and turns_at_least(m, 12)),
    ("the Melchizedek Priesthood", lambda m: m.get("melchizedek_priesthood") == "Yes",
     lambda m: m.get("sex") == "M" and turns_at_least(m, 18) and member_one_year(m)),
]


def member_missing(m: dict) -> list[str]:
    """The eligible-but-incomplete integration steps for one member dict."""
    return [label for label, complete, elig in MILESTONES if elig(m) and not complete(m)]
