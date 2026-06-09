"""
PRODUCTION-LIKE, fully-MOCKED scenario matrix for the covenant-path access / sync / data-correctness
logic. Runs AUTONOMOUSLY — no live credentials, no network, no real Supabase, no LCR. It exercises
the REAL imported code (backend.roles, backend.db, backend.credentials, covenant_path.report) against
an in-memory DB (backend.fake_db) + fake LCR payloads.

  python -m backend.test_scenarios

Why this exists alongside the LIVE tests: test_rls / test_power_users / test_admins / test_reconcile
prove the *SQL* (RLS policies, RPCs) but need a database + secrets. This suite covers the matrix the
user asked for with NOTHING provided, and complements (does not replace) those — see docs/SCENARIOS.md
for the cell-by-cell map and which surface (offline-here vs live-there) proves each.

The matrix axes:
  1. Subject role: stake leader / ward leader / non-leader member / non-member.
  2. Access level vs the existing credential/role: same / higher / lower / none.
  3. admin vs non-admin.
  4. Data-fetch outcomes: timeout/failure vs success; per-field empty/removed/added/modified;
     modified-by-stable-ID (reconcile updates BY id, never clobbers good data with a partial fetch).
  5. Access changes: remove / add / modify — calling changed; credential expired/stale.
  6. Logging & visibility: every issue is visible to ADMIN and is PROTECTED (admin-only, never public).

Each scenario is a function returning a list of (label, got, expected) checks. The runner prints
PASS/FAIL and exits non-zero on any failure (mirrors the other backend/test_*.py modules).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

# Self-contained crypto key so credential/token round-trips never need a provided secret.
import os as _os
from cryptography.fernet import Fernet as _Fernet
_os.environ.setdefault("CP_TOKEN_KEY", _Fernet.generate_key().decode())

from backend import credentials, db, roles  # REAL logic under test
from backend import fake_db
from backend.fake_db import FakeDB
from covenant_path import report


# ============================================================================
# Fake LCR client + access matrix (the only "network" boundary, fully in-memory)
# ============================================================================

class FakeSession:
    """Stands in for LcrSession — only identity matters (fetch_access_matrix is monkeypatched)."""


class _UnitRef:
    def __init__(self, name, unit_number, type_):
        self.name = name
        self.unit_number = unit_number
        self.type = type_


class _Ctx:
    def __init__(self, unit_number, unit_name, child_units):
        self.unit_number = unit_number
        self.unit_name = unit_name
        self.child_units = child_units


class _MemberRaw:
    def __init__(self, raw):
        self.raw = raw


class FakeMatrix:
    """Mirror of lcr_client.access.AccessMatrix.feature_roles for the provisioning gate."""

    def __init__(self, by_feature):
        self._by_feature = by_feature

    def feature_roles(self, key):
        return self._by_feature.get(key, [])


class FakeLcrClient:
    """Faithful-enough LcrClient for roles.provision_roles + covenant_path.report:
      - user_context() -> stake unit + child WARD/BRANCH units
      - org_callings(unit_number) -> {"unitOrgs": [...]} positions tree (roles._ward_positions shape)
      - member_list(unit_number) -> [Member-like .raw] (for _email_by_uuid + report birth/sex)
      - progress_record / progress_details for the report path (set per test).
    """

    def __init__(self, stake_unit, stake_name, child_units, *, org_callings=None,
                 member_lists=None, progress=None, details=None):
        self.session = FakeSession()
        self._stake_unit = stake_unit
        self._stake_name = stake_name
        self._child = child_units
        self._org_callings = org_callings or {}      # unit_number -> orgs dict
        self._member_lists = member_lists or {}       # unit_number -> [raw dict]
        self._progress = progress or {}               # unit_number -> raw progress dict OR Exception
        self._details = details or {}                 # person id -> details dict OR Exception
        self.calls: dict[str, int] = {}

    def _tick(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def user_context(self):
        units = [_UnitRef(n, num, t) for (num, n, t) in self._child]
        return _Ctx(self._stake_unit, self._stake_name, units)

    def org_callings(self, unit_number):
        self._tick(f"org_callings:{unit_number}")
        v = self._org_callings.get(unit_number, {"unitOrgs": []})
        if isinstance(v, Exception):
            raise v
        return v

    def member_list(self, unit_number):
        self._tick(f"member_list:{unit_number}")
        v = self._member_lists.get(unit_number, [])
        if isinstance(v, Exception):
            raise v
        return [_MemberRaw(m) for m in v]

    def progress_record(self, unit_number):
        self._tick(f"progress_record:{unit_number}")
        v = self._progress.get(unit_number)
        if isinstance(v, Exception):
            raise v

        class _PR:
            raw = v if isinstance(v, dict) else {}
        if v is None:
            raise RuntimeError("no progress record configured")
        return _PR()

    def progress_details(self, person_id, cmis_id):
        self._tick(f"progress_details:{person_id}")
        v = self._details.get(person_id)
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise RuntimeError("no details configured")
        return v


def _position(person_uuid, name, role_id, calling, unit_name="Ward"):
    """One ACTIVE_POSITION node in the org tree (roles._ward_positions / _positions shape)."""
    return {
        "positionStatus": "ACTIVE_POSITION",
        "positionType": {"id": role_id, "name": calling},
        "person": {"uuid": person_uuid, "name": name, "currentUnitName": unit_name},
    }


def _orgs(positions):
    return {"unitOrgs": [{"positions": positions, "children": []}]}


# Role-id catalog used across scenarios. The access matrix grants member-data features to the
# data-bearing role ids; everyone else is gated out (unless on the always-allowed calling list).
RID_STAKE_PRES = 1      # always-allowed by name + in matrix
RID_BISHOP = 4          # ward data role (in matrix)
RID_EQ_PRES = 138       # ward data role (in matrix)
RID_RS_PRES = 200       # ward data role (in matrix)
RID_PRIMARY_PIANIST = 900   # NON-data calling: not in matrix, not always-allowed
RID_STAKE_CLERK = 52    # always-allowed by name

# the matrix: which role ids reach each covenant-path data feature.
_DATA_ROLE_IDS = [RID_BISHOP, RID_EQ_PRES, RID_RS_PRES, RID_STAKE_PRES, RID_STAKE_CLERK]
DEFAULT_MATRIX = FakeMatrix({
    "menu.progress.record": list(_DATA_ROLE_IDS),
    "menu.member.list": list(_DATA_ROLE_IDS),
    "menu.view.member.profiles": list(_DATA_ROLE_IDS),
})


def _patch_matrix(monkey_target=roles, matrix=DEFAULT_MATRIX):
    """provision_roles calls the module-level fetch_access_matrix; swap it for our in-memory one."""
    monkey_target.fetch_access_matrix = lambda _session: matrix


def _provision(db_obj: FakeDB, client: FakeLcrClient, stake_id: str, unit_id_by_name: dict,
               matrix=DEFAULT_MATRIX):
    _patch_matrix(roles, matrix)
    return roles.provision_roles(db_obj, client, stake_id, unit_id_by_name)


# ============================================================================
# AXIS 1+2+5a — Subject role -> RLS scope, provisioned from callings; calling changes
# ============================================================================

def scenario_role_scope_and_visibility():
    """Stake leader sees the whole stake; ward leader only their ward; a non-leader member and a
    non-member see nothing. (RLS scope rule: migrations 0002/0004 — mirrored by fake_db; the SQL
    enforcement itself is proven LIVE by backend/test_rls.py.)"""
    d = FakeDB()
    sid = d.add_stake(999001, "Scope Stake")
    ua = d.add_unit(sid, 888101, "Ward A")
    ub = d.add_unit(sid, 888102, "Ward B")
    d.add_member(sid, ua, "m-a", name="Alice")
    d.add_member(sid, ub, "m-b", name="Bob")

    sl = "11111111-1111-1111-1111-111111111111"
    wl = "22222222-2222-2222-2222-222222222222"
    d.add_role(sid, "stake_leader", unit_id=None, lcr_person_uuid=sl, email="sl@example.org")
    d.add_role(sid, "ward_leader", unit_id=ua, lcr_person_uuid=wl, email="wl@example.org")

    sl_n = len(fake_db.members_visible_to(d, auth_id=sl))
    wl_n = len(fake_db.members_visible_to(d, auth_id=wl))
    wl_email_n = len(fake_db.members_visible_to(d, email="WL@example.org"))  # email match, case-insens
    member_n = len(fake_db.members_visible_to(d, email="rando-member@example.org"))  # non-leader member
    nonmember_n = len(fake_db.members_visible_to(d, auth_id=None, email=None))       # non-member

    return [
        ("stake_leader sees both members", sl_n, 2),
        ("ward_leader sees only their ward", wl_n, 1),
        ("ward_leader matched by verified email (case-insens)", wl_email_n, 1),
        ("non-leader member sees none", member_n, 0),
        ("non-member sees none", nonmember_n, 0),
    ]


def scenario_provision_grants_by_calling():
    """provision_roles maps a STAKE-prefixed data calling -> stake_leader (whole stake) and a WARD
    data calling -> ward_leader (that unit), and a NON-data calling (Primary Pianist) gets NOTHING.
    (roles.provision_roles + _can_see + the access matrix gate.)"""
    d = FakeDB()
    sid = d.add_stake(999002, "Provision Stake")
    ua = d.add_unit(sid, 888201, "Ward A")
    unit_id_by_name = {"Ward A": ua}

    client = FakeLcrClient(
        stake_unit=999002, stake_name="Provision Stake",
        child_units=[(888201, "Ward A", "WARD")],
        org_callings={
            999002: _orgs([_position("p-pres", "Pres Stake", RID_STAKE_PRES, "Stake President", "Provision Stake")]),
            888201: _orgs([
                _position("p-bish", "Bishop Ward", RID_BISHOP, "Bishop", "Ward A"),
                _position("p-piano", "Pianist Person", RID_PRIMARY_PIANIST, "Primary Pianist", "Ward A"),
            ]),
        },
        member_lists={888201: [{"personUuid": "p-bish", "email": "bishop@example.org"}]},
    )
    counts = _provision(d, client, sid, unit_id_by_name)

    stake_roles = d.roles_for(role="stake_leader")
    ward_roles = d.roles_for(role="ward_leader")
    piano = [r for r in d.user_roles if r["lcr_person_uuid"] == "p-piano"]
    bishop_email = [r["email"] for r in ward_roles if r["lcr_person_uuid"] == "p-bish"]

    return [
        ("stake calling -> 1 stake_leader", counts["stake_leader"], 1),
        ("ward data calling -> 1 ward_leader", counts["ward_leader"], 1),
        ("ward_leader scoped to the unit", ward_roles[0]["unit_id"] if ward_roles else None, ua),
        ("non-data calling granted nothing", len(piano), 0),
        ("email enrichment attached to role", bishop_email, ["bishop@example.org"]),
        ("stake_leader unit_id is NULL (whole stake)", stake_roles[0]["unit_id"] if stake_roles else "x", None),
    ]


def scenario_calling_changed_revoke_and_add():
    """AXIS 5a: a leader RELEASED from their calling loses access on the next provision; a NEW callee
    gains it. Calling-derived rows are keyed by person uuid and rebuilt; the released person is
    revoked (and audited). (roles.provision_roles revoke clause + _audit_access.)"""
    d = FakeDB()
    sid = d.add_stake(999003, "Turnover Stake")
    ua = d.add_unit(sid, 888301, "Ward A")
    unit_id_by_name = {"Ward A": ua}

    def client_with_bishop(uuid, name):
        return FakeLcrClient(
            stake_unit=999003, stake_name="Turnover Stake",
            child_units=[(888301, "Ward A", "WARD")],
            org_callings={
                999003: _orgs([_position("s1", "S", RID_STAKE_PRES, "Stake President", "Turnover Stake")]),
                888301: _orgs([_position(uuid, name, RID_BISHOP, "Bishop", "Ward A")]),
            },
        )

    # Run 1: old bishop holds the calling.
    _provision(d, client_with_bishop("old-bish", "Old Bishop"), sid, unit_id_by_name)
    after1 = {r["lcr_person_uuid"] for r in d.roles_for(role="ward_leader")}

    # Run 2: a NEW bishop replaced the old one (released).
    counts2 = _provision(d, client_with_bishop("new-bish", "New Bishop"), sid, unit_id_by_name)
    after2 = {r["lcr_person_uuid"] for r in d.roles_for(role="ward_leader")}

    granted_audit = [a for a in d.access_audit if a["action"] == "granted" and a["person_uuid"] == "new-bish"]
    revoked_audit = [a for a in d.access_audit if a["action"] == "revoked" and a["person_uuid"] == "old-bish"]

    return [
        ("run1: old bishop has ward access", "old-bish" in after1, True),
        ("run2: new bishop gains access", "new-bish" in after2, True),
        ("run2: released old bishop revoked", "old-bish" not in after2, True),
        ("run2 reports 1 revoked", counts2["revoked"], 1),
        ("grant audited (visible to admin)", len(granted_audit), 1),
        ("revoke audited (visible to admin)", len(revoked_audit), 1),
    ]


def scenario_revoke_gated_on_directory_fetch():
    """SAFETY: an empty/failed leadership fetch must NOT be read as 'everyone released' — the revoke
    is gated on stake_ok / ward_ok. Here org_callings returns NOTHING this run; the prior leaders
    must be PRESERVED, not wiped. (roles.provision_roles stake_ok/ward_ok gate.)"""
    d = FakeDB()
    sid = d.add_stake(999004, "Gated Stake")
    ua = d.add_unit(sid, 888401, "Ward A")
    unit_id_by_name = {"Ward A": ua}

    # Seed pre-existing calling-derived roles (from a prior healthy run).
    d.add_role(sid, "stake_leader", unit_id=None, lcr_person_uuid="s-old", calling_name="Stake President")
    d.add_role(sid, "ward_leader", unit_id=ua, lcr_person_uuid="b-old", calling_name="Bishop")

    # This run: BOTH stake org-callings and ward org-callings come back empty (transient failure).
    client = FakeLcrClient(
        stake_unit=999004, stake_name="Gated Stake",
        child_units=[(888401, "Ward A", "WARD")],
        org_callings={999004: {"unitOrgs": []}, 888401: {"unitOrgs": []}},
    )
    counts = _provision(d, client, sid, unit_id_by_name)

    survivors = {r["lcr_person_uuid"] for r in d.user_roles}
    return [
        ("empty fetch revokes nobody", counts["revoked"], 0),
        ("prior stake_leader preserved", "s-old" in survivors, True),
        ("prior ward_leader preserved", "b-old" in survivors, True),
    ]


def scenario_email_and_invitation_rows_preserved():
    """Manual / power-user (invitation) grants have a NULL lcr_person_uuid and must SURVIVE a
    provision run (which only rebuilds calling-derived rows). (roles.provision_roles revoke clause
    filters `lcr_person_uuid is not null`.)"""
    d = FakeDB()
    sid = d.add_stake(999005, "Mixed Stake")
    ua = d.add_unit(sid, 888501, "Ward A")
    unit_id_by_name = {"Ward A": ua}

    # an invited power user (email-only, source=invitation) + a calling-derived bishop to be replaced
    d.add_role(sid, "stake_leader", unit_id=None, lcr_person_uuid=None,
               email="poweruser@example.org", source="invitation")
    d.add_role(sid, "ward_leader", unit_id=ua, lcr_person_uuid="b-old", calling_name="Bishop")

    client = FakeLcrClient(
        stake_unit=999005, stake_name="Mixed Stake",
        child_units=[(888501, "Ward A", "WARD")],
        org_callings={
            999005: _orgs([_position("s1", "S", RID_STAKE_PRES, "Stake President", "Mixed Stake")]),
            888501: _orgs([_position("b-new", "New Bishop", RID_BISHOP, "Bishop", "Ward A")]),
        },
    )
    _provision(d, client, sid, unit_id_by_name)

    invited = [r for r in d.user_roles if r["email"] == "poweruser@example.org"]
    old_bish = [r for r in d.user_roles if r["lcr_person_uuid"] == "b-old"]
    return [
        ("invited power-user row preserved", len(invited), 1),
        ("invited row still stake-wide", invited[0]["unit_id"] if invited else "x", None),
        ("calling-derived old bishop revoked", len(old_bish), 0),
    ]


def scenario_always_allowed_calling_safety_net():
    """A stake stewardship calling on the always-allowed list (Stake Executive Secretary) gains data
    access EVEN IF the access matrix is incomplete (its role id is NOT in the matrix). Note: stake
    positions are filtered to STAKE-prefixed calling names first (roles._STAKE_PREFIXES), so the
    always-allowed safety net only fires for a stake-prefixed calling — which "Stake Executive
    Secretary" is. (roles._calling_always_allowed + the stake-prefix filter.)"""
    d = FakeDB()
    sid = d.add_stake(999006, "Safety Net Stake")
    unit_id_by_name = {}
    client = FakeLcrClient(
        stake_unit=999006, stake_name="Safety Net Stake",
        child_units=[],
        org_callings={999006: _orgs([
            # role id 778 is NOT in the matrix; only the always-allowed NAME path can grant it.
            _position("xs-1", "Exec Sec", 778, "Stake Executive Secretary", "Safety Net Stake"),
            # a non-data, non-always-allowed stake calling that must still be denied.
            _position("act-1", "Activities", 779, "Stake Activities Committee Member", "Safety Net Stake"),
        ])},
    )
    counts = _provision(d, client, sid, unit_id_by_name, matrix=FakeMatrix({}))
    xs = [r for r in d.roles_for(role="stake_leader") if r["lcr_person_uuid"] == "xs-1"]
    act = [r for r in d.user_roles if r["lcr_person_uuid"] == "act-1"]
    return [
        ("always-allowed stake calling granted despite empty matrix", len(xs), 1),
        ("non-allowed stake calling still denied", len(act), 0),
        ("counts reflect 1 stake_leader", counts["stake_leader"], 1),
    ]


