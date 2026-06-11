"""
Digest / weekly-reminder / handoff-ping NON-SPAM gates against the REAL test Supabase project
(catalog row F4) — these functions speak psycopg2 + SQL aggregates, so the in-memory stub
can't host them.

What must hold (and is asserted here):
  - send_digests: one digest per leader email per run, and NO digest at all for a leader whose
    scope is empty (an empty digest is spam).
  - send_handoff_pings: a convert crossing 6/12 months fires EXACTLY once per (person, phase) —
    the transition is recorded only when actually emailed, so an out-of-scope leader never
    burns the once-only send; owner-only preview gate respected.
  - send_weekly_reminders: owner-only preview gate respected; sends when (and only when) the
    owner's scope has outstanding eligible steps or fresh completions.

Env-gated like the RLS matrix (CP_TEST_SUPABASE_DB_URL; refuses prod). All rows are TEMPORARY
(stake 999902, digest-test-% emails) and removed in finally blocks — the seeded Testvale
fixtures (which other suites count exactly) are never touched. mailer.send_email is recorded,
never real.

Run: python -m pytest tests/test_digest_and_handoff_gates.py -q
"""

from __future__ import annotations

import os
from datetime import date

import pytest

DB_URL = os.environ.get("CP_TEST_SUPABASE_DB_URL") or ""
PROD_DB = os.environ.get("SUPABASE_DB_URL") or ""

pytestmark = pytest.mark.skipif(
    bool(not DB_URL or (PROD_DB and DB_URL == PROD_DB)),
    reason="Phase-B lane disabled: set CP_TEST_SUPABASE_DB_URL to the dedicated TEST project "
           "(refused when it equals SUPABASE_DB_URL).",
)

TEMP_UNIT = 999902
STAKE_LEADER = "digest-test-stake-leader@example.org"
EMPTY_WARD_LEADER = "digest-test-ward-leader@example.org"  # scoped to the EMPTY unit


def _months_ago(months: int) -> str:
    today = date.today()
    y, m = today.year, today.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}-10"


def _connect():
    import psycopg2
    return psycopg2.connect(DB_URL)


@pytest.fixture()
def temp_scope():
    """A throwaway stake: one populated ward (a 7-months-ago convert with missing steps + a
    brand-new convert) and one EMPTY ward; a stake-wide leader and an empty-ward leader."""
    conn = _connect()
    stake_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into stakes (unit_number, name) values (%s, %s) "
                "on conflict (unit_number) do update set name = excluded.name returning id",
                (TEMP_UNIT, "Digest-Test Stake (temporary)"))
            stake_id = str(cur.fetchone()[0])
            cur.execute(
                "insert into units (stake_id, unit_number, name) values (%s, %s, %s) "
                "on conflict (unit_number) do update set name = excluded.name returning id",
                (stake_id, 999921, "Digest-Test 1st Ward"))
            ward1 = str(cur.fetchone()[0])
            cur.execute(
                "insert into units (stake_id, unit_number, name) values (%s, %s, %s) "
                "on conflict (unit_number) do update set name = excluded.name returning id",
                (stake_id, 999922, "Digest-Test 2nd Ward (empty)"))
            ward2 = str(cur.fetchone()[0])
            # 7-months-post-baptism adult convert, several eligible steps missing -> crosses the
            # 6mo handoff phase AND shows up in weekly reminders.
            cur.execute(
                "insert into members (stake_id, unit_id, person_uuid, name, unit_name, kind, "
                "sex, birth_date, baptism_date, friends, calling) "
                "values (%s, %s, %s, %s, %s, 'new_member', 'F', '1990-03-15', %s, 'No', 'No')",
                (stake_id, ward1, "digest-test-person-1", "Avery Digestcase",
                 "Digest-Test 1st Ward", _months_ago(7)))
            # Baptized THIS month -> no handoff phase yet, still counts for the digest total.
            cur.execute(
                "insert into members (stake_id, unit_id, person_uuid, name, unit_name, kind, "
                "sex, birth_date, baptism_date, friends) "
                "values (%s, %s, %s, %s, %s, 'new_member', 'M', '1995-08-20', %s, 'Yes')",
                (stake_id, ward1, "digest-test-person-2", "Kit Digestcase",
                 "Digest-Test 1st Ward", _months_ago(0)))
            cur.execute(
                "insert into user_roles (stake_id, unit_id, role, email, source) "
                "values (%s, null, 'stake_leader', %s, 'invitation'), "
                "       (%s, %s, 'ward_leader', %s, 'invitation')",
                (stake_id, STAKE_LEADER, stake_id, ward2, EMPTY_WARD_LEADER))
        conn.commit()
        yield conn, stake_id
    finally:
        try:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("delete from handoff_pings where stake_id=%s", (stake_id,))
                cur.execute("delete from reminder_snapshots where stake_id=%s", (stake_id,))
                cur.execute("delete from user_roles where stake_id=%s", (stake_id,))
                cur.execute("delete from members where stake_id=%s", (stake_id,))
                cur.execute("delete from units where stake_id=%s", (stake_id,))
                cur.execute("delete from stakes where id=%s", (stake_id,))
            conn.commit()
        finally:
            conn.close()


