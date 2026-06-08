"""
Verify the calling-access overrides (#3c): admin-gated add/remove, admin-only visibility (RLS), and
that a non-admin can't add one. Runs in ONE rolled-back transaction. After `python -m backend.apply`:
  python -m backend.test_calling_overrides
"""

from __future__ import annotations

import json
import sys

from backend import db


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("set client_min_messages = warning")

    def as_user(email=None):
        cur.execute("set local role authenticated")
        claims = {"role": "authenticated"}
        if email:
            claims["email"] = email
        cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))

    def rpc(email, sql, *args):
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

    def count_as(email):
        as_user(email)
        cur.execute("select count(*) from calling_access_overrides where calling_match='Ward Mission Leader'")
        n = cur.fetchone()[0]
        cur.execute("reset role")
        return n

    checks = []
    try:
        cur.execute("insert into app_admins(email,invited_by_email) values ('owner@example.com','test') "
                    "on conflict (email) do nothing")

        # Non-admin cannot add an override.
        err = rpc("stranger@example.org", "select add_calling_override('Ward Mission Leader', true, 'x')")
        checks.append(("non-admin add blocked", err is not None and "not authorized" in err, True))

        # Admin adds one; it's visible to the admin, not to a stranger (RLS).
        err = rpc("owner@example.com", "select add_calling_override('Ward Mission Leader', true, 'EQ teaching')")
        checks.append(("admin add succeeds", err is None, True))
        checks.append(("admin sees override", count_as("owner@example.com"), 1))
        checks.append(("non-admin sees none", count_as("stranger@example.org"), 0))

        # Idempotent upsert on calling_match.
        rpc("owner@example.com", "select add_calling_override('Ward Mission Leader', false, 'changed')")
        cur.execute("select grants_access from calling_access_overrides where calling_match='Ward Mission Leader'")
        checks.append(("upsert updates grants_access", cur.fetchone()[0], False))

        # Admin removes it.
        cur.execute("select id from calling_access_overrides where calling_match='Ward Mission Leader'")
        oid = cur.fetchone()[0]
        rpc("owner@example.com", "select remove_calling_override(%s)" % oid)
        checks.append(("admin remove works", count_as("owner@example.com"), 0))

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