def scenario_admin_added_calling_override():
    """AXIS (admin add access): an admin-added calling override grants data access to an otherwise
    non-data calling (Ward Mission Leader). (roles._load_overrides + _can_see override branch.)"""
    d = FakeDB()
    sid = d.add_stake(999007, "Override Stake")
    ua = d.add_unit(sid, 888701, "Ward A")
    unit_id_by_name = {"Ward A": ua}
    d.calling_overrides = [("ward mission leader", True)]  # admin added this mapping

    client = FakeLcrClient(
        stake_unit=999007, stake_name="Override Stake",
        child_units=[(888701, "Ward A", "WARD")],
        org_callings={
            999007: _orgs([_position("s1", "S", RID_STAKE_PRES, "Stake President", "Override Stake")]),
            888701: _orgs([_position("wml-1", "Mission Leader", 950, "Ward Mission Leader", "Ward A")]),
        },
    )
    _provision(d, client, sid, unit_id_by_name)
    wml = [r for r in d.roles_for(role="ward_leader") if r["lcr_person_uuid"] == "wml-1"]

    # And a NON-granting override (grants=False) must NOT grant.
    d2 = FakeDB()
    sid2 = d2.add_stake(999017, "Override2")
    ub = d2.add_unit(sid2, 888711, "Ward B")
    d2.calling_overrides = [("ward mission leader", False)]
    client2 = FakeLcrClient(
        stake_unit=999017, stake_name="Override2", child_units=[(888711, "Ward B", "WARD")],
        org_callings={
            999017: _orgs([_position("s2", "S", RID_STAKE_PRES, "Stake President", "Override2")]),
            888711: _orgs([_position("wml-2", "ML2", 950, "Ward Mission Leader", "Ward B")]),
        })
    _provision(d2, client2, sid2, {"Ward B": ub})
    wml2 = [r for r in d2.user_roles if r["lcr_person_uuid"] == "wml-2"]

    return [
        ("admin override grants ward access", len(wml), 1),
        ("grants=False override does NOT grant", len(wml2), 0),
    ]


