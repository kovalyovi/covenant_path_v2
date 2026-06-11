"""
Catalog rows B6 + D7 + G2 against the real broker:

B6  deferred eval — a slow access scrape must NOT hold the login hostage: the response answers
    within the eval budget carrying enroll {"deferred": true}, and the background eval still
    finishes (audit row lands, offers become available via enrollment-status).
D7  /report RLS scoping — a stake-wide leader reports the whole stake, a ward leader ONLY their
    unit, a no-role user gets the empty "none" scope (never someone else's data).
G2  offboarding — admin remove-stake erases credential + members + roles + diagnostics + the
    stake row (idempotent), gated to admins; the provider WIPE tier deletes members only and
    resets freshness while roles + credential survive.
"""

from __future__ import annotations

import time

import pytest
import requests

from tests.e2e.seed_helpers import (
    PRESIDENT, STAKE_ID, credential_row, role_row, stake_row,
)

WARD1_ID = "b0000000-0000-4000-8000-000000000001"
WARD2_ID = "b0000000-0000-4000-8000-000000000002"


def _member(n: int, unit_id: str, unit_name: str, **over) -> dict:
    row = {
        "id": f"c0000000-0000-4000-8000-00000000000{n}",
        "stake_id": STAKE_ID, "unit_id": unit_id, "unit_name": unit_name,
        "person_uuid": f"e2e-person-000{n}", "name": f"Member Example{n}",
        "kind": "new_member", "sex": "F", "birth_date": "1990-01-15",
        "baptism_date": "2026-01-10", "friends": "No", "calling": None,
        "ministering_brothers_sisters": None, "ministering_assignment": None,
        "aaronic_priesthood": None, "melchizedek_priesthood": None,
    }
    row.update(over)
    return row


def _seed_scoped_stake(stack) -> None:
    """Testvale with 3 ward-1 + 2 ward-2 members, a stake-wide president and a ward-1 leader."""
    stack.seed(
        stakes=[stake_row()],
        units=[{"id": WARD1_ID, "stake_id": STAKE_ID, "unit_number": 999101,
                "name": "Testvale 1st Ward"},
               {"id": WARD2_ID, "stake_id": STAKE_ID, "unit_number": 999102,
                "name": "Testvale 2nd Ward"}],
        members=[_member(1, WARD1_ID, "Testvale 1st Ward"),
                 _member(2, WARD1_ID, "Testvale 1st Ward"),
                 _member(3, WARD1_ID, "Testvale 1st Ward"),
                 _member(4, WARD2_ID, "Testvale 2nd Ward"),
                 _member(5, WARD2_ID, "Testvale 2nd Ward")],
        user_roles=[role_row("rls.president@example.org"),
                    role_row("rls.bishop@example.org", unit_id=WARD1_ID, role="ward_leader")],
    )


# --- B6: deferred eval -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def short_eval_broker(stack):
    """A SECOND real broker on the same mocks/stub with a 1s eval budget, so a slow access
    scrape defers instead of finishing inside the generous default-harness budget."""
    import os
    import subprocess
    import sys

    from cryptography.fernet import Fernet

    from tests.e2e.conftest import REPO, _STRIP_ENV, _free_port, _wait_http

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    for key in _STRIP_ENV:
        env.pop(key, None)
    env.update({
        "CP_TEST_MODE": "1",
        "CP_TEST_LCR_BASE": stack.lcr_base,
        "CP_TEST_IDENTITY_BASE": stack.identity_base,
        "SUPABASE_URL": stack.stub_base,
        "SUPABASE_SERVICE_ROLE_KEY": "test-key",
        "SUPABASE_ANON_KEY": "test-anon",
        "LOGIN_EVAL_BUDGET_SECONDS": "1",   # the point of this broker
        "LOGIN_GATE_BUDGET_SECONDS": "20",
        "CP_TOKEN_KEY": Fernet.generate_key().decode("ascii"),
        "PYTHONUNBUFFERED": "1",
    })
    log_path = REPO / "tools" / "output" / "e2e_broker_short_budget.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 — closed in teardown
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.auth_broker.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        cwd=str(REPO), env=env, stdout=log_file, stderr=subprocess.STDOUT)
    try:
        _wait_http(f"{base}/health", timeout_s=90, proc=proc, log_path=log_path)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


