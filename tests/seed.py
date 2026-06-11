"""
PHASE B seeding — create the fictional persona fixtures in a REAL **test** Supabase project
so tests/test_rls_matrix.py can assert the role x table visibility matrix against actual
Postgres RLS (the in-memory stub can't test policies).

HARD REQUIREMENTS (refuses to run otherwise):
  CP_TEST_SUPABASE_URL                  the TEST project's URL
  CP_TEST_SUPABASE_SERVICE_ROLE_KEY     its service-role key
  CP_TEST_SUPABASE_URL must differ from SUPABASE_URL — this script must NEVER seed prod.

The test project must have the repo migrations applied first:
  SUPABASE_DB_URL=<test project db url> python -m backend.apply

Everything seeded is FICTIONAL (public repo): Testvale North Stake 999001, wards
999101/999102, example.org accounts. Idempotent — safe to re-run.

Run:  python -m tests.seed
"""

from __future__ import annotations

import os
import sys

import requests

STAKE_UNIT = 999001
WARD1_UNIT = 999101
WARD2_UNIT = 999102
STAKE_NAME = "Testvale North Stake"
WARD1_NAME = "Testvale 1st Ward"
WARD2_NAME = "Testvale 2nd Ward"

# persona email -> (password, description)
RLS_USERS = {
    "rls.president@example.org": ("pw-rls-president-1!", "stake_leader (whole stake)"),
    "rls.bishop@example.org":    ("pw-rls-bishop-1!", "ward_leader (ward 999101 only)"),
    "rls.norole@example.org":    ("pw-rls-norole-1!", "valid login, no roles"),
    "rls.power@example.org":     ("pw-rls-power-1!", "power-user clone of the president"),
    "rls.admin@example.org":     ("pw-rls-admin-1!", "app_admin (ops console)"),
}

# (person_uuid suffix, fictional name, ward unit) — 3 in ward 1, 2 in ward 2
MEMBERS = [
    ("e2e-person-0001", "Avery Example", WARD1_UNIT),
    ("e2e-person-0002", "Finley Mocksen", WARD1_UNIT),
    ("e2e-person-0003", "Harper Testworth", WARD1_UNIT),
    ("e2e-person-0004", "Jordan Fakely", WARD2_UNIT),
    ("e2e-person-0005", "Kit Specimen", WARD2_UNIT),
]


class SeedError(SystemExit):
    pass