# ============================================================================
# AXIS 4 — data reconciliation: merge-by-id, sentinel preservation, freshness
# ============================================================================

def _patch_execute_values():
    """Route db.upsert_members' execute_values through the FakeDB shim (REAL merge SQL semantics)."""
    db.psycopg2.extras.execute_values = fake_db.execute_values_shim


def scenario_upsert_merge_by_id_modified_added_removed():
    """AXIS 4: a member's NAME / UNIT changes are keyed by stable person_uuid (modify-by-id, never a
    duplicate); a NEW member is inserted; an absent member is left for reconcile (upsert never
    deletes). (db.upsert_members.)"""
    _patch_execute_values()
    d = FakeDB()
    sid = d.add_stake(999101, "Recon Stake")
    ua = d.add_unit(sid, 888901, "Ward A")
    ub = d.add_unit(sid, 888902, "Ward B")
    ubn = {888901: ua, 888902: ub}

    # Run 1: Alice in Ward A, Bob in Ward A.
    db.upsert_members(d, sid, [
        {"person_uuid": "u-alice", "name": "Alice", "unit_number": 888901, "calling": "No"},
        {"person_uuid": "u-bob", "name": "Bob", "unit_number": 888901, "calling": "No"},
    ], ubn)
    n_after1 = len(d.members)

    # Run 2: Alice RENAMED + MOVED to Ward B (same uuid); Carol ADDED; Bob absent (kept by upsert).
    db.upsert_members(d, sid, [
        {"person_uuid": "u-alice", "name": "Alice Smith", "unit_number": 888902, "calling": "No"},
        {"person_uuid": "u-carol", "name": "Carol", "unit_number": 888901, "calling": "No"},
    ], ubn)

    alice = d.member("u-alice")
    return [
        ("run1 inserted 2 members", n_after1, 2),
        ("modify-by-id: no duplicate Alice", sum(1 for m in d.members if m["person_uuid"] == "u-alice"), 1),
        ("name modified in place", alice["name"], "Alice Smith"),
        ("unit modified in place (moved A->B)", alice["unit_id"], ub),
        ("added member inserted", d.member("u-carol") is not None, True),
        ("upsert never deletes absent member (Bob kept)", d.member("u-bob") is not None, True),
        ("total members now 3", len(d.members), 3),
    ]


