"""
Offline tests for the Member Tools `/api/v5/sync` → CovenantPathMember adapter — no network, no DB.

Focus: the #data-gap ministering/calling RESCUE (2026-06-13). The covenant-path PERSON record carries
no ministering / calling / priesthood / recommend; the WHOLE payload carries the unit-wide ministering
org (`ministeringBrothers`/`ministeringSisters`) + the member directory (`households[].members[]`).
`adapt_sync` now fills ministering_brothers_sisters / ministering_assignment / calling / sex / birth
from that, instead of leaking the NEEDS_PROFILE sentinel once the LCR session dies.

The big fixture + its expectations are ported 1:1 from the upstream reference's
SyncDirectoryAdaptersTests.swift (rickybloomfield/Mission-KPIs — the official-app clone we
reverse-engineered the schema from), so this is a faithful regression of the authoritative algorithm.

Run: python -m pytest tests/test_membertools_adapter.py -q
"""

from __future__ import annotations

from covenant_path.membertools_adapter import (
    MinisteringIndex,
    _calling_index,
    _endowed_index,
    _name_index,
    _priesthood_office_index,
    _recommend_index,
    _sex_index,
    adapt_sync,
)
from covenant_path.report import NA, NEEDS_PROFILE


# The reference fixture: stake 999, wards 100 (full EQ/RS org) + 200 (no org). Each member sits in
# their own household so EQ (per-household) is tested independently of RS (per-individual). See the
# Swift test's comments for the rationale behind each profile.
REFERENCE_PAYLOAD = {
    "units": [{"unitNumber": 999, "unitType": "STAKE", "name": "Test Stake",
               "childUnits": [{"unitNumber": 100, "unitType": "WARD", "name": "Alpha Ward"},
                              {"unitNumber": 200, "unitType": "WARD", "name": "Beta Ward"}]}],
    "households": [
        {"uuid": "hh1", "unitNumber": 100, "members": [
            {"uuid": "self", "displayName": "User, Test", "sex": "MALE", "birthDate": "1980-01-01",
             "positions": [{"uuid": "pos1", "type": "STAKE_HIGH_COUNCILOR",
                            "name": "Stake High Councilor", "unitNumber": 999, "setApart": True}]}]},
        {"uuid": "hh2", "unitNumber": 100, "members": [
            {"uuid": "uuid-B", "displayName": "Member, B", "sex": "FEMALE", "birthDate": "2014-07-23",
             "positions": [{"uuid": "pos2", "type": "PRIMARY_TEACHER", "name": "Primary Teacher",
                            "unitNumber": 100}]}]},
        {"uuid": "hh5", "unitNumber": 100, "members": [
            {"uuid": "uuid-Maria", "displayName": "Member, M", "sex": "FEMALE",
             "birthDate": "1984-02-28", "positions": []}]},
        {"uuid": "hh4", "unitNumber": 100, "members": [
            {"uuid": "uuid-NoCalling", "displayName": "Member, N", "sex": "MALE",
             "birthDate": "1990-03-03", "positions": []}]},
        {"uuid": "hh3", "unitNumber": 200, "members": [
            {"uuid": "uuid-Uncovered", "displayName": "Member, U", "sex": "FEMALE",
             "birthDate": "1992-05-05", "positions": []}]},
        {"uuid": "hh-multiB", "unitNumber": 100, "members": [
            {"uuid": "uuid-Multi", "displayName": "Member, X", "sex": "MALE", "positions": []}]},
        {"uuid": "hh-multiA", "unitNumber": 100, "members": [
            {"uuid": "uuid-Multi", "displayName": "Member, X", "sex": "MALE", "positions": []}]},
    ],
    "ministeringBrothers": [{"unitNumber": 100, "districts": [
        {"uuid": "d1", "name": "District 1",
         "companionships": [{"uuid": "c1", "companions": ["self"], "households": ["hh2"]}]},
        {"uuid": "d2", "name": "District 2",
         "companionships": [{"uuid": "c2", "companions": ["mb-minister"], "households": ["hh-multiB"]}]},
    ], "unassignedHouseholds": ["hh1", "hh4", "hh5", "hh-multiA"]}],
    "ministeringSisters": [{"unitNumber": 100, "districts": [{"uuid": "sd1", "name": "S District 1",
        "companionships": [
            {"uuid": "sc1", "companions": ["uuid-B"], "sisters": ["ext-sister", "uuid-Maria"]},
            {"uuid": "sc2", "companions": ["ext-minister", "uuid-Maria"], "sisters": ["uuid-B"]},
        ]}], "unassignedSisters": []}],
}