def _env() -> tuple[str, str]:
    url = (os.environ.get("CP_TEST_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("CP_TEST_SUPABASE_SERVICE_ROLE_KEY") or ""
    if not url or not key:
        raise SeedError(
            "REFUSING to run: set CP_TEST_SUPABASE_URL and CP_TEST_SUPABASE_SERVICE_ROLE_KEY "
            "(a dedicated TEST Supabase project — never production).")
    prod = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    if prod and url == prod:
        raise SeedError(
            "REFUSING to run: CP_TEST_SUPABASE_URL equals SUPABASE_URL — this script must "
            "never seed the production project.")
    return url, key


def _sb(key: str, **extra) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json", **extra}


def _check(r: requests.Response, what: str) -> requests.Response:
    if r.status_code >= 300:
        raise SeedError(f"{what} failed ({r.status_code}): {r.text[:300]}")
    return r


def _ensure_auth_user(url: str, key: str, email: str, password: str) -> None:
    """Create the auth user with a known password (idempotent: update on conflict)."""
    r = requests.post(f"{url}/auth/v1/admin/users", headers=_sb(key),
                      json={"email": email, "password": password, "email_confirm": True},
                      timeout=30)
    if r.status_code in (200, 201):
        return
    if "already" not in r.text.lower() and r.status_code != 422:
        raise SeedError(f"create auth user {email} failed ({r.status_code}): {r.text[:200]}")
    # exists — find the id and force the known password so the password grant works
    lst = _check(requests.get(f"{url}/auth/v1/admin/users",
                              headers=_sb(key), params={"page": "1", "per_page": "200"},
                              timeout=30), "list auth users")
    users = lst.json().get("users", lst.json() if isinstance(lst.json(), list) else [])
    uid = next((u.get("id") for u in users
                if (u.get("email") or "").lower() == email.lower()), None)
    if not uid:
        raise SeedError(f"auth user {email} exists but was not found via admin list")
    _check(requests.put(f"{url}/auth/v1/admin/users/{uid}", headers=_sb(key),
                        json={"password": password, "email_confirm": True}, timeout=30),
           f"set password for {email}")


def _upsert(url: str, key: str, table: str, rows: list[dict], on_conflict: str) -> list[dict]:
    r = _check(requests.post(
        f"{url}/rest/v1/{table}",
        headers=_sb(key, Prefer="resolution=merge-duplicates,return=representation"),
        params={"on_conflict": on_conflict}, json=rows, timeout=30), f"upsert {table}")
    return r.json()


def _get(url: str, key: str, table: str, params: dict) -> list[dict]:
    r = _check(requests.get(f"{url}/rest/v1/{table}", headers=_sb(key), params=params,
                            timeout=30), f"select {table}")
    return r.json()


def _sign_in(url: str, key: str, email: str, password: str) -> str:
    r = _check(requests.post(f"{url}/auth/v1/token", params={"grant_type": "password"},
                             headers=_sb(key), json={"email": email, "password": password},
                             timeout=30), f"password grant for {email}")
    return r.json()["access_token"]


def main() -> int:
    url, key = _env()
    print(f"seeding TEST project: {url}")

    # 1. auth users with known passwords
    for email, (password, what) in RLS_USERS.items():
        _ensure_auth_user(url, key, email, password)
        print(f"  auth user ok: {email}  ({what})")

    # 2. stake + units
    stake = _upsert(url, key, "stakes",
                    [{"unit_number": STAKE_UNIT, "name": STAKE_NAME}], "unit_number")[0]
    stake_id = stake["id"]
    units = _upsert(url, key, "units", [
        {"stake_id": stake_id, "unit_number": WARD1_UNIT, "name": WARD1_NAME,
         "unit_type": "WARD"},
        {"stake_id": stake_id, "unit_number": WARD2_UNIT, "name": WARD2_NAME,
         "unit_type": "WARD"},
    ], "unit_number")
    unit_by_number = {u["unit_number"]: u["id"] for u in units}
    print(f"  stake {STAKE_UNIT} + wards {sorted(unit_by_number)} ok")

    # 3. members (fictional people)
    member_rows = []
    for person_uuid, name, ward in MEMBERS:
        member_rows.append({
            "stake_id": stake_id, "unit_id": unit_by_number[ward], "person_uuid": person_uuid,
            "name": name, "unit_name": WARD1_NAME if ward == WARD1_UNIT else WARD2_NAME,
            "baptism_date": "1 Jun 2026", "sex": "F",
        })
    _upsert(url, key, "members", member_rows, "stake_id,person_uuid")
    print(f"  members seeded: {len(member_rows)} ({sum(1 for m in MEMBERS if m[2] == WARD1_UNIT)}"
          f" in ward 1, {sum(1 for m in MEMBERS if m[2] == WARD2_UNIT)} in ward 2)")

    # 4. user_roles — delete this suite's rows then insert (the uniqueness key is an
    #    expression index PostgREST's on_conflict can't target)
    emails = [e.lower() for e in RLS_USERS]
    _check(requests.delete(f"{url}/rest/v1/user_roles", headers=_sb(key),
                           params={"email": f"in.({','.join(emails)})"}, timeout=30),
           "clear previous user_roles")
    _check(requests.post(f"{url}/rest/v1/user_roles", headers=_sb(key, Prefer="return=minimal"),
                         json=[
                             {"stake_id": stake_id, "unit_id": None, "role": "stake_leader",
                              "email": "rls.president@example.org", "source": "invitation"},
                             {"stake_id": stake_id, "unit_id": unit_by_number[WARD1_UNIT],
                              "role": "ward_leader", "email": "rls.bishop@example.org",
                              "source": "invitation"},
                         ], timeout=30), "insert user_roles")
    print("  user_roles: president=stake_leader, bishop=ward_leader(999101)")

    # 5. power user — exercise the REAL clone RPC with the president's session
    president_jwt = _sign_in(url, key, "rls.president@example.org",
                             RLS_USERS["rls.president@example.org"][0])
    _check(requests.post(f"{url}/rest/v1/rpc/invite_power_user",
                         headers={"apikey": key, "Authorization": f"Bearer {president_jwt}",
                                  "Content-Type": "application/json"},
                         json={"p_email": "rls.power@example.org"}, timeout=30),
           "invite_power_user RPC")
    print("  power user cloned from president via invite_power_user")

    # 6. app admin + one login_audit row (so the admin-visibility assertion has data)
    _upsert(url, key, "app_admins",
            [{"email": "rls.admin@example.org", "invited_by_email": "seed-script"}], "email")
    _check(requests.post(f"{url}/rest/v1/login_audit", headers=_sb(key, Prefer="return=minimal"),
                         json={"email": "rls.norole@example.org", "outcome": "allowed",
                               "stake_unit": STAKE_UNIT, "stake_name": STAKE_NAME,
                               "request_id": "seed", "phase": "seed"}, timeout=30),
           "insert login_audit")
    print("  app_admins + login_audit seeded")

    print("done. run the matrix: python -m pytest tests/test_rls_matrix.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