def scenario_sentinel_preserves_last_good():
    """AXIS 4 (failed/partial fetch): a degraded run emits sentinels for profile-gated fields; the
    merge-upsert PRESERVES the last-good value instead of clobbering it. A genuine empty (friends=0)
    is accepted; an unknown friends_count (None) keeps last-good. (db._merge_expr / upsert_members.)"""
    _patch_execute_values()
    d = FakeDB()
    sid = d.add_stake(999102, "Sentinel Stake")
    ua = d.add_unit(sid, 889001, "W")
    ubn = {889001: ua}

    # Run 1: GOOD data — real priesthood/calling/baptism + friends_count 3.
    db.upsert_members(d, sid, [{
        "person_uuid": "s1", "name": "Sam", "unit_number": 889001,
        "aaronic_priesthood": "Yes", "melchizedek_priesthood": "Yes", "calling": "Yes",
        "baptism_date": "1 Jan 2024", "temple_recommend": "Active", "friends_count": 3,
    }], ubn)

    # Run 2: DEGRADED — every gated field is a sentinel; friends_count unknown (None).
    db.upsert_members(d, sid, [{
        "person_uuid": "s1", "name": "Sam", "unit_number": 889001,
        "aaronic_priesthood": report.BLOCKED, "melchizedek_priesthood": report.NEEDS_PROFILE,
        "calling": report.NEEDS_PROFILE, "baptism_date": report.BLOCKED,
        "temple_recommend": report.NEEDS_PROFILE, "friends_count": None,
    }], ubn)
    # Snapshot scalars NOW (the member dict is a live reference that run 3 will mutate).
    sam2 = dict(d.member("s1"))

    # Run 3: a GENUINE empty (friends_count 0) IS accepted (not a sentinel/None).
    db.upsert_members(d, sid, [{
        "person_uuid": "s1", "name": "Sam", "unit_number": 889001, "friends_count": 0,
        "aaronic_priesthood": report.NEEDS_PROFILE, "calling": report.NEEDS_PROFILE,
    }], ubn)
    sam3_fc = d.member("s1")["friends_count"]

    return [
        ("priesthood preserved through sentinel", sam2["aaronic_priesthood"], "Yes"),
        ("melch preserved through sentinel", sam2["melchizedek_priesthood"], "Yes"),
        ("calling preserved through sentinel", sam2["calling"], "Yes"),
        ("baptism_date preserved through sentinel", sam2["baptism_date"], "1 Jan 2024"),
        ("temple_recommend preserved through sentinel", sam2["temple_recommend"], "Active"),
        ("friends_count preserved on unknown (None)", sam2["friends_count"], 3),
        ("genuine empty friends_count=0 accepted", sam3_fc, 0),
    ]


def scenario_field_freshness_tracking():
    """AXIS 4 (freshness): a FETCHED field stamps `f`; a SENTINEL field keeps its prior `f` while
    bumping `t` (staleness grows, value not blanked). field_staleness_summary then rolls up
    fresh/warn/error/never by AGE — a field last-fetched 10 days ago lands in 'error' (>7d), 5 days
    in 'warn' (>3d). (db._field_meta + field_staleness_summary.)

    We drive db._now_iso (the only clock _field_meta uses) so timestamps are deterministic, and the
    summary's age buckets are asserted relative to a controlled 'today' by stamping known-age `f`s."""
    _patch_execute_values()
    real_now_iso = db._now_iso
    d = FakeDB()
    sid = d.add_stake(999103, "Fresh Stake")
    ua = d.add_unit(sid, 889101, "W")
    ubn = {889101: ua}

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        db._now_iso = lambda: t0.isoformat()
        db.upsert_members(d, sid, [{
            "person_uuid": "f1", "name": "Fay", "unit_number": 889101,
            "ministering_assignment": "Yes", "baptism_date": report.NEEDS_PROFILE}], ubn)
        meta1 = dict(d.member("f1")["field_meta"])
        ma_f0 = meta1["ministering_assignment"]["f"]

        # 5 days later: ministering_assignment now a sentinel (keep prior f); baptism_date fetched.
        db._now_iso = lambda: (t0 + timedelta(days=5)).isoformat()
        db.upsert_members(d, sid, [{
            "person_uuid": "f1", "name": "Fay", "unit_number": 889101,
            "ministering_assignment": report.BLOCKED, "baptism_date": "2 Feb 2025"}], ubn)
        meta2 = dict(d.member("f1")["field_meta"])
    finally:
        db._now_iso = real_now_iso

    # Summary uses datetime.now() internally for the age math. Use a SEPARATE stake holding ONE
    # member with KNOWN-age last-fetched stamps so each bucket count is deterministic + isolated.
    now = datetime.now(timezone.utc)
    sid2 = d.add_stake(999113, "Summary Stake")
    ua2 = d.add_unit(sid2, 889111, "W2")
    d.add_member(sid2, ua2, "f2", field_meta={
        "calling": {"f": (now - timedelta(days=10)).isoformat()},          # >7d -> error
        "temple_recommend": {"f": (now - timedelta(days=5)).isoformat()},  # >3d -> warn
        "baptism_date": {"f": now.isoformat()},                             # fresh
        "patriarchal_blessing": {"t": now.isoformat()},                    # never fetched -> never
    })
    summary = db.field_staleness_summary(d, sid2)

    return [
        ("fetched stamps f (run1)", "f" in meta1.get("ministering_assignment", {}), True),
        ("sentinel: no f (run1 baptism)", "f" not in meta1.get("baptism_date", {}), True),
        ("sentinel: has t (run1 baptism)", "t" in meta1.get("baptism_date", {}), True),
        ("later fetch stamps f (baptism)", "f" in meta2.get("baptism_date", {}), True),
        ("sentinel preserves prior f", meta2["ministering_assignment"]["f"], ma_f0),
        ("sentinel bumps t past prior f", meta2["ministering_assignment"]["t"] > ma_f0, True),
        ("summary: 10d-old field -> error bucket", summary["calling"]["error"], 1),
        ("summary: 5d-old field -> warn bucket", summary["temple_recommend"]["warn"], 1),
        ("summary: fresh field -> fresh bucket", summary["baptism_date"]["fresh"], 1),
        ("summary: never-fetched -> never bucket", summary["patriarchal_blessing"]["never"], 1),
    ]


