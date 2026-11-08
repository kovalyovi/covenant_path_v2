#!/usr/bin/env python3
"""Verify the aligned Families derivation (D81) against a fresh raw /api/v5/sync capture.

Compares List A (derive_part_member_families) to LCR's own ground truth:
the per-unit `unitStatistics[].membersOfRecordAge9OrOlderUuids` sets.
Usage: python scripts/verify_families_derivation.py [path-to-raw-payload]
Default path: tools/output/stake_data_raw.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from covenant_path.membertools_adapter import (  # noqa: E402
    derive_part_member_families,
    derive_part_member_families_list_b,
)


def main() -> int:
    raw_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tools" / "output" / "stake_data_raw.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    households = payload.get("households") or []
    people = sum(len(hh.get("members") or []) for hh in households if isinstance(hh, dict))

    # Ground truth: LCR's per-unit uuid sets.
    stat_uuids: set[str] = set()
    per_unit: dict[int, int] = {}
    for st in payload.get("unitStatistics") or []:
        if not isinstance(st, dict):
            continue
        v = st.get("membersOfRecordAge9OrOlderUuids")
        if isinstance(v, list):
            unit = st.get("unitNumber")
            per_unit[int(unit)] = len(v) if unit is not None else len(v)
            stat_uuids.update(u for u in v if isinstance(u, str))

    list_a = derive_part_member_families(payload)
    list_b = derive_part_member_families_list_b(payload)
    # List A rows carry no person uuid (the table stores household + name + birth date), so map
    # each row back to its uuid through the derivation's own _pmf_members normalization.
    from covenant_path.membertools_adapter import _pmf_members  # noqa: E402
    from datetime import date as _date  # noqa: E402
    _today = _date.today()
    _lookup: dict[tuple, str] = {}
    for hh in households:
        if not isinstance(hh, dict):
            continue
        _hu = hh.get("uuid") or hh.get("householdUuid")
        for _m in _pmf_members(hh, _today):
            _lookup[(_hu, _m["name"], (_m["birth_raw"] or "")[:10] or None)] = _m["uuid"]
    a_uuids = set()
    _unmapped = 0
    for r in list_a:
        _u = _lookup.get((r["household_uuid"], r["nonmember_name"], r["nonmember_birth_date"]))
        if _u:
            a_uuids.add(_u)
        else:
            _unmapped += 1

    missing = stat_uuids - a_uuids   # in LCR's statistic but NOT in List A
    extra = a_uuids - stat_uuids     # in List A but NOT in LCR's statistic (fallback path)

    print(f"payload: {raw_path}  ({raw_path.stat().st_size / 1e6:.1f} MB)")
    print(f"households: {len(households)}  people: {people}")
    print(f"unitStatistics entries: {len(payload.get('unitStatistics') or [])}  "
          f"units shipping the 9+ set: {len(per_unit)}")
    print(f"LCR membersOfRecordAge9OrOlder (ground truth): {len(stat_uuids)}")
    print(f"List A rows: {len(list_a)}  (missing vs truth: {len(missing)}, "
          f"extra vs truth: {len(extra)})" + (f"  [unmapped rows: {_unmapped}]" if _unmapped else ""))
    print(f"List B rows: {len(list_b)}  "
          f"({sum(1 for r in list_b if r.get('basis') == 'unbaptized_spouse_in_home')} confirmed, "
          f"{sum(1 for r in list_b if r.get('basis') == 'spouse_not_on_record')} candidate)")

    # Why would a statistic uuid miss List A? List A requires a MEMBER anchor in the household.
    # Check each missing uuid's household for a member.
    if missing:
        print(f"\n-- {len(missing)} statistic uuid(s) NOT in List A --")
        by_uuid = {}
        for hh in households:
            if not isinstance(hh, dict):
                continue
            for m in hh.get("members") or []:
                if isinstance(m, dict) and (m.get("uuid") or m.get("memberUuid")):
                    by_uuid[str(m.get("uuid") or m.get("memberUuid"))] = (hh, m)
        no_anchor = 0
        for u in sorted(missing):
            hh, m = by_uuid.get(u, (None, None))
            if hh is None:
                print(f"  {u}: not found in any household")
                continue
            members = hh.get("members") or []
            has_member = any(
                isinstance(x, dict) and "MEMBER" in (x.get("classifications") or [])
                for x in members)
            if not has_member:
                no_anchor += 1
            print(f"  {u}: household has {len(members)} person(s), "
                  f"member anchor: {'yes' if has_member else 'NO'}")
        print(f"  of these, {no_anchor} have NO member anchor in their household "
              f"(expected List A exclusion)")
    if extra:
        print(f"\n-- {len(extra)} List A row(s) NOT in LCR's statistic (fallback derivation) --")
        for u in sorted(extra)[:10]:
            print(f"  {u}")
        if len(extra) > 10:
            print(f"  ... and {len(extra) - 10} more")
    print(f"\nVERDICT: List A {'== truth' if not missing and not extra else 'differs — see above'}")
    return 0 if not missing and not extra else 1


if __name__ == "__main__":
    sys.exit(main())
