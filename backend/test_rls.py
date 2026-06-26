"""
Verify Row-Level Security enforces the stake/ward access model — against the live DB.

Seeds TWO throwaway stakes:
  • Stake 1 with wards A + B and a member in each (rls-a, rls-b)
  • Stake 2 with ward C and one member (rls-c)
and several users: a whole-stake leader and a ward-only leader in Stake 1 (keyed by
auth_id), an EMAIL-keyed whole-stake leader in Stake 1 (the email/Google login path —
auth_id NULL, matched by the JWT email claim, exactly how ilia.kovaliov signs in), and a
whole-stake leader in Stake 2.

It runs SELECTs as each user by switching to the `authenticated` role and setting the JWT
claims (so auth.uid()/auth.jwt()->>'email' resolve) and asserts the FULL isolation matrix:

  stake_leader      -> sees ONLY its own stake's members (never the other stake's)
  ward_leader       -> sees ONLY its ward's member
  email stake_leader-> sees ONLY its own stake's members (cross-stake isolation on the email path)
  anon              -> sees none

This regresses the "I see Springville data under my Raleigh login" class of bug at the
RLS layer: no login may ever see a stake it is not provisioned for.

Everything runs in ONE transaction that is ROLLED BACK, so no test data persists.
Run after `python -m backend.apply`:  python -m backend.test_rls
"""

from __future__ import annotations

import json
import sys
import uuid

from backend import db

_SEEDED = ("rls-a", "rls-b", "rls-c")


def _visible(cur, *, auth_id: str | None = None, email: str | None = None) -> set[str]:
    """The set of seeded person_uuids this principal can SELECT, under RLS, as `authenticated`."""
    cur.execute("set local role authenticated")
    claims: dict = {"role": "authenticated"}
    if auth_id:
        claims["sub"] = auth_id
    if email:
        claims["email"] = email
    cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
    cur.execute("select person_uuid from members where person_uuid in %s", (_SEEDED,))
    seen = {r[0] for r in cur.fetchall()}
    cur.execute("reset role")
    return seen


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # --- Stake 1: two wards, a member in each ---------------------------------------------
        cur.execute("insert into stakes(unit_number,name) values (999999,'RLS Test 1') returning id")
        stake1 = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888001,'Ward A') returning id",
                    (stake1,))
        unit_a = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888002,'Ward B') returning id",
                    (stake1,))
        unit_b = cur.fetchone()[0]
        cur.execute("insert into members(stake_id,unit_id,person_uuid,name) "
                    "values (%s,%s,'rls-a','Alice'),(%s,%s,'rls-b','Bob')",
                    (stake1, unit_a, stake1, unit_b))

        # --- Stake 2: a different stake the Stake-1 users must NEVER see -----------------------
        cur.execute("insert into stakes(unit_number,name) values (999998,'RLS Test 2') returning id")
        stake2 = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888003,'Ward C') returning id",
                    (stake2,))
        unit_c = cur.fetchone()[0]
        cur.execute("insert into members(stake_id,unit_id,person_uuid,name) values (%s,%s,'rls-c','Carol')",
                    (stake2, unit_c))

        # --- Users ----------------------------------------------------------------------------
        sl1, wl_a, sl2 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        email_leader = f"rls-{uuid.uuid4().hex[:8]}@example.test"
        cur.execute("insert into user_roles(auth_id,stake_id,unit_id,role) values (%s,%s,NULL,'stake_leader')",
                    (sl1, stake1))
        cur.execute("insert into user_roles(auth_id,stake_id,unit_id,role) values (%s,%s,%s,'ward_leader')",
                    (wl_a, stake1, unit_a))
        cur.execute("insert into user_roles(auth_id,stake_id,unit_id,role) values (%s,%s,NULL,'stake_leader')",
                    (sl2, stake2))
        # Email-keyed whole-stake leader of Stake 1 (auth_id NULL) — the email/Google login path.
        cur.execute("insert into user_roles(auth_id,email,stake_id,unit_id,role) "
                    "values (NULL,%s,%s,NULL,'stake_leader')", (email_leader, stake1))

        v_sl1 = _visible(cur, auth_id=sl1)
        v_wl_a = _visible(cur, auth_id=wl_a)
        v_sl2 = _visible(cur, auth_id=sl2)
        v_email = _visible(cur, email=email_leader)
        v_anon = _visible(cur)

        checks = [
            ("stake_leader(1) sees its own stake", v_sl1, {"rls-a", "rls-b"}),
            ("stake_leader(1) is ISOLATED from stake 2", "rls-c" in v_sl1, False),
            ("ward_leader(A) sees only Ward A", v_wl_a, {"rls-a"}),
            ("stake_leader(2) sees its own stake", v_sl2, {"rls-c"}),
            ("stake_leader(2) is ISOLATED from stake 1", v_sl2 & {"rls-a", "rls-b"}, set()),
            ("email stake_leader(1) sees its own stake", v_email, {"rls-a", "rls-b"}),
            ("email stake_leader(1) is ISOLATED from stake 2", "rls-c" in v_email, False),
            ("anon sees none", v_anon, set()),
        ]
        ok = True
        for name, got, want in checks:
            passed = got == want
            ok = ok and passed
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}: saw {got!r} (expected {want!r})")
        return 0 if ok else 1
    finally:
        conn.rollback()  # discard all test data
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