def scenario_reconcile_departed_safe_and_gated():
    """AXIS 4 (removed data): a member absent from a CLEANLY-scraped unit is hard-deleted; a member
    of a FAILED unit (not in keep set) is preserved; orphans (ward removed) removed with the flag.
    Empty report / empty keep-set no-op (a bad run never wipes). (db.reconcile_members.)"""
    d = FakeDB()
    sid = d.add_stake(999104, "Departed Stake")
    ua = d.add_unit(sid, 889201, "Ward A")
    ub = d.add_unit(sid, 889202, "Ward B")
    d.add_member(sid, ua, "p-a1", name="A1")     # present -> kept
    d.add_member(sid, ua, "p-a2", name="A2")     # absent, clean unit -> departed
    d.add_member(sid, ub, "p-b1", name="B1")     # Ward B FAILED this run -> preserved
    d.add_member(sid, None, "p-orph", name="Orph")  # ward removed -> departed with include_orphans

    removed = db.reconcile_members(d, sid, ["p-a1"], [ua], include_orphans=True)
    # Snapshot the post-reconcile state immediately (before the gate test re-adds p-a2).
    a1_kept = d.member("p-a1") is not None
    a2_removed = d.member("p-a2") is None
    b1_preserved = d.member("p-b1") is not None
    orph_removed = d.member("p-orph") is None

    # Gates: empty present / empty keep no-op (a bad run never deletes).
    d.add_member(sid, ua, "p-a2", name="A2")  # re-add to prove the gates don't touch it
    n_empty_present = db.reconcile_members(d, sid, [], [ua], include_orphans=True)
    n_empty_keep = db.reconcile_members(d, sid, ["p-a1"], [], include_orphans=True)

    return [
        ("present member kept", a1_kept, True),
        ("absent in clean unit removed", a2_removed, True),
        ("failed-unit member preserved", b1_preserved, True),
        ("orphan removed with include_orphans", orph_removed, True),
        ("reported 2 removed", removed, 2),
        ("empty present no-ops", n_empty_present, 0),
        ("empty keep-set no-ops", n_empty_keep, 0),
        ("no-op gates did not delete the re-added member", d.member("p-a2") is not None, True),
    ]


def scenario_prune_units_gated_orphans_members():
    """AXIS 4 + 5: a ward that LEFT the stake is pruned; its members orphan to unit_id NULL (FK set
    null) and its ward_leader roles cascade away. An empty keep-list no-ops. (db.prune_units.)"""
    d = FakeDB()
    sid = d.add_stake(999105, "Prune Stake")
    ua = d.add_unit(sid, 889301, "Ward A")
    ub = d.add_unit(sid, 889302, "Ward B (leaving)")
    d.add_member(sid, ua, "pm-a", name="A")
    d.add_member(sid, ub, "pm-b", name="B")
    d.add_role(sid, "ward_leader", unit_id=ub, lcr_person_uuid="wl-b", calling_name="Bishop")
    d.add_role(sid, "ward_leader", unit_id=ua, lcr_person_uuid="wl-a", calling_name="Bishop")

    removed = db.prune_units(d, sid, [889301])  # keep only Ward A

    survivor_units = {u["unit_number"] for u in d.units}
    return [
        ("1 unit pruned", removed, 1),
        ("Ward B removed", 889302 not in survivor_units, True),
        ("Ward A kept", 889301 in survivor_units, True),
        ("pruned ward's member orphaned (unit NULL)", d.member("pm-b")["unit_id"], None),
        ("kept ward's member untouched", d.member("pm-a")["unit_id"], ua),
        ("pruned ward's ward_leader cascaded away",
         any(r["lcr_person_uuid"] == "wl-b" for r in d.user_roles), False),
        ("kept ward's ward_leader survives",
         any(r["lcr_person_uuid"] == "wl-a" for r in d.user_roles), True),
        ("empty keep-list no-ops", db.prune_units(d, sid, []), 0),
    ]


# ============================================================================
# AXIS 4 (report side) — assemble/profile/neutralize: never invent a false negative
# ============================================================================

def _mk_member(**over):
    base = dict(
        name="t", unit="u", baptism_date="2024", birth_date="1 Jan 1990", friends="No",
        aaronic_priesthood="N/A", melchizedek_priesthood="N/A", calling="No",
        ministering_brothers_sisters="No", ministering_assignment="No",
        temple_recommend="No", patriarchal_blessing="No", living_ordinance="N/A",
        membership_duration=None, weeks_since_last_attendance=None, baptism_goal_date=None,
        friends_summary=None, sex="F")
    base.update(over)
    return report.CovenantPathMember(**base)


def scenario_report_no_profile_emits_sentinels():
    """AXIS 4: a bare progress record (NO profile subtree) must emit NEEDS_PROFILE (not a false
    'No'/'N/A') for profile-sourced fields, so the merge-upsert preserves last-good. After
    _mark_profile_blocked they become BLOCKED. (report._assemble + _mark_profile_blocked.)"""
    person = {"personUuid": "r1", "id": "r1", "name": "Rex"}
    m = report._assemble(person, details=None, unit_name="Ward A", birth=None, kind="new_member")
    pre = (m.aaronic_priesthood, m.calling, m.baptism_date, m.temple_recommend)
    report._mark_profile_blocked(m)
    post = (m.aaronic_priesthood, m.baptism_date, m.temple_recommend)
    return [
        ("no-profile priesthood -> NEEDS_PROFILE", pre[0], report.NEEDS_PROFILE),
        ("no-profile calling -> NEEDS_PROFILE", pre[1], report.NEEDS_PROFILE),
        ("no-profile baptism -> NEEDS_PROFILE", pre[2], report.NEEDS_PROFILE),
        ("after block: priesthood BLOCKED", post[0], report.BLOCKED),
        ("after block: baptism BLOCKED", post[1], report.BLOCKED),
        ("after block: recommend BLOCKED", post[2], report.BLOCKED),
    ]


