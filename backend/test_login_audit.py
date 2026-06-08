"""
Verify the login_audit table: rows can be written, and ONLY admins can read them (RLS) — it holds
sign-in emails, so a non-admin must see nothing. Runs in ONE rolled-back transaction (no data
persists). After `python -m backend.apply`:  python -m backend.test_login_audit
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

    def visible_as(email):
        as_user(email)
        cur.execute("select count(*) from login_audit where email = 'audit-test@example.com'")
        n = cur.fetchone()[0]
        cur.execute("reset role")
        return n

    checks = []
    try:
        # Seed an admin + a login_audit row (as the privileged/default role — bypasses RLS, like the
        # service-role broker does on write).
        cur.execute("insert into app_admins(email,invited_by_email) values ('owner@example.com','test') "
                    "on conflict (email) do nothing")
        cur.execute("insert into login_audit (email, stake_unit, stake_name, callings, authorized, outcome) "
                    "values ('audit-test@example.com', 123, 'Test Stake', "
                    "'[\"Stake President\"]'::jsonb, 'allowed', 'allowed')")

        checks.append(("admin can read audit", visible_as("owner@example.com"), 1))
        checks.append(("non-admin sees none (PII-safe)", visible_as("stranger@example.org"), 0))
        checks.append(("unknown email sees none", visible_as(None), 0))

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
