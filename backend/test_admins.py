"""
Verify the app_admins model against the live DB: is_admin() reflects the JWT email,
invite/revoke are admin-gated and escalation-safe, and you can't revoke yourself. Runs in
ONE transaction that is ROLLED BACK (seeded admin and test rows do not persist). Run after
`python -m backend.apply`:  python -m backend.test_admins
"""

from __future__ import annotations

import json
import sys

from backend import db


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("set client_min_messages = warning")  # silence SECURITY DEFINER notices

    def as_user(email=None):
        cur.execute("set local role authenticated")
        claims = {"role": "authenticated"}
        if email:
            claims["email"] = email
        cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))

    def is_admin(email):
        as_user(email)
        cur.execute("select is_admin()")
        v = cur.fetchone()[0]
        cur.execute("reset role")
        return v

    def rpc(email, sql, *args):
        # A raised exception aborts the transaction, so wrap each call in a savepoint
        # we can roll back to — otherwise the next statement hits "transaction aborted".
        as_user(email)
        cur.execute("savepoint sp")
        try:
            cur.execute(sql, args)
            cur.execute("release savepoint sp")
            err = None
        except Exception as e:  # noqa: BLE001
            err = str(e).splitlines()[0]
            cur.execute("rollback to savepoint sp")
        cur.execute("reset role")
        return err

    checks = []
    try:
        # The migration seeds ilia.kovaliov@gmail.com as the first admin.
        admin = "ilia.kovaliov@gmail.com"
        checks.append(("seeded admin is_admin", is_admin(admin), True))
        checks.append(("stranger is not admin", is_admin("stranger@example.org"), False))

        # A non-admin cannot invite.
        err = rpc("stranger@example.org", "select invite_admin('x@example.org')")
        checks.append(("non-admin invite blocked", err is not None and "not authorized" in err, True))

        # An admin can invite; the invitee becomes an admin.
        err = rpc(admin, "select invite_admin('NewAdmin@Example.org')")
        checks.append(("admin invite succeeds", err is None, True))
        checks.append(("invitee is now admin", is_admin("newadmin@example.org"), True))

        # The new admin can invite further (recursive), and revoke others.
        err = rpc("newadmin@example.org", "select invite_admin('third@example.org')")
        checks.append(("recursive invite", err is None and is_admin("third@example.org"), True))

        # You cannot revoke yourself (guarantees >=1 admin remains).
        err = rpc(admin, "select revoke_admin(%s)" % "'ilia.kovaliov@gmail.com'")
        checks.append(("cannot revoke self", err is not None and "yourself" in err, True))

        # Revoke works for others.
        rpc(admin, "select revoke_admin('third@example.org')")
        checks.append(("revoke removes admin", is_admin("third@example.org"), False))

        ok = True
        for name, got, want in checks:
            good = got == want
            ok = ok and good
            print(f"  [{'PASS' if good else 'FAIL'}] {name}: {got} (expected {want})")
        return 0 if ok else 1
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