def _index():
    return MinisteringIndex(REFERENCE_PAYLOAD)


# --- the ministering index (ported from SyncGoldenHourIndex) -------------------------------------

def test_eq_assigned_household_has_ministers():
    mi = _index()
    assert mi.has_ministers("uuid-B") is True       # household hh2 is EQ-assigned
    assert mi.has_assignment("uuid-B") is True       # an RS minister (sc1.companions)


def test_minister_without_assigned_ministers():
    # "self" ministers (c1.companions) but their own household hh1 is unassigned.
    mi = _index()
    assert mi.has_assignment("self") is True
    assert mi.has_ministers("self") is False


def test_no_relationship_in_covered_unit_is_false_not_unknown():
    mi = _index()
    assert mi.has_ministers("uuid-NoCalling") is False
    assert mi.has_assignment("uuid-NoCalling") is False


def test_uncovered_unit_is_unknown_not_false():
    # ward 200 carries no ministering org → genuinely unknown (None), so the adapter sentinels it and
    # the merge-upsert preserves last-good (never writes a false "No").
    mi = _index()
    assert mi.has_ministers("uuid-Uncovered") is None
    assert mi.has_assignment("uuid-Uncovered") is None


def test_rs_individual_distinguished_from_eq_household():
    # uuid-Maria: in an RS sisters list (has sisters) + an RS minister, but her household is NOT
    # EQ-assigned. The only profile that catches an EQ/RS swap bug.
    mi = _index()
    assert mi.has_ministers("uuid-Maria") is True    # RS sisters side
    assert mi.has_assignment("uuid-Maria") is True


def test_multi_household_uses_any_assigned_household():
    # uuid-Multi is in two households; hh-multiB (assigned) listed before hh-multiA (unassigned).
    # A last-write-wins lookup would wrongly report False.
    mi = _index()
    assert mi.has_ministers("uuid-Multi") is True
    assert mi.has_assignment("uuid-Multi") is False


def test_minister_absent_from_directory():
    mi = _index()
    # ext-minister appears only in the org (no household) → assignment True, brothers/sisters unknown.
    assert mi.has_assignment("ext-minister") is True
    assert mi.has_ministers("ext-minister") is None  # no household → unit unknown


def test_minister_names_resolved_via_directory():
    mi = _index()
    nm = _name_index(REFERENCE_PAYLOAD)
    # uuid-B is ministered to by "self" (EQ via hh2) and uuid-Maria (RS via sc2 → sc1.sisters).
    names = mi.minister_names("uuid-B", nm)
    assert "User, Test" in names and "Member, M" in names


# --- calling / sex from the directory ------------------------------------------------------------

def test_calling_index_present_empty_vs_absent():
    ci = _calling_index(REFERENCE_PAYLOAD)
    assert ci.get("uuid-B") == ["Primary Teacher"]   # has a calling
    assert ci.get("uuid-NoCalling") == []            # directory member, no positions → real "No"
    assert "not-in-directory" not in ci              # absent → unknown (adapter keeps the sentinel)


def test_sex_index_from_directory():
    si = _sex_index(REFERENCE_PAYLOAD)
    assert si.get("self") == "M"
    assert si.get("uuid-B") == "F"


# --- end-to-end adapt_sync: the rescue on a covenant cohort --------------------------------------

def test_adapt_sync_rescues_ministering_calling_sex_birth():
    payload = dict(REFERENCE_PAYLOAD)
    payload["covenantPathMembers"] = [
        {"id": "cov-B", "memberUuid": "uuid-B", "names": {"listed": "Member, B"},
         "unitNumber": 100, "confirmationDate": "2024-01-01"},
        {"id": "cov-U", "memberUuid": "uuid-Uncovered", "names": {"listed": "Member, U"},
         "unitNumber": 200, "confirmationDate": "2024-02-02"},
    ]
    members = {m.person_uuid: m for m in adapt_sync(payload)}
    b = members["uuid-B"]
    assert b.ministering_brothers_sisters == "Yes"
    assert b.ministering_assignment == "Yes"
    assert b.calling == "Yes"
    assert b.sex == "F"
    assert b.birth_date == "2014-07-23"
    assert (b.details or {}).get("callings") == ["Primary Teacher"]
    assert (b.details or {}).get("ministeringBrothers")  # names surfaced

    # The member in the uncovered ward keeps the sentinel for ministering (unknown, not a false "No")
    # so the merge-upsert preserves last-good; calling is a real "No" (directory present, no positions).
    u = members["uuid-Uncovered"]
    assert u.ministering_brothers_sisters == NEEDS_PROFILE
    assert u.ministering_assignment == NEEDS_PROFILE
    assert u.calling == "No"


