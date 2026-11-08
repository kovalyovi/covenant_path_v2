"""
Offline tests for part-member families, Lists A + B (migration 0067) — no network, no DB.

Derivation (covenant_path.membertools_adapter.derive_part_member_families /
derive_part_member_families_list_b), aligned to the verified model in
rickybloomfield/Mission-KPIs (docs/part-member-families.md, PartMemberFamilyReport.swift;
capture: 2,661 people / 1,374 households, `MEMBER` vs `mrn` agreed 2,597/2,597):

- Membership is `classifications[]` containing `MEMBER` (fallback: an `mrn`), NOT the ordinances
  list — non-members may carry no `ordinances` key at all, so an ordinances-based derivation
  silently returns 0 rows.
- List A: LCR's per-unit uuid set `unitStatistics[].membersOfRecordAge9OrOlderUuids` when shipped,
  else `!isMemberOfRecord && age >= 9`. Not children-only: adults are included.
- List B, graded: `unbaptized_spouse_in_home` (unbaptized adult + married member) and
  `spouse_not_on_record` (single member adult + couple-form listed name, spouse name parsed —
  a candidate, not a confirmation). Never "married alone": a lone married member under a
  single-name household is NOT listed (mostly widows/single members on Ricky's capture).
- The upsert (backend.db.upsert_part_member_families) writes ONLY sync-derived columns: the SQL
  it issues must not touch status / Do Not Contact / notes, which leaders own.

Run: python -m pytest tests/test_part_member_families.py -q
"""

from __future__ import annotations

from datetime import date

import psycopg2.extras

from covenant_path.membertools_adapter import (
    derive_part_member_families, derive_part_member_families_list_b)


TODAY = date(2026, 11, 8)

UNITS = [{"unitNumber": 999, "unitType": "STAKE", "name": "Test Stake",
          "childUnits": [{"unitNumber": 100, "unitType": "WARD", "name": "Alpha Ward"}]}]


def _hh(uuid, members, unit=100, name="Smith Household", listed=None):
    hh = {"uuid": uuid, "name": name, "unitNumber": unit, "members": members}
    if listed is not None:
        hh["names"] = {"listed": listed}
    return hh


def _m(uuid, name, birth, *, member=True, age_group="ADULT"):
    """A directory member. Membership is the `classifications` MEMBER flag (or an `mrn`); the
    ordinances list is deliberately NOT part of the derivation."""
    m = {"uuid": uuid, "displayName": name, "birthDate": birth, "ageGroup": age_group}
    if member:
        m["classifications"] = ["MEMBER"]
        m["mrn"] = f"MRN-{uuid}"
    else:
        m["classifications"] = []
    return m


def _baptized(uuid="parent", name="Smith, John", birth="1985-03-04"):
    return _m(uuid, name, birth)


def _child(uuid="kid", name="Smith, Jane", birth="2014-05-06"):
    return _m(uuid, name, birth, member=False, age_group="CHILD")


def _payload(households, stats=None):
    return {"units": UNITS, "households": households,
            "unitStatistics": stats if stats is not None else []}


# --- List A --------------------------------------------------------------------------------------


def test_baptized_parent_plus_unbaptized_child_12_is_list_a():
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), _child()])]), today=TODAY)
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "lcr_list_a" and r["nonmember_role"] == "child"
    assert r["nonmember_name"] == "Smith, Jane" and r["age_years"] == 12
    assert r["age_group"] == "CHILD"
    assert r["member_person_uuid"] == "parent" and r["member_name"] == "Smith, John"
    assert r["household_uuid"] == "hh1" and r["household_name"] == "Smith Household"
    assert r["unit_number"] == 100 and r["unit_name"] == "Alpha Ward"


def test_child_aged_9_exactly_is_included_and_8_is_not():
    nine = _child("k9", "Smith, Nine", "2017-11-08")   # turns 9 today
    eight = _child("k8", "Smith, Eight", "2017-11-09")  # 8 until tomorrow
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), nine, eight])]), today=TODAY)
    assert [r["nonmember_name"] for r in rows] == ["Smith, Nine"]


def test_member_child_is_not_a_candidate():
    member_kid = _m("bk", "Smith, Baptized", "2012-01-01", member=True, age_group="CHILD")
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), member_kid])]), today=TODAY)
    assert rows == []


def test_list_a_uses_the_lcr_uuid_set_when_shipped():
    # The unit ships membersOfRecordAge9OrOlderUuids: membership in the set decides, not the age.
    stats = [{"unitNumber": 100, "membersOfRecordAge9OrOlderUuids": ["kid"]}]
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), _child()])], stats=stats), today=TODAY)
    assert [r["nonmember_name"] for r in rows] == ["Smith, Jane"]
    # … and a 9+ non-member NOT in the set is excluded for that unit.
    stats = [{"unitNumber": 100, "membersOfRecordAge9OrOlderUuids": []}]
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), _child()])], stats=stats), today=TODAY)
    assert rows == []


def test_list_a_includes_unbaptized_adults_not_just_children():
    # Ricky's capture: 20 of 64 List A rows were adults, up to age 38.
    adult = _m("a1", "Smith, Adult", "1990-01-01", member=False, age_group="ADULT")
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), adult])]), today=TODAY)
    assert len(rows) == 1 and rows[0]["age_group"] == "ADULT"


def test_household_with_no_member_anchor_is_not_part_member():
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_child("k1"), _child("k2", "Smith, Two", "2013-01-01")])]),
        today=TODAY)
    assert rows == []


