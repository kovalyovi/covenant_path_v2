"""
#5 Spreadsheet access rules — who may see which Google Sheet, derived from current callings.

The stake sheet (all units' data) goes ONLY to stake-level leadership; each ward gets its OWN
sheet (that ward's data only) shared with that ward's leadership + the assigned missionaries; and
stake leaders see every ward sheet too. This is recomputed from `user_roles` (+ the missionary
roster) on every sync, so a released leader / rotated missionary / calling that lost a feature is
dropped automatically (just don't appear in the fresh recipient set → reconcile removes them).

Recipient lists (per the access policy):
  • STAKE sheet  → stake presidency + their clerks / executive secretaries / assistants.
  • WARD  sheet  → ward bishopric + EQ & RS presidencies + ward mission leader + assigned
                   full-time missionaries, PLUS all stake-sheet recipients (stake sees all).

This is intentionally TIGHTER than the in-app data-access gate (backend/roles.py): e.g. a High
Councilor can see stake data in the app but is not auto-added to the spreadsheet. Pure functions,
unit-tested — no I/O here; the orchestrator (scripts/daily_sync.py) feeds it DB rows.
"""

from __future__ import annotations

import re
from collections import defaultdict

# --- calling → which sheet(s) ------------------------------------------------

# Stake-sheet callings: the stake presidency and the secretaries/clerks/assistants who serve it.
# (High Council is deliberately excluded — they have in-app data access, not a sheet share.)
_STAKE = re.compile(r"\bstake\b", re.I)
_PRES_CLERK_SEC = re.compile(r"president|presidency|clerk|secretary", re.I)


def is_stake_sheet_calling(calling: str | None) -> bool:
    """A stake-level calling that receives the stake-wide sheet: Stake President / Counselor in the
    Stake Presidency / Stake (Assistant) Clerk / Stake (Assistant) Executive Secretary."""
    c = calling or ""
    return bool(_STAKE.search(c) and _PRES_CLERK_SEC.search(c))


def is_ward_sheet_calling(calling: str | None) -> bool:
    """A ward-level calling that receives that ward's sheet: bishopric (Bishop / Counselor in the
    Bishopric), Elders Quorum & Relief Society presidencies (president + counselors), and the Ward
    Mission Leader. (Ward clerks/secretaries are NOT auto-shared — not in the access list.)"""
    c = calling or ""
    if re.search(r"bishop", c, re.I):  # Bishop, Counselor in the Bishopric
        return True
    if re.search(r"ward mission leader", c, re.I):
        return True
    # EQ / RS presidency = president or a counselor in that presidency
    if re.search(r"elders\s+quorum", c, re.I) and _PRES_CLERK_SEC.search(c):
        return True
    if re.search(r"relief\s+society", c, re.I) and _PRES_CLERK_SEC.search(c):
        return True
    return False


# --- recipient computation ---------------------------------------------------

def _clean(email: str | None) -> str | None:
    e = (email or "").strip().lower()
    return e if "@" in e else None


def compute_recipients(roles: list[dict], missionaries_by_unit: dict[str, list[dict]] | None = None
                       ) -> dict:
    """Compute the email recipient sets for every sheet from the stake's current roles + missionary
    roster.

    `roles`: rows from user_roles — each {email, calling_name, role, unit_id, unit_name}.
    `missionaries_by_unit`: {unit_name: [{email, ...}, ...]} (stakes.missionaries).

    Returns:
      {
        "stake": set[email],                 # the stake-wide sheet
        "wards": {unit_id: set[email]},       # each ward's own sheet (incl. stake recipients)
        "ward_names": {unit_id: unit_name},   # for titling the ward sheets
      }
    Stake recipients are unioned into every ward set (stake leaders see all wards).
    """
    missionaries_by_unit = missionaries_by_unit or {}
    stake: set[str] = set()
    wards: dict[str, set[str]] = defaultdict(set)
    ward_names: dict[str, str] = {}
    name_to_unit: dict[str, str] = {}  # unit_name -> unit_id, to attach missionaries by name

    for r in roles:
        email = _clean(r.get("email"))
        calling = r.get("calling_name")
        unit_id = r.get("unit_id")
        unit_name = r.get("unit_name")
        if unit_id and unit_name:
            ward_names.setdefault(unit_id, unit_name)
            name_to_unit.setdefault(unit_name, unit_id)
        if not email:
            continue
        if is_stake_sheet_calling(calling):
            stake.add(email)
        elif unit_id and is_ward_sheet_calling(calling):
            wards[unit_id].add(email)

    # Assigned full-time missionaries get their ward's sheet (rotates automatically each run).
    for unit_name, miss in missionaries_by_unit.items():
        unit_id = name_to_unit.get(unit_name)
        if not unit_id:
            continue
        for m in miss or []:
            email = _clean(m.get("email"))
            if email:
                wards[unit_id].add(email)
                ward_names.setdefault(unit_id, unit_name)

    # Stake leaders see every ward sheet.
    for unit_id in list(wards) + list(ward_names):
        wards[unit_id] |= stake

    return {"stake": stake, "wards": {u: e for u, e in wards.items()},
            "ward_names": ward_names}