def test_adapt_sync_no_directory_keeps_sentinels():
    # A payload with covenant people but NO households/ministering org (e.g. a degraded/minimal sync):
    # ministering + calling must stay the sentinel (so last-good is preserved), never a false "No".
    payload = {
        "units": [{"unitNumber": 999, "name": "S", "unitType": "STAKE",
                   "childUnits": [{"unitNumber": 100, "name": "W", "unitType": "WARD"}]}],
        "covenantPathMembers": [
            {"id": "x", "memberUuid": "uuid-x", "names": {"listed": "X, Y"}, "unitNumber": 100},
        ],
    }
    m = adapt_sync(payload)[0]
    assert m.ministering_brothers_sisters == NEEDS_PROFILE
    assert m.ministering_assignment == NEEDS_PROFILE
    assert m.calling == NEEDS_PROFILE
    # priesthood / recommend / patriarchal / endowment are genuinely NOT in the payload → sentinel.
    assert m.temple_recommend == NEEDS_PROFILE
    assert m.aaronic_priesthood == NEEDS_PROFILE
    assert m.patriarchal_blessing == NEEDS_PROFILE


def test_ministering_index_absent_when_no_org():
    assert MinisteringIndex({}).present is False
    assert MinisteringIndex(REFERENCE_PAYLOAD).present is True


# --- field-gap report: the "why is this blank?" diagnostic ---------------------------------------

def test_field_gap_report_attributes_reasons():
    """The structured field-gap report distinguishes a profile-only field blank because the LCR
    session is dead (re-auth needed) from a rescuable field that the bulk payload just didn't carry."""
    from covenant_path.report import CovenantPathMember, field_gap_report

    def mk(**over):
        base = dict(name="x", unit="u", baptism_date="2024", birth_date="1 Jan 1990", friends="No",
                    aaronic_priesthood=NEEDS_PROFILE, melchizedek_priesthood=NEEDS_PROFILE,
                    calling="Yes", ministering_brothers_sisters="Yes", ministering_assignment="No",
                    temple_recommend=NEEDS_PROFILE, patriarchal_blessing=NEEDS_PROFILE,
                    living_ordinance=NEEDS_PROFILE, membership_duration=None,
                    weeks_since_last_attendance=None, baptism_goal_date=None, friends_summary=None,
                    sex="M")
        base.update(over)
        return CovenantPathMember(**base)

    # LCR session DEAD (profile merge did not run): patriarchal_blessing is the ONLY genuinely
    # profile-only field, so it (and only it) gets the "re-auth" reason. Priesthood / temple-recommend /
    # endowment are now RESCUED from the bulk payload (2026-06-13), so a sentinel on those reads as a
    # bulk-payload gap, NOT "re-auth needed".
    rows = [mk() for _ in range(3)]
    rep = field_gap_report(rows, profile_merge_ran=False)
    assert rep["members"] == 3
    assert "patriarchal_blessing" in rep["fields"]
    assert rep["fields"]["patriarchal_blessing"]["missing"] == 3
    assert "re-auth" in rep["fields"]["patriarchal_blessing"]["reason"]
    # temple_recommend / priesthood / endowment are now rescuable → a sentinel = "bulk payload gap".
    assert "temple_recommend" in rep["fields"]
    assert "bulk payload" in rep["fields"]["temple_recommend"]["reason"]
    assert "bulk payload" in rep["fields"]["aaronic_priesthood"]["reason"]
    assert "bulk payload" in rep["fields"]["living_ordinance"]["reason"]
    # the already-filled rescued fields are NOT in the gap report
    assert "ministering_brothers_sisters" not in rep["fields"]
    assert "calling" not in rep["fields"]

    # A rescuable field still a sentinel (e.g. unit org gap) gets the "bulk payload this run" reason.
    rows2 = [mk(ministering_brothers_sisters=NEEDS_PROFILE)]
    rep2 = field_gap_report(rows2, profile_merge_ran=True)
    assert "bulk payload" in rep2["fields"]["ministering_brothers_sisters"]["reason"]

    # Everything filled → empty gap report.
    full = [mk(aaronic_priesthood="Yes", melchizedek_priesthood="Yes", temple_recommend="Active",
               patriarchal_blessing="Yes", living_ordinance="Yes")]
    assert field_gap_report(full, profile_merge_ran=True)["fields"] == {}


# --- priesthood office / endowment / temple recommend RESCUE (#data-gap 2026-06-13) --------------
# Verified live (stake 503991) that the bulk payload carries these three of the four "profile-only"
# fields after all: the member directory's `priesthood` OFFICE enum + `ordinances[]` (ENDOWMENT), and
# the unit-wide `templeRecommendStatus[].recommends[]` roster. Only patriarchal_blessing is genuinely
# absent. These tests pin the index builders + the eligibility-gated end-to-end rescue.

