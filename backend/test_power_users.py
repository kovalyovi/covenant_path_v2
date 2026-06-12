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

        # DBRLS-03: a co-leader who did NOT issue the invite (and isn't an admin) cannot revoke it.
        cur.execute("insert into user_roles (stake_id, unit_id, role, email, source) "
                    "values (%s,null,'stake_leader','coleader@test.org','calling')", (sid,))
        caller('coleader@test.org')
        cur.execute("select revoke_power_user('missionary@example.org')")
        checks.append(("DBRLS-03 non-inviter cannot revoke", seen('missionary@example.org'), stake_n))

        # DBRLS-02: a credential write with NO access posture must NOT mint a stake_leader role;
        # an access-bearing write (the real enroll path) does. Trigger: bind_provider_stake_role.
        cur.execute("insert into stake_credentials "
                    "(stake_id, principal_email, credential_enc, access_rank, granting_role_ids, revoked) "
                    "values (%s,'spoof@evil.test','x',null,null,false) on conflict (stake_id) do update set "
                    "principal_email=excluded.principal_email, access_rank=excluded.access_rank, "
                    "granting_role_ids=excluded.granting_role_ids, credential_enc=excluded.credential_enc, "
                    "revoked=excluded.revoked", (sid,))
        cur.execute("select count(*) from user_roles where stake_id=%s and lower(email)='spoof@evil.test'", (sid,))
        checks.append(("DBRLS-02 bare credential write binds no role", cur.fetchone()[0], 0))
        cur.execute("update stake_credentials set principal_email='realleader@example.org', "
                    "access_rank=10, granting_role_ids=array[1]::integer[] where stake_id=%s", (sid,))
        cur.execute("select count(*) from user_roles where stake_id=%s and lower(email)='realleader@example.org'", (sid,))
        checks.append(("DBRLS-02 access-bearing write binds role", cur.fetchone()[0], 1))

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