def scenario_report_profile_union_never_downgrades():
    """AXIS 4 (modified data): the per-member profile UNIONs with the org-aggregate — a profile 'Yes'
    upgrades a calling; a profile 'No' NEVER downgrades a real org 'Yes'; ministering 'Yes' from
    details is never downgraded. (report._apply_profile.)"""
    # profile finds a sub-org calling the org-aggregate missed -> upgrade + surface the name
    m = _mk_member(calling="No")
    report._apply_profile(m, {"calling": "Yes", "_calling_names": ["RS Service Committee Member"]})
    # profile 'No' must not downgrade an org 'Yes'
    m2 = _mk_member(calling="Yes")
    report._apply_profile(m2, {"calling": "No"})
    # genuine no-calling
    m3 = _mk_member(calling="No")
    report._apply_profile(m3, {"calling": "No"})
    # ministering: details established Yes (via names); profile 'No' must not downgrade
    m4 = _mk_member(ministering_brothers_sisters="Yes")
    m4.details = {"ministeringBrothers": ["Bro A"]}
    report._apply_profile(m4, {"ministering_brothers_sisters": "No"})
    return [
        ("profile Yes upgrades calling", m.calling, "Yes"),
        ("calling name surfaced", (m.details or {}).get("callings"), ["RS Service Committee Member"]),
        ("profile No never downgrades org Yes", m2.calling, "Yes"),
        ("genuine no-calling stays No", m3.calling, "No"),
        ("ministering Yes not downgraded by profile No", m4.ministering_brothers_sisters, "Yes"),
    ]


def scenario_report_neutralize_uniform_stale():
    """AXIS 4 (silent-failure guard): a whole cohort uniformly 'No' for temple_recommend / calling is
    the stale-action signature, not real data -> neutralized to a sentinel so the upsert preserves
    last-good. A single real 'Yes' means it's NOT uniform -> not neutralized. (report._neutralize_uniform_stale.)"""
    rows_cal = [_mk_member(calling="No", temple_recommend="No") for _ in range(25)]
    neutralized = report._neutralize_uniform_stale(rows_cal, with_profile=True)

    rows_mixed = [_mk_member(calling="No", temple_recommend="No") for _ in range(24)] + \
                 [_mk_member(calling="Yes", temple_recommend="Active")]
    neutralized_mixed = report._neutralize_uniform_stale(rows_mixed, with_profile=True)

    # small cohort (<20) never neutralizes (uniformity is plausible)
    small = [_mk_member(calling="No", temple_recommend="No") for _ in range(5)]
    neutralized_small = report._neutralize_uniform_stale(small, with_profile=True)

    return [
        ("uniform calling neutralized", "calling" in neutralized, True),
        ("uniform recommend neutralized", "temple_recommend" in neutralized, True),
        ("neutralized calling -> sentinel", all(r.calling == report.NEEDS_PROFILE for r in rows_cal), True),
        ("a real Yes prevents calling neutralize", "calling" not in neutralized_mixed, True),
        ("a real Active prevents recommend neutralize", "temple_recommend" not in neutralized_mixed, True),
        ("small cohort not neutralized", neutralized_small, []),
    ]


def scenario_report_degraded_fetch_end_to_end():
    """AXIS 4 (fetch outcomes end-to-end): build_stake_report over a fake LCR where ONE unit's
    progress_record FAILS (skipped, not fatal) and the other succeeds; profiles are NOT fetched so
    gated fields are sentinels; the surviving unit's members come through. Then feeding the result
    to db.upsert_members PRESERVES any prior good values for the sentinels. (report.build_stake_report.)"""
    _patch_execute_values()
    # Fake covenant_path_access so build_stake_report doesn't hit the network for the matrix.
    report.covenant_path_access = lambda client: {
        "runner_positions": [{"name": "Stake President"}], "can_pull_all": True,
        "features": [{"feature": "menu.view.member.profiles", "allowed": True}], "missing": [],
    }
    # Neutralize the real retry backoff sleeps so the failing-unit path is instant (autonomous/fast).
    report.time.sleep = lambda *_a, **_k: None
    client = FakeLcrClient(
        stake_unit=999106, stake_name="E2E Stake",
        child_units=[(889401, "Ward A", "WARD"), (889402, "Ward B", "WARD")],
        # org_callings FAILS for Ward A -> calling_uuids is None -> calling stays a sentinel (the code
        # only sets a definitive "No" when org-callings is fetchable-but-empty). This is the genuine
        # "couldn't determine calling" degraded case the merge-upsert must preserve last-good for.
        org_callings={889401: RuntimeError("orgs 500"), 889402: {"unitOrgs": []}},
        member_lists={889401: [], 889402: []},
        progress={
            889401: {"newMemberList": [{"id": "e-1", "personUuid": "e-1", "name": "Eve",
                                        "cmisId": 111}]},
            889402: RuntimeError("progress-record 500 (transient)"),  # FAILS all retries
        },
        details={"e-1": RuntimeError("details 500")},  # details down -> friend names empty, not fatal
    )
    rows = report.build_stake_report(client, with_profile=False, verbose=False, delay=0)
    names = sorted(r.name for r in rows)

    # The surviving member's gated fields are sentinels (no profile) -> upsert preserves prior good.
    d = FakeDB()
    sid = d.add_stake(999106, "E2E Stake")
    ua = d.add_unit(sid, 889401, "Ward A")
    d.add_member(sid, ua, "e-1", name="Eve", calling="Yes", aaronic_priesthood="Yes")  # prior good
    payload = []
    for r in rows:
        rd = dict(r.__dict__)
        rd["unit_number"] = 889401
        payload.append(rd)
    db.upsert_members(d, sid, payload, {889401: ua})
    eve = d.member("e-1")

    return [
        ("failed unit skipped, other survives", names, ["Eve"]),
        ("surviving member assembled", len(rows), 1),
        ("no-profile calling is a sentinel pre-upsert",
         rows[0].calling in (report.NEEDS_PROFILE, report.BLOCKED), True),
        ("prior good calling preserved after degraded upsert", eve["calling"], "Yes"),
        ("prior good priesthood preserved after degraded upsert", eve["aaronic_priesthood"], "Yes"),
    ]


# ============================================================================
# AXIS 2+5b — credential staleness / expiry / takeover (most-elevated-wins)
# ============================================================================

def scenario_credential_staleness_alert_edge():
    """AXIS 5b (credential expired/stale): mark_failed stamps the failing state; claim_stale_notification
    returns True ONCE per failure streak (no spam); mark_succeeded clears it so the NEXT failure
    re-alerts. (backend.credentials.)"""
    d = FakeDB()
    sid = d.add_stake(999201, "Cred Stake")
    d.add_credential(sid, principal_email="provider@example.org")

    credentials.mark_failed(d, sid, "SSO did not complete — landed back on Okta")
    first = credentials.claim_stale_notification(d, sid)      # first failure -> alert
    second = credentials.claim_stale_notification(d, sid)     # same streak -> no alert
    # Snapshot scalars NOW (the credential dict is a live reference mutated by the next calls).
    failing_set = bool(d.credential(sid)["last_failed_at"])
    error_stored = (d.credential(sid)["last_error"] or "").startswith("SSO did not")

    credentials.mark_succeeded(d, sid)                         # recovered -> clears notified
    ok_failed = d.credential(sid)["last_failed_at"]
    ok_notified = d.credential(sid)["stale_notified_at"]
    # next failure re-alerts
    credentials.mark_failed(d, sid, "expired again")
    third = credentials.claim_stale_notification(d, sid)

    email = credentials.provider_email(d, sid)
    return [
        ("failing state recorded", failing_set, True),
        ("error message stored", error_stored, True),
        ("first failure claims the alert", first, True),
        ("same streak does NOT re-alert (no spam)", second, False),
        ("success clears failing state", ok_failed, None),
        ("success clears notified", ok_notified, None),
        ("new failure re-alerts (success->failure edge)", third, True),
        ("provider email available for the alert", email, "provider@example.org"),
    ]


