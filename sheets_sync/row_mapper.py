"""
Map a v2 covenant-path member record to the master spreadsheet's row format.

Matches the existing sheet (and v1's MemberProgress.to_data) exactly so a v2 sync
keeps the data identical in shape:

  A Member  B Unit  C Baptism date  D Member for  E Birth date  F Age
  G Friends  H Aaronic  I Melchizedek  J Calling  K Ministering Bros/Sisters
  L Ministering Assignment  M Temple recommend  N Patriarchal blessing
  O Living ordinance  P 1st temple visit  Q Family name prepared
  [R+ e.g. "Notes" = manual, preserved by the merge. P was a MANUAL column before the
   temple-experiences sync (2026-06-10) — same header, now synced, old hand-entries
   preserved by the gated merge; the merge shifts any remaining manual tail right.]

Conventions taken from the live sheet:
  - dates -> MM/DD/YY; "Member for"/"Age" -> human duration ("8 months", "1 year 2 months")
  - unit -> name with " Ward"/" Branch" stripped (col B); full name kept for tab grouping
  - temple recommend -> Yes / Expired / No  (v2 emits Active/Expired/No -> Active maps to Yes)
  - fields we couldn't fetch (blocked/needs-profile) -> empty, and the merge preserves the
    existing cell so a partial scrape never erases good data.
"""

from __future__ import annotations

import datetime as _dt

DATA_WIDTH = 17  # columns A..Q written by the sync; R+ are manual and preserved

# Column headers (row 2) — written when we CREATE a fresh per-stake sheet, and re-asserted on every
# sync (manual headers beyond the synced block are kept, shifted right). Must stay aligned with
# to_row()'s column order above.
HEADER_LABELS = [
    "Member", "Unit", "Baptism date", "Member for", "Birth date", "Age", "Friends", "Aaronic",
    "Melchizedek", "Calling", "Ministering Bros/Sisters", "Ministering Assignment",
    "Temple recommend", "Patriarchal blessing", "Living ordinance", "1st temple visit",
    "Family name prepared",
]


def synced_header_width(headers: list) -> int:
    """How many LEADING existing header cells already match the synced layout — i.e. where the
    sheet's MANUAL tail starts. A pre-temple-experiences sheet (15 synced cols, then a manual
    '1st temple visit' P and 'Notes' Q) yields 16: P's header text matches the new synced P, so its
    hand-entered values feed the gated merge, while Q ('Notes' ≠ 'Family name prepared') and beyond
    are the manual tail the merge shifts right. An up-to-date sheet yields DATA_WIDTH."""
    width = 0
    for i, label in enumerate(HEADER_LABELS):
        if i < len(headers) and str(headers[i]).strip().lower() == label.lower():
            width = i + 1
        else:
            break
    # Below 15 the headers aren't a recognizable covenant-path layout (missing/renamed) — fall back
    # to the full synced width, i.e. the old fixed-DATA_WIDTH behavior, rather than misclassifying
    # synced columns as a manual tail.
    return width if width >= 15 else DATA_WIDTH

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
        _plain(m.get("first_temple_visit")),
        _plain(m.get("family_name_prepared")),
    ]


# columns (0-based) that come from flaky/gated endpoints and may come back unknown;
# the merge preserves the existing cell when our value is empty for these.
GATED_COLUMNS = (2, 3, 11, 12, 13, 15, 16)  # baptism, member-for, min-assign, recommend,
#                                             patriarchal, 1st temple visit, family name
