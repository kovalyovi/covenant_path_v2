"""
Verify the power-user invitation system against the live DB — invite clones the
caller's exact scope to any email, recursively, with no privilege escalation, and
revoke removes access. Runs in ONE transaction that is ROLLED BACK (no test data
persists). Run after `python -m backend.apply`:  python -m backend.test_power_users
"""

from __future__ import annotations

import json
import sys

from backend import db


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()

    def caller(email=None):
        claims = {"role": "authenticated"}
        if email:
            claims["email"] = email
        cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))

    def seen(email):
        cur.execute("set local role authenticated")
        caller(email)
        cur.execute("select count(*) from members")
        n = cur.fetchone()[0]
        cur.execute("reset role")
        return n

    checks = []
    try:
        cur.execute("select id from stakes where unit_number=503991")
        sid = cur.fetchone()[0]
        cur.execute("select email from user_roles where role='stake_leader' and email is not null limit 1")
        stake_email = cur.fetchone()[0]
        cur.execute("select id from units where stake_id=%s limit 1", (sid,))
        unit_id = cur.fetchone()[0]
        cur.execute("select count(*) from members where unit_id=%s", (unit_id,))
        ward_n = cur.fetchone()[0]
        cur.execute("select count(*) from members where stake_id=%s", (sid,))
        stake_n = cur.fetchone()[0]

        caller(stake_email)
        cur.execute("select invite_power_user('Missionary@Example.org')")
        checks.append(("stake invite -> full scope", seen('missionary@example.org'), stake_n))

        caller('missionary@example.org')
        cur.execute("select invite_power_user('friend@example.org')")
        checks.append(("recursive invite", seen('friend@example.org'), stake_n))

        cur.execute("insert into user_roles (stake_id, unit_id, role, email, source) "
                    "values (%s,%s,'ward_leader','wardguy@test.org','calling')", (sid, unit_id))
        caller('wardguy@test.org')
        cur.execute("select invite_power_user('wardinvitee@test.org')")
        checks.append(("ward invitee scoped to ward (no escalation)", seen('wardinvitee@test.org'), ward_n))

        # stake leader grants WARD-only access (unit-scoped invite) — manual ward path (#21)
        caller(stake_email)
        cur.execute("select invite_power_user('wardonly@example.org', %s)", (unit_id,))
        checks.append(("stake grants ward-only scope", seen('wardonly@example.org'), ward_n))

        caller(stake_email)
        cur.execute("select revoke_power_user('missionary@example.org')")
        checks.append(("revoke", seen('missionary@example.org'), 0))

        ok = True
        for name, got, want in checks:
            good = got == want
            ok = ok and good
            print(f"  [{'PASS' if good else 'FAIL'}] {name}: {got} (expected {want})")
        # escalation sanity: ward != stake so the scoping test is meaningful
        if ward_n >= stake_n:
            print("  [warn] ward size == stake size; escalation test is weak")
        return 0 if ok else 1
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
