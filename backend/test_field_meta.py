"""
Verify per-field freshness (field_meta, migration 0036): a FETCHED field stamps `f` fresh; a SENTINEL
(not-fetched) field PRESERVES its prior `f` while bumping `t`, so staleness grows and we never blank
a value we didn't get. ONE rolled-back transaction (no data persists).
  python -m backend.test_field_meta
"""

from __future__ import annotations

import sys

from backend import db


class _NoCommit:
    def __init__(self, conn):
        self._c = conn

    def cursor(self, *a, **k):
        return self._c.cursor(*a, **k)

    def commit(self):
        pass


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()
    proxy = _NoCommit(conn)
    try:
        cur.execute("insert into stakes(unit_number,name) values (999997,'Field Meta Test') returning id")
        stake_id = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888021,'W') returning id", (stake_id,))
        unit_id = cur.fetchone()[0]
        ubn = {888021: unit_id}

        def meta_of(puid):
            cur.execute("select field_meta from members where stake_id=%s and person_uuid=%s", (stake_id, puid))
            return cur.fetchone()[0]

        # Run 1: ministering_assignment FETCHED ('Yes'); baptism_date SENTINEL (not fetched).
        db.upsert_members(proxy, stake_id, [{
            "person_uuid": "fm-1", "name": "A", "unit_number": 888021,
            "ministering_assignment": "Yes", "baptism_date": "needs-profile-api"}], ubn)
        meta = meta_of("fm-1")
        first_ma_f = meta["ministering_assignment"]["f"]

        # Run 2: baptism_date now FETCHED; ministering_assignment now SENTINEL (must KEEP its prior f).
        db.upsert_members(proxy, stake_id, [{
            "person_uuid": "fm-1", "name": "A", "unit_number": 888021,
            "ministering_assignment": "blocked: insufficient calling access",
            "baptism_date": "1 Jan 2025"}], ubn)
        meta2 = meta_of("fm-1")

        checks = [
            ("fetched stamps f", "f" in meta.get("ministering_assignment", {}), True),
            ("sentinel: no f", "f" not in meta.get("baptism_date", {}), True),
            ("sentinel: has t", "t" in meta.get("baptism_date", {}), True),
            ("later fetch stamps f", "f" in meta2.get("baptism_date", {}), True),
            ("sentinel preserves prior f", meta2["ministering_assignment"]["f"] == first_ma_f, True),
            ("sentinel bumps t", meta2["ministering_assignment"]["t"] > first_ma_f, True),
        ]
        ok = True
        for n, g, w in checks:
            ok = ok and (g == w)
            print(f"  [{'PASS' if g == w else 'FAIL'}] {n}: {g}")
        return 0 if ok else 1
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
