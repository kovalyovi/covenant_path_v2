"""
Verify departed-people reconciliation (hard-delete) is correct AND safe — against the live DB, in
ONE transaction that is ROLLED BACK (no test data persists). Mirrors backend/test_rls.py.

  python -m backend.test_reconcile      # after `python -m backend.apply`

Scenario: a throwaway stake with Ward A (scraped OK) and Ward B (FAILED this run), plus an orphaned
member (their ward was removed). Asserts: present member kept, absent member in a clean unit
removed, failed-unit member preserved, orphan removed, and the gates (empty report / empty keep-set)
no-op so a bad run never deletes anyone.
"""

from __future__ import annotations

import sys

from backend import db


class _NoCommit:
    """Wrap the connection so db.* helpers' internal commit() is a no-op — keeps every write inside
    this test's single transaction, so the final rollback wipes it all (nothing hits real data)."""

    def __init__(self, conn):
        self._c = conn

    def cursor(self, *a, **k):
        return self._c.cursor(*a, **k)

    def commit(self):
        pass


def _count(cur, puid: str) -> int:
    cur.execute("select count(*) from members where person_uuid = %s", (puid,))
    return cur.fetchone()[0]


def run() -> int:
    conn = db.connect()
    conn.autocommit = False
    cur = conn.cursor()
    proxy = _NoCommit(conn)
    try:
        cur.execute("insert into stakes(unit_number,name) values (999998,'Reconcile Test') returning id")
        stake_id = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888011,'Ward A') returning id",
                    (stake_id,))
        unit_a = cur.fetchone()[0]
        cur.execute("insert into units(stake_id,unit_number,name) values (%s,888012,'Ward B') returning id",
                    (stake_id,))
        unit_b = cur.fetchone()[0]

        def add(puid: str, unit_id):
            cur.execute("insert into members(stake_id,unit_id,person_uuid,name) values (%s,%s,%s,%s)",
                        (stake_id, unit_id, puid, puid))

        add("rec-a1", unit_a)       # present this run → kept
        add("rec-a2", unit_a)       # absent, clean unit → departed
        add("rec-b1", unit_b)       # Ward B FAILED this run → preserved
        add("rec-orphan", None)     # ward removed (unit_id NULL) → departed

        # This run: Ward A scraped OK (present = a1; a2 departed). Ward B FAILED (excluded from keep).
        removed = db.reconcile_members(proxy, stake_id, ["rec-a1"], [unit_a], include_orphans=True)

        assert _count(cur, "rec-a1") == 1, "present member must be kept"
        assert _count(cur, "rec-a2") == 0, "absent member in a clean unit must be removed"
        assert _count(cur, "rec-b1") == 1, "member of a FAILED unit must be preserved"
        assert _count(cur, "rec-orphan") == 0, "orphan (removed ward) must be removed with include_orphans"
        assert removed == 2, f"expected 2 removed (a2 + orphan), got {removed}"

        # Safety gates: an empty report or empty keep-set must delete NOTHING.
        add("rec-a2", unit_a)
        assert db.reconcile_members(proxy, stake_id, [], [unit_a], include_orphans=True) == 0, \
            "empty present must no-op"
        assert db.reconcile_members(proxy, stake_id, ["rec-a1"], [], include_orphans=True) == 0, \
            "empty keep-set must no-op"
        assert _count(cur, "rec-a2") == 1, "no-op gates must not delete anything"

        # only_unit semantics (include_orphans=False): a stake-wide orphan must SURVIVE a targeted
        # single-ward refetch (re-add one to prove it; only the refetched unit's absentee goes).
        add("rec-orphan2", None)
        removed_targeted = db.reconcile_members(proxy, stake_id, ["rec-a1"], [unit_a], include_orphans=False)
        assert _count(cur, "rec-orphan2") == 1, "orphan must survive when include_orphans=False"
        assert _count(cur, "rec-a2") == 0, "absent member in the refetched unit is still removed"
        assert removed_targeted == 1, f"only a2 should go (orphan preserved), got {removed_targeted}"

        print("[+] test_reconcile: all assertions passed (rolled back, no data persisted)")
        return 0
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    sys.exit(run())