def scenario_credential_save_roundtrip_encrypted():
    """The delegated session blob round-trips through envelope encryption and is NEVER stored in
    plaintext. (credentials.save_credential / get_credential — exercised with a fake conn that
    captures the written row, fully offline with a self-generated key.)"""
    captured = {}

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            # Only the INSERT carries the full row; the later SELECT (params=(stake_id,)) must NOT
            # overwrite it, or fetchone would index the 1-tuple and IndexError.
            if "insert into stake_credentials" in sql:
                captured["insert"] = params

        def fetchone(self):
            p = captured["insert"]
            # save_credential params order: (stake_id, principal_name, granting_role_ids, blob,
            #   coverage_json, access_rank, expires_at). get_credential selects, in order:
            #   principal_name, granting_role_ids, credential_enc, expires_at, revoked, coverage, access_rank
            return (p[1], p[2], p[3], p[6], False, None, p[5])

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

    conn = _Conn()
    grant = {"principal_name": "Pres", "granting_role_ids": [1, 52],
             "cookies": [{"name": "idx", "value": "SUPER-SECRET-COOKIE"}],
             "refresh_token": "RT-SECRET", "access_rank": 100, "expires_at": None}
    credentials.save_credential(conn, "stake-x", grant)
    blob = captured["insert"][3]
    got = credentials.get_credential(conn, "stake-x")

    return [
        ("blob is not plaintext (cookie)", "SUPER-SECRET-COOKIE" not in blob, True),
        ("blob is not plaintext (refresh)", "RT-SECRET" not in blob, True),
        ("decrypt restores cookies", got["cookies"][0]["value"], "SUPER-SECRET-COOKIE"),
        ("decrypt restores refresh token", got["refresh_token"], "RT-SECRET"),
        ("principal round-trips", got["principal_name"], "Pres"),
    ]


def scenario_enroll_most_elevated_wins():
    """AXIS 2 (same/higher/lower/none access vs existing credential): the enroll RPC's most-elevated-
    wins + same-principal + stale-takeover rule. Pure-logic mirror of the WHERE clause in migration
    0038 (the SQL is what runs in prod; this asserts the decision table the broker relies on)."""
    def enroll_replaces(existing, incoming):
        """Returns True iff ON CONFLICT would replace the stored credential (migration 0038 WHERE)."""
        if existing is None:
            return True  # fresh insert
        if existing.get("revoked"):
            return True
        if not bool((existing.get("coverage") or {}).get("complete")):
            return True
        if incoming["access_rank"] >= (existing.get("access_rank") if existing.get("access_rank") is not None else -1):
            return True
        if incoming["principal_email"].lower() == (existing.get("principal_email") or "").lower():
            return True
        if existing.get("last_failed_at") is not None:
            return True
        return False

    healthy_high = {"access_rank": 100, "principal_email": "boss@x.org",
                    "coverage": {"complete": True}, "revoked": False, "last_failed_at": None}

    same_principal = {"access_rank": 100, "principal_email": "boss@x.org"}     # same person refresh
    higher = {"access_rank": 200, "principal_email": "other@x.org"}            # higher access
    equal_other = {"access_rank": 100, "principal_email": "peer@x.org"}        # equal, different leader
    lower_other = {"access_rank": 50, "principal_email": "junior@x.org"}       # lower, different leader

    healthy_failing = dict(healthy_high, last_failed_at="2026-06-01T00:00:00")  # stale -> takeover
    incomplete = dict(healthy_high, coverage={"complete": False})

    return [
        ("none existing -> insert", enroll_replaces(None, lower_other), True),
        ("same principal refresh wins (even healthy)", enroll_replaces(healthy_high, same_principal), True),
        ("higher access wins", enroll_replaces(healthy_high, higher), True),
        ("equal access (fresher session) wins", enroll_replaces(healthy_high, equal_other), True),
        ("lower access different leader CANNOT clobber healthy", enroll_replaces(healthy_high, lower_other), False),
        ("lower access CAN take over a FAILING credential", enroll_replaces(healthy_failing, lower_other), True),
        ("lower access CAN take over an INCOMPLETE credential", enroll_replaces(incomplete, lower_other), True),
    ]


# ============================================================================
# AXIS 3+6 — admin visibility + protection of the audit/log surfaces
# ============================================================================

def scenario_audit_is_admin_only_and_complete():
    """AXIS 6: the access-change trail is COMPLETE (every grant/revoke recorded) and PROTECTED
    (admin-only). is_admin mirrors migration 0008; the SQL RLS that enforces login_audit/access_audit
    admin-only is proven LIVE by backend/test_login_audit.py. Here we assert the visibility predicate
    + that provisioning populated the audit. (roles._audit_access + is_admin.)"""
    d = FakeDB()
    d.add_admin("owner@example.org")
    sid = d.add_stake(999301, "Audit Stake")
    ua = d.add_unit(sid, 889501, "Ward A")
    unit_id_by_name = {"Ward A": ua}

    client = FakeLcrClient(
        stake_unit=999301, stake_name="Audit Stake",
        child_units=[(889501, "Ward A", "WARD")],
        org_callings={
            999301: _orgs([_position("s1", "S Pres", RID_STAKE_PRES, "Stake President", "Audit Stake")]),
            889501: _orgs([_position("b1", "Bishop", RID_BISHOP, "Bishop", "Ward A")]),
        },
        member_lists={889501: [{"personUuid": "b1", "email": "bishop@example.org"}]},
    )
    _provision(d, client, sid, unit_id_by_name)
    grants = [a for a in d.access_audit if a["action"] == "granted"]

    # admin-only visibility predicate
    admin_sees = fake_db.is_admin(d, "owner@example.org")
    stranger_sees = fake_db.is_admin(d, "stranger@example.org")
    anon_sees = fake_db.is_admin(d, None)

    return [
        ("provision recorded grants in access_audit", len(grants) >= 2, True),
        ("granted rows carry calling + scope",
         all(g.get("role") and g.get("calling") for g in grants), True),
        ("audit source is 'provision'", all(g["source"] == "provision" for g in grants), True),
        ("admin can read the audit (is_admin True)", admin_sees, True),
        ("non-admin cannot (is_admin False)", stranger_sees, False),
        ("anon cannot (is_admin False)", anon_sees, False),
    ]


