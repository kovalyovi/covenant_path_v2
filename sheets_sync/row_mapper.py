"""
Map a v2 covenant-path member record to the master spreadsheet's row format.

Matches the existing sheet (and v1's MemberProgress.to_data) exactly so a v2 sync
keeps the data identical in shape:

  A Member  B Unit  C Baptism date  D Member for  E Birth date  F Age
  G Friends  H Aaronic  I Melchizedek  J Calling  K Ministering Bros/Sisters
  L Ministering Assignment  M Temple recommend  N Patriarchal blessing
  O Living ordinance   [P "1st temple visit", Q "Notes" = manual, preserved by the merge]

Conventions taken from the live sheet:
  - dates -> MM/DD/YY; "Member for"/"Age" -> human duration ("8 months", "1 year 2 months")
  - unit -> name with " Ward"/" Branch" stripped (col B); full name kept for tab grouping
  - temple recommend -> Yes / Expired / No  (v2 emits Active/Expired/No -> Active maps to Yes)
  - fields we couldn't fetch (blocked/needs-profile) -> empty, and the merge preserves the
    existing cell so a partial scrape never erases good data.
"""

from __future__ import annotations

import datetime as _dt

DATA_WIDTH = 15  # columns A..O written by the sync; P+ are manual and preserved

# values that mean "not fetched" — blanked, and preserved-on-merge for gated cols.
# NOTE: "N/A" is a REAL value (e.g. priesthood not applicable) and must pass through.
_UNKNOWN = {"", None, "needs-profile-api", "blocked: insufficient calling access"}
_DATE_IN_FORMATS = ("%d %b %Y", "%d %B %Y", "%m/%d/%y", "%Y-%m-%d")


def parse_date(value) -> _dt.date | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in _DATE_IN_FORMATS:
        try:
            return _dt.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def format_date(d: _dt.date | None) -> str:
    return d.strftime("%m/%d/%y") if d else ""


def duration_string(d: _dt.date | None, today: _dt.date | None = None) -> str:
    if d is None:
        return ""
    today = today or _dt.date.today()
    months = (today.year - d.year) * 12 + (today.month - d.month) - (today.day < d.day)
    months = max(0, months)
    years, rem = divmod(months, 12)
    if years == 0:
        return f"{rem} month{'s' if rem != 1 else ''}"
    return f"{years} year{'s' if years != 1 else ''} {rem} month{'s' if rem != 1 else ''}"


def format_unit(unit: str | None) -> str:
    if not unit:
        return ""
    return unit.replace(" Ward", "").replace(" Branch", "")


def _recommend(value) -> str:
    """v2 emits Active/Expired/No; the sheet uses Yes/Expired/No."""
    if value == "Active":
        return "Yes"
    if value == "Expired":
        return "Expired"
    if value in _UNKNOWN:
        return ""
    return value  # "No"


def _plain(value) -> str:
    """Yes/No/N/A pass-through; unknown sentinels become empty."""
    return "" if value in _UNKNOWN else str(value)


def to_row(m: dict) -> list[str]:
    """Convert a covenant_path report record (dict) to the 15-col sheet row (A..O)."""
    baptism = parse_date(m.get("baptism_date"))
    birth = parse_date(m.get("birth_date"))
    return [
        m.get("name") or "",
        format_unit(m.get("unit")),
        format_date(baptism),
        duration_string(baptism),
        format_date(birth),
        duration_string(birth),
        _plain(m.get("friends")),
        _plain(m.get("aaronic_priesthood")),
        _plain(m.get("melchizedek_priesthood")),
        _plain(m.get("calling")),
        _plain(m.get("ministering_brothers_sisters")),
        _plain(m.get("ministering_assignment")),
        _recommend(m.get("temple_recommend")),
        _plain(m.get("patriarchal_blessing")),
        _plain(m.get("living_ordinance")),
    ]


# columns (0-based) that come from the profile actions and may be access-blocked;
# the merge preserves the existing cell when our value is empty for these.
GATED_COLUMNS = (2, 3, 11, 12, 13)  # baptism date, member-for, ministering-assign, recommend, patriarchal
