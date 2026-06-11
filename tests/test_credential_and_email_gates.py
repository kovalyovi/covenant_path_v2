"""
Credential-staleness + invitation email gates against the REAL test Supabase project
(catalog rows F2 + F3) — these functions speak psycopg2, so the in-memory stub can't host them.

F2: backend.credentials.claim_stale_notification — exactly ONE alert per failure streak, even
under concurrent claims (two parallel daily-sync style connections), re-armed by mark_succeeded.

F3: backend.mailer.send_pending_invitations — emailed-once, revoked rows skipped, the daily cap,
and a failed send leaving the row pending for retry. send_email is recorded, never real.

Env-gated like tests/test_rls_matrix.py: skips cleanly without CP_TEST_SUPABASE_DB_URL.
All rows are TEMPORARY (unit 999901 + gate-test-% emails) and removed in finally blocks; the
seeded Testvale fixtures are never touched (pre-existing pending invitations are parked as
emailed=true for the cap test and restored afterwards).

Run: python -m pytest tests/test_credential_and_email_gates.py -q
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

DB_URL = os.environ.get("CP_TEST_SUPABASE_DB_URL") or ""
PROD_DB = os.environ.get("SUPABASE_DB_URL") or ""

pytestmark = pytest.mark.skipif(
    bool(not DB_URL or (PROD_DB and DB_URL == PROD_DB)),
    reason="Phase-B lane disabled: set CP_TEST_SUPABASE_DB_URL to the dedicated TEST project "
           "(refused when it equals SUPABASE_DB_URL).",
)

TEMP_UNIT = 999901  # outside the seeded fixtures (999001/999101/999102)


def _connect():
    import psycopg2
    return psycopg2.connect(DB_URL)


@pytest.fixture()
def temp_stake():
    """A throwaway stake + credential row; deleted afterwards regardless of outcome."""
    conn = _connect()
    stake_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into stakes (unit_number, name) values (%s, %s) "
                "on conflict (unit_number) do update set name = excluded.name returning id",
                (TEMP_UNIT, "Gate-Test Stake (temporary)"))
            stake_id = cur.fetchone()[0]
            cur.execute("delete from stake_credentials where stake_id=%s", (stake_id,))
            cur.execute(
                "insert into stake_credentials (stake_id, principal_name, principal_email, "
                "credential_enc, revoked) values (%s, %s, %s, %s, false)",
                (stake_id, "Gate Tester", "gate-test-provider@example.org", "enc-test-blob"))
        conn.commit()
        yield conn, str(stake_id)
    finally:
        try:
            conn.rollback()  # a failed test leaves the tx aborted — reset before cleanup
            with conn.cursor() as cur:
                cur.execute("delete from invitations where stake_id=%s", (stake_id,))
                cur.execute("delete from stake_credentials where stake_id=%s", (stake_id,))
                cur.execute("delete from stakes where id=%s", (stake_id,))
            conn.commit()
        finally:
            conn.close()


# --- F2: one stale alert per failure streak --------------------------------------------------


def test_stale_claim_fires_once_then_rearms_on_success(temp_stake):
    from backend import credentials
    conn, stake_id = temp_stake
    credentials.mark_failed(conn, stake_id, "SSO did not complete")
    assert credentials.claim_stale_notification(conn, stake_id) is True
    # The streak continues — every later failing run must NOT alert again.
    credentials.mark_failed(conn, stake_id, "still failing")
    assert credentials.claim_stale_notification(conn, stake_id) is False
    # A healthy sync clears the edge; the NEXT failure alerts exactly once again.
    credentials.mark_succeeded(conn, stake_id)
    credentials.mark_failed(conn, stake_id, "failing again")
    assert credentials.claim_stale_notification(conn, stake_id) is True
    assert credentials.claim_stale_notification(conn, stake_id) is False


def test_stale_claim_is_atomic_under_concurrency(temp_stake):
    from backend import credentials
    conn, stake_id = temp_stake
    credentials.mark_failed(conn, stake_id, "outage")

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def claim():
        c = _connect()
        try:
            barrier.wait(timeout=10)  # maximize overlap
            results.append(credentials.claim_stale_notification(c, stake_id))
        finally:
            c.close()

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [False, True], f"exactly one claim must win, got {results}"


# --- F3: invitation send gates ----------------------------------------------------------------


@pytest.fixture()
def recorded_mailer(monkeypatch):
    """Record sends instead of emailing; the test controls the per-call outcome."""
    from backend import mailer
    sent: list[str] = []
    holder = {"ok": True}

    def fake_send(to, subject, html, sender=None):
        sent.append(to)
        return holder["ok"]

    monkeypatch.setattr(mailer, "send_email", fake_send)
    return sent, holder


@pytest.fixture()
def parked_foreign_invites():
    """Park any PRE-EXISTING pending invitations (e.g. the seeded power-user one) as emailed=true
    so cap/count assertions see only this test's rows; restore the originals afterwards."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select id from invitations where emailed=false")
            parked = [str(r[0]) for r in cur.fetchall()]
            if parked:
                cur.execute("update invitations set emailed=true where id = any(%s::uuid[])",
                            (parked,))
        conn.commit()
        yield
    finally:
        try:
            conn.rollback()  # reset any aborted tx before restoring
            with conn.cursor() as cur:
                if parked:
                    cur.execute("update invitations set emailed=false where id = any(%s::uuid[])",
                                (parked,))
            conn.commit()
        finally:
            conn.close()


