"""
PHASE B — the role x table visibility matrix against a REAL test Supabase project
(RLS policies from backend/migrations; fixtures from `python -m tests.seed`).

Skips cleanly unless CP_TEST_SUPABASE_URL + CP_TEST_SUPABASE_SERVICE_ROLE_KEY are set
(and refuses to touch a URL equal to SUPABASE_URL). Optional: CP_TEST_SUPABASE_ANON_KEY
enables the anon-sees-zero assertions.

Matrix asserted (seed fixtures: 5 members — 3 in ward 999101, 2 in 999102):
  stake leader  -> members of BOTH wards, both units, the stake
  ward leader   -> ONLY their ward's members/unit
  no-role user  -> zero rows everywhere
  power user    -> the inviter's (stake leader) clone scope
  anon          -> zero rows (when anon key provided)
  admin-only    -> login_audit/app_admins: 0 rows for non-admins, visible to the admin
"""

from __future__ import annotations

import os

import pytest
import requests

URL = (os.environ.get("CP_TEST_SUPABASE_URL") or "").rstrip("/")
SERVICE_KEY = os.environ.get("CP_TEST_SUPABASE_SERVICE_ROLE_KEY") or ""
ANON_KEY = os.environ.get("CP_TEST_SUPABASE_ANON_KEY") or ""
PROD_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")

# bool(...) is load-bearing: with SUPABASE_URL unset the or-chain yields '' (a STRING), and
# pytest evaluates a STRING skipif condition as an expression -> eval('') -> SyntaxError at
# setup of every test (passed locally only because prod SUPABASE_URL happened to be exported;
# failed in CI where it deliberately isn't).
pytestmark = pytest.mark.skipif(
    bool(not URL or not SERVICE_KEY or (PROD_URL and URL == PROD_URL)),
    reason="Phase-B lane disabled: set CP_TEST_SUPABASE_URL + "
           "CP_TEST_SUPABASE_SERVICE_ROLE_KEY to a dedicated TEST project "
           "(refused when it equals SUPABASE_URL).",
)

PASSWORDS = {
    "rls.president@example.org": "pw-rls-president-1!",
    "rls.bishop@example.org": "pw-rls-bishop-1!",
    "rls.norole@example.org": "pw-rls-norole-1!",
    "rls.power@example.org": "pw-rls-power-1!",
    "rls.admin@example.org": "pw-rls-admin-1!",
}
WARD1_NAME = "Testvale 1st Ward"


@pytest.fixture(scope="module")
def tokens() -> dict[str, str]:
    """Password-grant JWTs for every seeded persona (sign in like a real client would)."""
    out: dict[str, str] = {}
    for email, password in PASSWORDS.items():
        r = requests.post(f"{URL}/auth/v1/token", params={"grant_type": "password"},
                          headers={"apikey": SERVICE_KEY, "Content-Type": "application/json"},
                          json={"email": email, "password": password}, timeout=30)
        if r.status_code != 200:
            pytest.skip(f"could not sign in {email} ({r.status_code}) — "
                        "run `python -m tests.seed` against the test project first")
        out[email] = r.json()["access_token"]
    return out


def _rows(table: str, token: str, params: dict | None = None) -> list[dict]:
    """Read a table AS the signed-in user: the user JWT decides the Postgres role, so RLS
    applies; the service key only satisfies the gateway's apikey check."""
    r = requests.get(f"{URL}/rest/v1/{table}",
                     headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {token}"},
                     params={"select": "*", **(params or {})}, timeout=30)
    assert r.status_code == 200, f"{table} as user -> {r.status_code}: {r.text[:200]}"
    return r.json()


def _anon_rows(table: str) -> list[dict]:
    r = requests.get(f"{URL}/rest/v1/{table}",
                     headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
                     params={"select": "*"}, timeout=30)
    assert r.status_code == 200, f"{table} as anon -> {r.status_code}: {r.text[:200]}"
    return r.json()


def test_stake_leader_sees_both_wards_members(tokens):
    members = _rows("members", tokens["rls.president@example.org"])
    assert len(members) == 5, [m.get("name") for m in members]
    assert len(_rows("units", tokens["rls.president@example.org"])) == 2
    assert len(_rows("stakes", tokens["rls.president@example.org"])) == 1


def test_ward_leader_sees_only_their_ward(tokens):
    members = _rows("members", tokens["rls.bishop@example.org"])
    assert len(members) == 3, [m.get("name") for m in members]
    assert {m["unit_name"] for m in members} == {WARD1_NAME}
    units = _rows("units", tokens["rls.bishop@example.org"])
    assert [u["unit_number"] for u in units] == [999101]


def test_no_role_user_sees_zero_rows(tokens):
    token = tokens["rls.norole@example.org"]
    assert _rows("members", token) == []
    assert _rows("units", token) == []
    assert _rows("stakes", token) == []
    assert _rows("user_roles", token) == []


def test_power_user_clone_matches_inviter_scope(tokens):
    president = _rows("members", tokens["rls.president@example.org"])
    power = _rows("members", tokens["rls.power@example.org"])
    assert len(power) == len(president) == 5
    roles = _rows("user_roles", tokens["rls.power@example.org"])
    assert any(r["role"] == "stake_leader" and r.get("source") == "invitation" for r in roles)


@pytest.mark.skipif(not ANON_KEY, reason="CP_TEST_SUPABASE_ANON_KEY not set")
def test_anon_sees_zero_rows():
    assert _anon_rows("members") == []
    assert _anon_rows("stakes") == []
    assert _anon_rows("login_audit") == []


def test_admin_only_tables_hidden_from_non_admins(tokens):
    for email in ("rls.president@example.org", "rls.norole@example.org",
                  "rls.power@example.org"):
        assert _rows("login_audit", tokens[email]) == [], f"{email} must not read login_audit"
        assert _rows("app_admins", tokens[email]) == [], f"{email} must not read app_admins"


def test_admin_sees_admin_tables(tokens):
    audit = _rows("login_audit", tokens["rls.admin@example.org"])
    assert len(audit) >= 1, "seed writes one login_audit row; the admin must see it"
    admins = _rows("app_admins", tokens["rls.admin@example.org"])
    assert any(a["email"] == "rls.admin@example.org" for a in admins)
