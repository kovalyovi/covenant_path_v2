"""
Verify Row-Level Security enforces the stake/ward access model — against the live DB.

Seeds a throwaway stake with two wards (A, B) and a member in each, plus two users:
a stake_leader (whole stake) and a ward_leader (Ward A only). It then runs SELECTs as
each user by switching to the `authenticated` role and setting the JWT `sub` claim
(so auth.uid() resolves), and asserts:

  stake_leader sees BOTH members; ward_leader sees ONLY Ward A's member; anon sees none.

Everything runs in ONE transaction that is ROLLED BACK, so no test data persists.
Run after `python -m backend.apply`:  python -m backend.test_rls
"""

from __future__ import annotations

import json
import sys
import uuid

from backend import db


def _become(cur, auth_id: str | None) -> None:
    cur.execute("set local role authenticated")
    claims = json.dumps({"sub": auth_id, "role": "authenticated"}) if auth_id else "{}"
    cur.execute("select set_config('request.jwt.claims', %s, true)", (claims,))


def _reset(cur) -> None:
    cur.execute("reset role")


def _count_members(cur, auth_id: str | None) -> int:
    _become(cur, auth_id)
    cur.execute("select count(*) from members where person_uuid in ('rls-a','rls-b')")
    n = cur.fetchone()[0]
    _reset(cur)
    return n


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("insert into stakes(unit_number,name) values (999999,'RLS Test') "
                    "returning id")
        stake_id = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888001,'Ward A') "
                    "returning id", (stake_id,))
        unit_a = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888002,'Ward B') "
                    "returning id", (stake_id,))
        unit_b = cur.fetchone()[0]
        cur.execute("insert into members(stake_id,unit_id,person_uuid,name) "
                    "values (%s,%s,'rls-a','Alice'),(%s,%s,'rls-b','Bob')",
                    (stake_id, unit_a, stake_id, unit_b))
        stake_leader, ward_leader = str(uuid.uuid4()), str(uuid.uuid4())
        cur.execute("insert into user_roles(auth_id,stake_id,unit_id,role) "
                    "values (%s,%s,NULL,'stake_leader')", (stake_leader, stake_id))
        cur.execute("insert into user_roles(auth_id,stake_id,unit_id,role) "
                    "values (%s,%s,%s,'ward_leader')", (ward_leader, stake_id, unit_a))

        sl = _count_members(cur, stake_leader)
        wl = _count_members(cur, ward_leader)
        anon = _count_members(cur, None)

        checks = [("stake_leader sees both", sl, 2),
                  ("ward_leader sees only Ward A", wl, 1),
                  ("anon sees none", anon, 0)]
        ok = True
        for name, got, want in checks:
            status = "PASS" if got == want else "FAIL"
            ok = ok and got == want
            print(f"  [{status}] {name}: saw {got} (expected {want})")
        return 0 if ok else 1
    finally:
        conn.rollback()  # discard all test data
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