@pytest.fixture()
def recorded_mailer(monkeypatch):
    from backend import mailer
    sent: list[tuple[str, str]] = []  # (to, subject)

    def fake_send(to, subject, html, sender=None):
        sent.append((to, subject))
        return True

    monkeypatch.setattr(mailer, "send_email", fake_send)
    return sent


def _set_owner_gate(monkeypatch, owner_email: str) -> None:
    """The weekly/handoff owner-only preview gate (read from env at import — patch the attrs)."""
    from backend import mailer
    monkeypatch.setattr(mailer, "_REMINDER_OWNER", owner_email.lower())
    monkeypatch.setattr(mailer, "_REMINDERS_OWNER_ONLY", True)


# --- digests -----------------------------------------------------------------------------------


def test_digest_once_per_leader_and_never_for_an_empty_scope(temp_scope, recorded_mailer):
    from backend import mailer
    conn, _stake_id = temp_scope
    mailer.send_digests(conn)
    recipients = [to for to, _subject in recorded_mailer]
    # One digest per leader, period — globally no recipient appears twice in a run.
    assert len(recipients) == len(set(recipients)), f"duplicate digests in one run: {recipients}"
    assert recipients.count(STAKE_LEADER) == 1
    # The empty-ward leader gets NOTHING (an empty digest is spam, not a summary).
    assert EMPTY_WARD_LEADER not in recipients


# --- handoff pings -----------------------------------------------------------------------------


def test_handoff_fires_once_per_phase_and_only_when_in_scope(
        temp_scope, recorded_mailer, monkeypatch):
    from backend import mailer
    conn, stake_id = temp_scope

    # Out-of-scope leader (empty ward) as the gated recipient: nothing sends AND — critically —
    # the transition is NOT burned (recording happens only when actually emailed).
    _set_owner_gate(monkeypatch, EMPTY_WARD_LEADER)
    assert mailer.send_handoff_pings(conn) == 0
    with conn.cursor() as cur:
        cur.execute("select count(*) from handoff_pings where stake_id=%s", (stake_id,))
        assert cur.fetchone()[0] == 0, "an unsent handoff must not be recorded"

    # The stake-wide leader gets the 6mo crossing exactly once...
    _set_owner_gate(monkeypatch, STAKE_LEADER)
    assert mailer.send_handoff_pings(conn) == 1
    handoff_sends = [s for s in recorded_mailer if "handoff" in s[1].lower()]
    assert [to for to, _ in handoff_sends] == [STAKE_LEADER]
    with conn.cursor() as cur:
        cur.execute("select person_uuid, phase from handoff_pings where stake_id=%s", (stake_id,))
        assert cur.fetchall() == [("digest-test-person-1", "6mo")]

    # ...and never again for the same phase.
    assert mailer.send_handoff_pings(conn) == 0


# --- weekly reminders --------------------------------------------------------------------------


def test_weekly_reminders_respect_the_owner_gate_and_send_on_outstanding_steps(
        temp_scope, recorded_mailer, monkeypatch):
    from backend import mailer
    conn, _stake_id = temp_scope

    # Gated to an email with no scope here -> zero sends (the WIP preview gate).
    _set_owner_gate(monkeypatch, "someone-else@example.org")
    assert mailer.send_weekly_reminders(conn) == 0

    # Gated to the stake leader -> exactly one reminder (the 7-month convert has eligible
    # missing steps: friend, calling, ministers, family name, temple visit...).
    _set_owner_gate(monkeypatch, STAKE_LEADER)
    assert mailer.send_weekly_reminders(conn) == 1
    weekly = [to for to, subject in recorded_mailer if "next steps" in subject.lower()]
    assert weekly == [STAKE_LEADER]