def test_non_member_without_ordinances_key_is_still_found():
    # The old ordinances-based derivation returned 0 rows for non-members carrying no
    # `ordinances` key at all — the membership flag is what decides, not ordinances.
    no_ords = _m("u1", "Smith, Unknown", "2010-01-01", member=False, age_group="CHILD")
    rows = derive_part_member_families(
        _payload([_hh("hh1", [_baptized(), no_ords])]), today=TODAY)
    assert len(rows) == 1


def test_member_link_is_oldest_member_adult():
    mom = _baptized("mom", "Smith, Mary", "1988-06-01")
    dad = _baptized("dad", "Smith, John", "1985-03-04")
    rows = derive_part_member_families(
        _payload([_hh("hh1", [mom, dad, _child()])]), today=TODAY)
    assert rows[0]["member_person_uuid"] == "dad"


def test_empty_payload_derives_nothing():
    assert derive_part_member_families({}, today=TODAY) == []
    assert derive_part_member_families({"households": []}, today=TODAY) == []


# --- List B --------------------------------------------------------------------------------------


def test_list_b_unbaptized_spouse_in_home():
    spouse = _m("sp", "Smith, Ana", "1987-02-02", member=False, age_group="ADULT")
    stats = [{"unitNumber": 100, "marriedAdultsUuids": ["parent"]}]
    rows = derive_part_member_families_list_b(
        _payload([_hh("hh1", [_baptized(), spouse])], stats=stats), today=TODAY)
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "lcr_list_b" and r["basis"] == "unbaptized_spouse_in_home"
    assert r["nonmember_role"] == "spouse" and r["nonmember_name"] == "Smith, Ana"
    assert r["member_person_uuid"] == "parent"


def test_list_b_spouse_not_on_record_parses_the_name():
    # "Adkins, Roger & Jane" with only Roger on the roster: the record names Jane.
    roger = _m("roger", "Adkins, Roger", "1980-01-01", member=True, age_group="ADULT")
    rows = derive_part_member_families_list_b(
        _payload([_hh("hh1", [roger], listed="Adkins, Roger & Jane")]), today=TODAY)
    assert len(rows) == 1
    r = rows[0]
    assert r["basis"] == "spouse_not_on_record"
    assert r["named_spouse"] == "Jane Adkins" and r["nonmember_name"] == "Jane Adkins"
    assert r["member_person_uuid"] == "roger"


def test_list_b_married_alone_under_a_single_name_is_not_listed():
    # The false-positive trap: a lone married member is NOT a part-member family on its own
    # (mostly widows / single members on Ricky's capture).
    roger = _m("roger", "Adkins, Roger", "1980-01-01", member=True, age_group="ADULT")
    stats = [{"unitNumber": 100, "marriedAdultsUuids": ["roger"]}]
    rows = derive_part_member_families_list_b(
        _payload([_hh("hh1", [roger], listed="Adkins, Roger")], stats=stats), today=TODAY)
    assert rows == []


def test_list_b_couple_both_on_record_is_not_listed():
    john = _baptized("john", "Smith, John", "1985-03-04")
    mary = _m("mary", "Smith, Mary", "1988-06-01", member=True, age_group="ADULT")
    rows = derive_part_member_families_list_b(
        _payload([_hh("hh1", [john, mary])]), today=TODAY)
    assert rows == []


# --- the upsert never overwrites leader-owned state ----------------------------------------------


class _FakeCursor:
    def __init__(self):
        self.sql = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def test_upsert_writes_only_derived_columns(monkeypatch):
    from backend import db

    captured: dict = {}

    def fake_execute_values(cur, sql, rows):
        captured["sql"] = sql
        captured["rows"] = rows

    monkeypatch.setattr(psycopg2.extras, "execute_values", fake_execute_values)
    conn = _FakeConn()
    rows = [{"household_uuid": "hh1", "household_name": "Smith Household", "unit_number": 100,
             "unit_name": "Alpha Ward", "member_person_uuid": "parent", "member_name": "Smith, John",
             "nonmember_name": "Smith, Jane", "nonmember_role": "child",
             "nonmember_birth_date": "2014-05-06", "age_group": "CHILD",
             "source": "lcr_list_a", "basis": None, "named_spouse": None, "age_years": 12}]
    assert db.upsert_part_member_families(conn, "stake-1", rows, {100: "unit-100"}) == 1
    assert conn.committed is True
    sql = captured["sql"]
    # The ON CONFLICT target is the derived-rows partial unique index …
    assert "where source in ('lcr_list_a', 'lcr_list_b')" in sql
    # … and the update clause touches ONLY sync-derived columns — never status, Do Not Contact,
    # companionship, or notes (a re-derived row must not reset a family's Love/Share stage).
    update = sql.split("do update set", 1)[1]
    for forbidden in ("status", "do_not_contact", "assigned_companionship", "notes",
                      "merged_into_uuid"):
        assert forbidden not in update, f"sync must never write {forbidden}: {update}"
    assert captured["rows"][0][7] == "Smith, Jane"


def test_upsert_ignores_non_derived_rows(monkeypatch):
    from backend import db

    called: list = []
    monkeypatch.setattr(psycopg2.extras, "execute_values",
                        lambda cur, sql, rows: called.append(rows))
    conn = _FakeConn()
    manual = [{"household_uuid": None, "unit_number": 100, "unit_name": "Alpha Ward",
               "member_person_uuid": "parent", "member_name": "Smith, John",
               "nonmember_name": "Smith, Ana", "nonmember_role": "spouse",
               "nonmember_birth_date": None, "source": "manual"}]
    assert db.upsert_part_member_families(conn, "stake-1", manual, {100: "unit-100"}) == 0
    assert called == []