from datetime import datetime  # noqa: E402

_THIS_YEAR = datetime.now().year


def _adult_birth():
    return f"{_THIS_YEAR - 40}-01-01"          # 40yo -> 18+ now, turns 12+


def _youth_birth():
    return f"{_THIS_YEAR - 13}-01-01"          # 13yo -> turns 12+ this year, but NOT 18 now


def _long_member_conf():
    return f"{_THIS_YEAR - 5}-01-01"           # baptized 5y ago -> member >1yr


# A live-shaped payload: covenant members ALSO present in the directory with priesthood + ordinances,
# plus a unit-wide temple-recommend roster. Wards 100 (covered) + 200 (no recommend roster entry).
_RESCUE_PAYLOAD = {
    "units": [{"unitNumber": 999, "unitType": "STAKE", "name": "Stake",
               "childUnits": [{"unitNumber": 100, "unitType": "WARD", "name": "W100"},
                              {"unitNumber": 200, "unitType": "WARD", "name": "W200"}]}],
    "households": [
        # Endowed elder, active regular recommend.
        {"uuid": "h-elder", "unitNumber": 100, "members": [
            {"uuid": "u-elder", "displayName": "E, E", "sex": "MALE", "birthDate": _adult_birth(),
             "priesthood": "ELDER",
             "ordinances": [{"type": "BAPTISM"}, {"type": "CONFIRMATION"},
                            {"type": "ORDAIN_ELDER"}, {"type": "ENDOWMENT"}]}]},
        # Young deacon, NOT endowed (has ordinances but no ENDOWMENT), no recommend entry -> 'No'.
        {"uuid": "h-deacon", "unitNumber": 100, "members": [
            {"uuid": "u-deacon", "displayName": "D, D", "sex": "MALE", "birthDate": _youth_birth(),
             "priesthood": "DEACON",
             "ordinances": [{"type": "BAPTISM"}, {"type": "CONFIRMATION"}, {"type": "ORDAIN_DEACON"}]}]},
        # Adult woman, no priesthood office, endowed, active recommend.
        {"uuid": "h-sister", "unitNumber": 100, "members": [
            {"uuid": "u-sister", "displayName": "S, S", "sex": "FEMALE", "birthDate": _adult_birth(),
             "ordinances": [{"type": "BAPTISM"}, {"type": "CONFIRMATION"}, {"type": "ENDOWMENT"}]}]},
        # Member in ward 200 — in the directory but absent from the recommend roster (a real 'No').
        {"uuid": "h-w200", "unitNumber": 200, "members": [
            {"uuid": "u-w200", "displayName": "W, W", "sex": "MALE", "birthDate": _adult_birth(),
             "priesthood": "HIGH_PRIEST",
             "ordinances": [{"type": "BAPTISM"}, {"type": "ENDOWMENT"}]}]},
    ],
    "templeRecommendStatus": [
        {"unitNumber": 100, "recommends": [
            {"memberUuid": "u-elder", "type": "REGULAR", "status": "ACTIVE"},
            {"memberUuid": "u-sister", "type": "REGULAR", "status": "EXPIRED"},
            {"memberUuid": "u-sister", "type": "REGULAR", "status": "ACTIVE"},   # strongest wins
        ]},
    ],
    "covenantPathMembers": [
        {"id": "c-elder", "memberUuid": "u-elder", "names": {"listed": "E, E"},
         "unitNumber": 100, "confirmationDate": _long_member_conf()},
        {"id": "c-deacon", "memberUuid": "u-deacon", "names": {"listed": "D, D"},
         "unitNumber": 100, "confirmationDate": _long_member_conf()},
        {"id": "c-sister", "memberUuid": "u-sister", "names": {"listed": "S, S"},
         "unitNumber": 100, "confirmationDate": _long_member_conf()},
        {"id": "c-w200", "memberUuid": "u-w200", "names": {"listed": "W, W"},
         "unitNumber": 200, "confirmationDate": _long_member_conf()},
    ],
}


def test_priesthood_office_index():
    idx = _priesthood_office_index(_RESCUE_PAYLOAD)
    assert idx.get("u-elder") == "ELDER"
    assert idx.get("u-deacon") == "DEACON"
    assert "u-sister" in idx and idx["u-sister"] == ""   # in directory, no office -> real "no office"
    assert "not-in-dir" not in idx