def _insert_invite(conn, stake_id: str, email: str, status: str = "pending") -> str:
    inv_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "insert into invitations (id, stake_id, unit_id, role, invited_email, "
            "invited_by_email, status, emailed) values (%s, %s, null, %s, %s, %s, %s, false)",
            (inv_id, stake_id, "stake_leader", email, "gate-test-inviter@example.org", status))
    conn.commit()
    return inv_id


def test_invitations_send_once_and_skip_revoked(temp_stake, recorded_mailer, parked_foreign_invites):
    from backend import mailer
    conn, stake_id = temp_stake
    sent, _holder = recorded_mailer
    _insert_invite(conn, stake_id, "gate-test-a@example.org")
    _insert_invite(conn, stake_id, "gate-test-b@example.org")
    _insert_invite(conn, stake_id, "gate-test-revoked@example.org", status="revoked")

    assert mailer.send_pending_invitations(conn) == 2
    assert sorted(sent) == ["gate-test-a@example.org", "gate-test-b@example.org"]
    # Emailed-once: a second run sends NOTHING (rows flipped to emailed=true/active).
    sent.clear()
    assert mailer.send_pending_invitations(conn) == 0
    assert sent == []


def test_invitation_cap_is_respected(temp_stake, recorded_mailer, parked_foreign_invites):
    from backend import mailer
    conn, stake_id = temp_stake
    sent, _holder = recorded_mailer
    for i in range(4):
        _insert_invite(conn, stake_id, f"gate-test-cap{i}@example.org")
    assert mailer.send_pending_invitations(conn, cap=2) == 2
    assert len(sent) == 2
    # The remainder goes out on the next run — nothing is lost, nothing duplicated.
    sent.clear()
    assert mailer.send_pending_invitations(conn, cap=10) == 2
    assert len(sent) == 2


def test_failed_send_stays_pending_for_retry(temp_stake, recorded_mailer, parked_foreign_invites):
    from backend import mailer
    conn, stake_id = temp_stake
    sent, holder = recorded_mailer
    _insert_invite(conn, stake_id, "gate-test-retry@example.org")

    holder["ok"] = False  # transport down
    assert mailer.send_pending_invitations(conn) == 0
    with conn.cursor() as cur:
        cur.execute("select emailed from invitations where invited_email=%s",
                    ("gate-test-retry@example.org",))
        assert cur.fetchone()[0] is False  # still pending — will retry next run

    holder["ok"] = True  # transport back
    assert mailer.send_pending_invitations(conn) == 1
    assert sent.count("gate-test-retry@example.org") == 2  # one failed try + one success


# --- B8: pre-emptive aging-credential alert (claim_age_notification, migration 0047) ----------


def _age_credential(conn, stake_id: str, days: int, **cols) -> None:
    """Backdate the credential's updated_at (and set extra columns) to simulate aging."""
    sets = ["updated_at = now() - make_interval(days => %s)"]
    args: list = [days]
    for col, val in cols.items():
        sets.append(f"{col} = %s")
        args.append(val)
    args.append(stake_id)
    with conn.cursor() as cur:
        cur.execute(f"update stake_credentials set {', '.join(sets)} where stake_id = %s", args)
    conn.commit()


def test_age_alert_fires_once_per_credential_generation(temp_stake):
    from backend import credentials
    conn, stake_id = temp_stake

    # Fresh credential -> too young, no nudge.
    assert credentials.claim_age_notification(conn, stake_id, 21) is False

    # 30 days old, no refresh token -> exactly ONE nudge for this generation.
    _age_credential(conn, stake_id, 30, has_refresh_token=False)
    assert credentials.claim_age_notification(conn, stake_id, 21) is True
    assert credentials.claim_age_notification(conn, stake_id, 21) is False, (
        "the aging nudge must fire once per stored session, not every sync")

    # A RE-ENROLL bumps updated_at -> young again now, and once it ages the alert RE-ARMS
    # (age_notified_at < updated_at) without any explicit reset.
    with conn.cursor() as cur:
        cur.execute("update stake_credentials set updated_at = now() where stake_id = %s",
                    (stake_id,))
    conn.commit()
    assert credentials.claim_age_notification(conn, stake_id, 21) is False  # fresh session
    # Generation 2 ages in turn: alerted 60d ago (gen 1), re-enrolled 30d ago, old again NOW —
    # age_notified_at < updated_at re-arms the nudge with no explicit reset anywhere.
    with conn.cursor() as cur:
        cur.execute("update stake_credentials set "
                    "updated_at = now() - make_interval(days => 30), "
                    "age_notified_at = now() - make_interval(days => 60) where stake_id = %s",
                    (stake_id,))
    conn.commit()
    assert credentials.claim_age_notification(conn, stake_id, 21) is True
    assert credentials.claim_age_notification(conn, stake_id, 21) is False


def test_age_alert_skips_self_renewing_and_revoked_credentials(temp_stake):
    from backend import credentials
    conn, stake_id = temp_stake

    # Old but SELF-RENEWING (has a refresh token) -> never nudged.
    _age_credential(conn, stake_id, 40, has_refresh_token=True)
    assert credentials.claim_age_notification(conn, stake_id, 21) is False

    # Old and REVOKED -> the revoked banner owns that story; no aging nudge on top.
    _age_credential(conn, stake_id, 40, has_refresh_token=False, revoked=True)
    assert credentials.claim_age_notification(conn, stake_id, 21) is False