def test_slow_access_scrape_defers_the_eval_but_still_finishes(stack, short_eval_broker):
    """B6: with the access scrape sleeping past the 1s budget, the login response carries
    enroll {"deferred": true} (session still minted, user not held hostage), and the
    BACKGROUND eval completes anyway — its audit row lands with the full-eval phase."""
    stack.seed(stakes=[stake_row()])  # no credential → the eval takes the full path
    stack.scenario("slow_access", sleep_seconds=4)

    r = requests.post(f"{short_eval_broker}/auth/password",
                      json={"username": PRESIDENT.username, "password": PRESIDENT.password,
                            "enroll": False},
                      timeout=120)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["status"] == "ok" and body["session"].get("otp")  # login itself unharmed
    assert body.get("enroll") == {"deferred": True}, body.get("enroll")

    # The background thread keeps going past the budget: the full-eval audit row lands.
    deadline = time.monotonic() + 30
    full_rows: list = []
    while time.monotonic() < deadline and not full_rows:
        full_rows = [a for a in stack.audit_rows(email=PRESIDENT.email)
                     if a.get("phase") == "full" and a.get("outcome") == "allowed"]
        time.sleep(0.5)
    assert full_rows, "background eval never audited after deferring"


# --- D7: /report scoping -----------------------------------------------------------------------


def test_report_is_scoped_to_the_callers_roles(stack):
    _seed_scoped_stake(stack)

    def report(email: str) -> dict:
        token = stack.user_token(email)
        r = requests.get(f"{stack.broker_base}/report",
                         headers={"Authorization": f"Bearer {token}"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        return r.json()

    stake_wide = report("rls.president@example.org")
    assert stake_wide["scope"] == "stake" and stake_wide["total"] == 5

    ward_only = report("rls.bishop@example.org")
    assert ward_only["scope"] == "units" and ward_only["total"] == 3
    ward_names = {o["name"] for o in ward_only["outstanding"]}
    assert ward_names and all("Example4" not in n and "Example5" not in n for n in ward_names), (
        "ward-2 members leaked into the ward-1 leader's report")

    none = report("rls.norole@example.org")
    assert none["scope"] == "none" and none["total"] == 0 and none["outstanding"] == []


# --- G2: offboarding tiers ----------------------------------------------------------------------


def _seed_offboard_stake(stack) -> None:
    _seed_scoped_stake(stack)
    stack.seed(
        stake_credentials=[credential_row()],
        sync_diagnostics=[{"id": "d0000000-0000-4000-8000-000000000001",
                           "stake_id": STAKE_ID, "run_kind": "sync"}],
        app_admins=[{"email": "rls.admin@example.org", "invited_by": None}],
    )


def test_admin_remove_stake_erases_everything_and_is_admin_gated(stack):
    _seed_offboard_stake(stack)
    admin_token = stack.user_token("rls.admin@example.org")
    user_token = stack.user_token("rls.president@example.org")

    # Not an admin → 403, nothing deleted.
    r = requests.post(f"{stack.broker_base}/admin/stakes/{STAKE_ID}/remove",
                      headers={"Authorization": f"Bearer {user_token}"}, timeout=30)
    assert r.status_code == 403
    assert len(stack.stub_rows("members")) == 5

    r = requests.post(f"{stack.broker_base}/admin/stakes/{STAKE_ID}/remove",
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200 and r.json()["status"] == "removed"
    for table in ("stake_credentials", "members", "user_roles", "sync_diagnostics", "stakes"):
        assert stack.stub_rows(table) == [], f"{table} not erased by remove_stake"

    # Idempotent like the SQL function: removing an already-gone stake is not an error.
    r = requests.post(f"{stack.broker_base}/admin/stakes/{STAKE_ID}/remove",
                      headers={"Authorization": f"Bearer {admin_token}"}, timeout=30)
    assert r.status_code == 200


def test_provider_wipe_keeps_roles_and_credential(stack):
    """The lighter tier: wipe deletes MEMBER data + resets freshness; the stake shell, roles and
    the credential survive so the next sync repopulates."""
    _seed_offboard_stake(stack)
    provider_token = stack.user_token(PRESIDENT.email)

    r = requests.post(f"{stack.broker_base}/auth/wipe-data",
                      json={"stake_id": STAKE_ID},
                      headers={"Authorization": f"Bearer {provider_token}"}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    assert stack.stub_rows("members") == []
    assert len(stack.stub_rows("user_roles")) == 2, "wipe must keep roles"
    creds = stack.stub_rows("stake_credentials")
    assert len(creds) == 1 and creds[0]["revoked"] is False, "wipe must keep the credential"
    stake = stack.stub_rows("stakes")[0]
    assert stake["sync_state"] == "idle" and stake["last_synced_at"] is None