def test_endowed_index():
    idx = _endowed_index(_RESCUE_PAYLOAD)
    assert idx.get("u-elder") is True
    assert idx.get("u-deacon") is False        # has ordinances list, but no ENDOWMENT
    assert idx.get("u-sister") is True


def test_recommend_index_strongest_label_wins():
    idx = _recommend_index(_RESCUE_PAYLOAD)
    assert idx.get("u-elder") == "Active"
    assert idx.get("u-sister") == "Active"     # ACTIVE beats the EXPIRED record
    assert "u-w200" not in idx                 # not in any roster entry


def test_adapt_sync_rescues_priesthood_endowment_recommend():
    members = {m.person_uuid: m for m in adapt_sync(_RESCUE_PAYLOAD)}

    # Endowed elder, member >1yr, adult male: full priesthood + endowed + active recommend.
    elder = members["u-elder"]
    assert elder.aaronic_priesthood == "Yes"
    assert elder.melchizedek_priesthood == "Yes"
    assert elder.living_ordinance == "Yes"
    assert elder.temple_recommend == "Active"
    assert elder.patriarchal_blessing == NEEDS_PROFILE   # genuinely not in the payload

    # Young deacon: Aaronic Yes (office), Melchizedek N/A (under 18), endowment N/A (ineligible 'No'),
    # no recommend roster entry but IS a directory member -> a real 'No'.
    deacon = members["u-deacon"]
    assert deacon.aaronic_priesthood == "Yes"
    assert deacon.melchizedek_priesthood == NA
    assert deacon.living_ordinance == NA
    assert deacon.temple_recommend == "No"

    # Adult woman: priesthood N/A (female), endowed Yes, active recommend (strongest label).
    sister = members["u-sister"]
    assert sister.aaronic_priesthood == NA
    assert sister.melchizedek_priesthood == NA
    assert sister.living_ordinance == "Yes"
    assert sister.temple_recommend == "Active"

    # Ward-200 member: directory member absent from the recommend roster -> a real 'No'.
    w200 = members["u-w200"]
    assert w200.temple_recommend == "No"
    assert w200.melchizedek_priesthood == "Yes"   # HIGH_PRIEST office, adult male, member >1yr


def test_adapt_sync_no_directory_keeps_priesthood_recommend_sentinels():
    # A covenant person NOT in any household + no recommend roster: priesthood/endowment/recommend stay
    # the sentinel so the /mlt merge (or last-good) preserves — never a false 'No' for an unknown.
    payload = {
        "units": [{"unitNumber": 999, "name": "S", "unitType": "STAKE",
                   "childUnits": [{"unitNumber": 100, "name": "W", "unitType": "WARD"}]}],
        "covenantPathMembers": [
            {"id": "x", "memberUuid": "u-x", "names": {"listed": "X, Y"}, "unitNumber": 100,
             "confirmationDate": _long_member_conf()},
        ],
    }
    m = adapt_sync(payload)[0]
    assert m.aaronic_priesthood == NEEDS_PROFILE
    assert m.melchizedek_priesthood == NEEDS_PROFILE
    assert m.living_ordinance == NEEDS_PROFILE
    assert m.temple_recommend == NEEDS_PROFILE
    assert m.patriarchal_blessing == NEEDS_PROFILE


def test_recommend_roster_absent_keeps_directory_member_sentinel():
    # A directory member with NO templeRecommendStatus container in the payload (a degraded/minimal
    # sync): temple_recommend must stay the sentinel for everyone — NOT a false stake-wide 'No' — so the
    # merge preserves last-good. Priesthood/endowment (per-member directory data) still resolve.
    payload = {
        "units": [{"unitNumber": 999, "name": "S", "unitType": "STAKE",
                   "childUnits": [{"unitNumber": 100, "name": "W", "unitType": "WARD"}]}],
        "households": [
            {"uuid": "h", "unitNumber": 100, "members": [
                {"uuid": "u-m", "sex": "MALE", "birthDate": f"{_THIS_YEAR - 40}-01-01",
                 "priesthood": "ELDER", "ordinances": [{"type": "ENDOWMENT"}]}]},
        ],
        "covenantPathMembers": [
            {"id": "c-m", "memberUuid": "u-m", "names": {"listed": "M, M"}, "unitNumber": 100,
             "confirmationDate": _long_member_conf()},
        ],
    }
    m = {x.person_uuid: x for x in adapt_sync(payload)}["u-m"]
    assert m.temple_recommend == NEEDS_PROFILE        # roster absent -> unknown, not a false 'No'
    assert m.melchizedek_priesthood == "Yes"          # per-member directory office still resolves
    assert m.living_ordinance == "Yes"                # per-member ordinances still resolve