def scenario_admin_view_revoke_add_access():
    """AXIS 3+6 (admin can view/revoke/add access): from the FakeDB an admin can SEE every role
    (the over/under-visibility surface), ADD a manual grant, and REVOKE one. These mirror the admin
    console operations (the RPCs invite_power_user/revoke_power_user/manual ward grants are proven
    LIVE by backend/test_power_users.py)."""
    d = FakeDB()
    d.add_admin("owner@example.org")
    sid = d.add_stake(999302, "AdminOps Stake")
    ua = d.add_unit(sid, 889601, "Ward A")
    d.add_role(sid, "stake_leader", unit_id=None, lcr_person_uuid="s1", calling_name="Stake President")
    d.add_role(sid, "ward_leader", unit_id=ua, lcr_person_uuid="b1", calling_name="Bishop")

    # VIEW: admin sees all roles (count); a non-admin has no such console access.
    all_roles = len(d.user_roles)

    # ADD: admin grants a manual stake-wide power user (email row).
    d.add_role(sid, "stake_leader", unit_id=None, email="newhelper@example.org", source="invitation")
    helper_can_see = len(fake_db.members_visible_to(d, email="newhelper@example.org"))
    d.add_member(sid, ua, "vis-1", name="V")  # something to see
    helper_can_see_after = len(fake_db.members_visible_to(d, email="newhelper@example.org"))

    # REVOKE: admin removes the manual grant -> helper sees nothing.
    d.user_roles = [r for r in d.user_roles if r["email"] != "newhelper@example.org"]
    helper_after_revoke = len(fake_db.members_visible_to(d, email="newhelper@example.org"))

    return [
        ("admin can enumerate all roles", all_roles, 2),
        ("added helper initially sees stake (0 members yet)", helper_can_see, 0),
        ("added helper sees the member after it exists", helper_can_see_after, 1),
        ("revoked helper sees nothing", helper_after_revoke, 0),
        ("admin-only console (is_admin gate)", fake_db.is_admin(d, "owner@example.org"), True),
    ]


def scenario_under_and_over_visibility_signals():
    """AXIS 6 (the two failure modes the audit exists to catch): UNDER-visibility = an 'allowed'
    login whose role_scope resolves to nothing (sees an empty app); OVER-visibility = a viewer who
    can see a stake they shouldn't. We assert the resolving predicate detects both. (RLS scope mirror
    + the login_audit.role_scope concept, migration 0034.)"""
    d = FakeDB()
    sid_a = d.add_stake(999303, "Stake A")
    sid_b = d.add_stake(999304, "Stake B")
    ua = d.add_unit(sid_a, 889701, "A1")
    d.add_member(sid_a, ua, "a-mem", name="A member")
    ub = d.add_unit(sid_b, 889801, "B1")
    d.add_member(sid_b, ub, "b-mem", name="B member")

    # UNDER: a user who logged in (allowed) but has NO role row -> role_scope 'none', sees nothing.
    under_scope = fake_db.members_visible_to(d, email="loggedin-but-noscope@example.org")

    # OVER: a Stake A leader must NOT see Stake B's members.
    d.add_role(sid_a, "stake_leader", unit_id=None, email="a-leader@example.org")
    a_leader_sees = fake_db.members_visible_to(d, email="a-leader@example.org")
    a_leader_sees_b = [m for m in a_leader_sees if m["stake_id"] == sid_b]

    return [
        ("under-visibility: no-scope login sees nothing", len(under_scope), 0),
        ("Stake A leader sees Stake A member", any(m["person_uuid"] == "a-mem" for m in a_leader_sees), True),
        ("no over-visibility: Stake A leader sees NO Stake B member", len(a_leader_sees_b), 0),
    ]


# ============================================================================
# runner
# ============================================================================

SCENARIOS = [
    # AXIS 1+2+5a — role -> scope, provisioning, calling changes
    scenario_role_scope_and_visibility,
    scenario_provision_grants_by_calling,
    scenario_calling_changed_revoke_and_add,
    scenario_revoke_gated_on_directory_fetch,
    scenario_email_and_invitation_rows_preserved,
    scenario_always_allowed_calling_safety_net,
    scenario_admin_added_calling_override,
    # AXIS 4 — data reconciliation
    scenario_upsert_merge_by_id_modified_added_removed,
    scenario_sentinel_preserves_last_good,
    scenario_field_freshness_tracking,
    scenario_reconcile_departed_safe_and_gated,
    scenario_prune_units_gated_orphans_members,
    # AXIS 4 — report assembly correctness
    scenario_report_no_profile_emits_sentinels,
    scenario_report_profile_union_never_downgrades,
    scenario_report_neutralize_uniform_stale,
    scenario_report_degraded_fetch_end_to_end,
    # AXIS 2+5b — credential staleness / expiry / takeover
    scenario_credential_staleness_alert_edge,
    scenario_credential_save_roundtrip_encrypted,
    scenario_enroll_most_elevated_wins,
    # AXIS 3+6 — admin visibility + protection
    scenario_audit_is_admin_only_and_complete,
    scenario_admin_view_revoke_add_access,
    scenario_under_and_over_visibility_signals,
]


def run() -> int:
    # Save the module globals the scenarios monkeypatch so a leaked patch can't poison a later
    # in-process import (e.g. pytest collecting test_field_meta after this module).
    _saved = {
        "report.covenant_path_access": report.covenant_path_access,
        "report.time.sleep": report.time.sleep,
        "db._now_iso": db._now_iso,
        "db.execute_values": db.psycopg2.extras.execute_values,
        "roles.fetch_access_matrix": roles.fetch_access_matrix,
    }
    total = 0
    passed = 0
    failed_scenarios = []
    try:
        for scenario in SCENARIOS:
            print(f"\n== {scenario.__name__} ==")
            try:
                checks = scenario()
            except Exception as exc:  # noqa: BLE001
                import traceback
                print(f"  [CRASH] {type(exc).__name__}: {exc}")
                traceback.print_exc()
                failed_scenarios.append(scenario.__name__)
                continue
            ok_here = True
            for name, got, want in checks:
                good = got == want
                total += 1
                passed += 1 if good else 0
                ok_here = ok_here and good
                print(f"  [{'PASS' if good else 'FAIL'}] {name}: {got!r} (expected {want!r})")
            if not ok_here:
                failed_scenarios.append(scenario.__name__)
    finally:
        report.covenant_path_access = _saved["report.covenant_path_access"]
        report.time.sleep = _saved["report.time.sleep"]
        db._now_iso = _saved["db._now_iso"]
        db.psycopg2.extras.execute_values = _saved["db.execute_values"]
        roles.fetch_access_matrix = _saved["roles.fetch_access_matrix"]

    print(f"\n== {passed}/{total} checks passed across {len(SCENARIOS)} scenarios ==")
    if failed_scenarios:
        print("FAILED scenarios: " + ", ".join(failed_scenarios))
    return 0 if not failed_scenarios else 1


def test_scenarios():
    """pytest entrypoint — the whole matrix must be green (no live DB / network / secrets needed)."""
    assert run() == 0, "covenant-path scenario matrix had failing checks (see stdout)"


if __name__ == "__main__":
    sys.exit(run())
