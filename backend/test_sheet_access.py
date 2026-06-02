"""Offline unit tests for backend/sheet_access.py (#5 recipient rules). Run:
    python -m backend.test_sheet_access
Pure functions, no DB/network."""

from __future__ import annotations

from backend.sheet_access import (compute_recipients, is_stake_sheet_calling,
                                   is_ward_sheet_calling)


def _check(name: str, cond: bool) -> bool:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main() -> int:
    ok = True

    # --- stake-sheet callings ---
    for c in ["Stake President", "Counselor in the Stake Presidency", "Stake Clerk",
              "Stake Assistant Clerk", "Stake Executive Secretary",
              "Stake Assistant Executive Secretary"]:
        ok &= _check(f"stake-sheet: {c!r}", is_stake_sheet_calling(c))
    for c in ["High Councilor", "Bishop", "Elders Quorum President", "", None]:
        ok &= _check(f"NOT stake-sheet: {c!r}", not is_stake_sheet_calling(c))

    # --- ward-sheet callings ---
    for c in ["Bishop", "Counselor in the Bishopric", "Elders Quorum President",
              "Counselor in the Elders Quorum Presidency", "Relief Society President",
              "Counselor in the Relief Society Presidency", "Ward Mission Leader"]:
        ok &= _check(f"ward-sheet: {c!r}", is_ward_sheet_calling(c))
    for c in ["Ward Clerk", "Ward Executive Secretary", "Stake President",
              "Elders Quorum Instructor", "Sunday School President", "", None]:
        ok &= _check(f"NOT ward-sheet: {c!r}", not is_ward_sheet_calling(c))

    # --- compute_recipients ---
    roles = [
        {"email": "PrezStake@x.org", "calling_name": "Stake President", "unit_id": "s1", "unit_name": "Stake"},
        {"email": "sclerk@x.org", "calling_name": "Stake Clerk", "unit_id": "s1", "unit_name": "Stake"},
        {"email": "hc@x.org", "calling_name": "High Councilor", "unit_id": "s1", "unit_name": "Stake"},
        {"email": "bishopA@x.org", "calling_name": "Bishop", "unit_id": "wA", "unit_name": "Ward A"},
        {"email": "eqA@x.org", "calling_name": "Elders Quorum President", "unit_id": "wA", "unit_name": "Ward A"},
        {"email": "clerkA@x.org", "calling_name": "Ward Clerk", "unit_id": "wA", "unit_name": "Ward A"},
        {"email": "bishopB@x.org", "calling_name": "Bishop", "unit_id": "wB", "unit_name": "Ward B"},
        {"email": None, "calling_name": "Relief Society President", "unit_id": "wB", "unit_name": "Ward B"},
    ]
    miss = {"Ward A": [{"email": "elderSmith@missionary.org"}, {"email": ""}],
            "Ward Z (unmatched)": [{"email": "stray@x.org"}]}
    r = compute_recipients(roles, miss)

    ok &= _check("stake = president + clerk (lowercased), no HC",
                 r["stake"] == {"prezstake@x.org", "sclerk@x.org"})
    ok &= _check("ward A = bishop+EQ+missionary + stake (no ward clerk)",
                 r["wards"]["wA"] == {"bishopa@x.org", "eqa@x.org", "eldersmith@missionary.org",
                                      "prezstake@x.org", "sclerk@x.org"})
    ok &= _check("ward B = bishop + stake (RS pres had no email)",
                 r["wards"]["wB"] == {"bishopb@x.org", "prezstake@x.org", "sclerk@x.org"})
    ok &= _check("unmatched missionary unit is ignored",
                 all("stray@x.org" not in s for s in r["wards"].values()))
    ok &= _check("ward names mapped", r["ward_names"].get("wA") == "Ward A")

    print(f"\n== sheet_access: {'ALL PASS' if ok else 'FAILURES'} ==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
