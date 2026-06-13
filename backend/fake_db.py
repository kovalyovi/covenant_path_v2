"""
A tiny in-memory Postgres stand-in for the OFFLINE scenario suite (backend/test_scenarios.py).

The existing access tests (test_rls / test_power_users / test_admins / test_reconcile / …) talk to a
LIVE Supabase and roll back. That proves the *SQL* (RLS policies, SECURITY DEFINER RPCs) but needs
credentials + network. This module lets the scenario matrix run with NOTHING provided — no DB, no
LCR, no secrets — by simulating just the rows + statements the REAL Python sync code issues.

It is deliberately NOT a general SQL engine. It recognizes the exact, stable statements that
`backend.roles.provision_roles`, `backend.db.{upsert_members, reconcile_members, prune_units,
field_staleness_summary}`, and `backend.credentials.*` execute, and applies their semantics to
in-memory tables. If one of those internal statements is reworded, the corresponding handler here
must follow — itself a useful tripwire that the storage contract changed.

The point of value: the merge-by-id / sentinel-preservation / freshness / revoke-gating /
credential-staleness logic under test is the REAL imported code; only the rows live here.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone


# Sentinel UUID the unique-key uses for "no unit" (stake-wide); mirrors the migrations' coalesce.
_NIL_UNIT = "00000000-0000-0000-0000-000000000000"


def _norm(sql: str) -> str:
    """Collapse whitespace so multi-line statements match by their stable shape."""
    return re.sub(r"\s+", " ", sql).strip().lower()


class FakeCursor:
    """Recognizes the handful of statements the real sync code runs and mutates FakeDB tables.

    fetchone/fetchall return tuples in the SELECT's column order, matching psycopg2 (the real code
    indexes results positionally)."""

    def __init__(self, db: "FakeDB"):
        self._db = db
        self._result: list[tuple] = []
        self.rowcount = -1

    # context-manager: the real code uses `with conn.cursor() as cur:`
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def execute(self, sql: str, params=None):
        params = params or ()
        n = _norm(sql)
        self._result = []
        self.rowcount = -1

        # ---- roles.provision_roles ---------------------------------------
        if n.startswith("select lower(calling_match), grants_access from calling_access_overrides"):
            self._result = [(m.lower(), g) for m, g in self._db.calling_overrides]
            return

        if n.startswith("select role, unit_id::text, lcr_person_uuid from user_roles"):
            stake_id = params[0]
            self._result = [
                (r["role"], (str(r["unit_id"]) if r["unit_id"] is not None else None), r["lcr_person_uuid"])
                for r in self._db.user_roles
                if r["stake_id"] == stake_id and r["lcr_person_uuid"] is not None
            ]
            return

        if n.startswith("insert into user_roles (stake_id, unit_id, role, lcr_person_uuid, auth_id"):
            self._upsert_user_role(params)
            return

        if n.startswith("delete from user_roles where stake_id=") and "returning role" in n:
            self._revoke_user_roles(params)
            return

        # ---- access_audit (roles._audit_access) --------------------------
        if n.startswith("insert into access_audit"):
            self._insert_access_audit(params)
            return

        # ---- db.upsert_members -------------------------------------------
        if n.startswith("select person_uuid, field_meta from members where stake_id="):
            stake_id = params[0]
            self._result = [(r["person_uuid"], r.get("field_meta") or {})
                            for r in self._db.members if r["stake_id"] == stake_id]
            return

        # ---- db.count_reconcile_candidates (the degraded-run deferral guard) ----
        if n.startswith("select count(*) from members where stake_id =") and "person_uuid <> all" in n:
            self._count_reconcile(n, params)
            return

        # ---- db.reconcile_members ----------------------------------------
        if n.startswith("delete from members where stake_id =") and "person_uuid <> all" in n:
            self._reconcile_members(n, params)
            return

        # ---- db.prune_units ----------------------------------------------
        if n.startswith("delete from units where stake_id=") and "unit_number <> all" in n:
            self._prune_units(params)
            return

        # ---- db.field_staleness_summary ----------------------------------
        if n.startswith("select field_meta from members where stake_id="):
            stake_id = params[0]
            self._result = [(r.get("field_meta") or {},)
                            for r in self._db.members if r["stake_id"] == stake_id]
            return

        # ---- credentials.* -----------------------------------------------
        if n.startswith("update stake_credentials set last_failed_at=now()"):
            self._cred_update(params[-1], {"last_failed_at": self._db.now(), "last_error": params[0]})
            return
        if n.startswith("update stake_credentials set last_succeeded_at=now()"):
            self._cred_update(params[0], {"last_succeeded_at": self._db.now(), "last_failed_at": None,
                                          "last_error": None, "stale_notified_at": None})
            return
        if n.startswith("update stake_credentials set stale_notified_at=now()"):
            sid = params[0]
            cred = self._db.credential(sid)
            if cred is not None and cred.get("stale_notified_at") is None:
                cred["stale_notified_at"] = self._db.now()
                self.rowcount = 1
            else:
                self.rowcount = 0
            return
        if n.startswith("select principal_email from stake_credentials where stake_id="):
            sid = params[0]
            cred = self._db.credential(sid)
            self._result = [(cred["principal_email"],)] if cred and not cred.get("revoked") else []
            return

        raise NotImplementedError(f"FakeCursor has no handler for: {n[:120]}")

    # -- handlers ----------------------------------------------------------
    def _upsert_user_role(self, params):
        # params: (stake_id, unit_id, role, lcr_person_uuid, auth_id_raw, calling_name, email)
        stake_id, unit_id, role, lcr_uuid, _auth_raw, calling, email = params
        auth_id = (lcr_uuid or None)  # nullif(%s,'')::uuid with the same person uuid
        key_unit = str(unit_id) if unit_id is not None else _NIL_UNIT
        key_subject = (lcr_uuid or (email or "").lower() or "")
        for r in self._db.user_roles:
            if (r["stake_id"] == stake_id and
                    (str(r["unit_id"]) if r["unit_id"] is not None else _NIL_UNIT) == key_unit and
                    r["role"] == role and
                    (r["lcr_person_uuid"] or (r["email"] or "").lower() or "") == key_subject):
                # do update set calling_name, auth_id, email=coalesce(excluded.email, existing)
                r["calling_name"] = calling
                r["auth_id"] = auth_id
                r["email"] = email if email is not None else r["email"]
                return
        self._db.user_roles.append({
            "stake_id": stake_id, "unit_id": unit_id, "role": role,
            "lcr_person_uuid": lcr_uuid, "auth_id": auth_id, "calling_name": calling,
            "email": email, "source": "calling", "invited_by_email": None,
        })

    def _revoke_user_roles(self, params):
        # params: (stake_id, keep_list, stake_ok, ward_ok)
        stake_id, keep, stake_ok, ward_ok = params
        keep_set = set(keep or [])
        removed, survivors = [], []
        for r in self._db.user_roles:
            is_candidate = (
                r["stake_id"] == stake_id and
                r["lcr_person_uuid"] is not None and
                r["lcr_person_uuid"] not in keep_set and
                ((r["role"] == "stake_leader" and stake_ok) or (r["role"] == "ward_leader" and ward_ok))
            )
            if is_candidate:
                removed.append((r["role"], (str(r["unit_id"]) if r["unit_id"] is not None else None),
                                r["lcr_person_uuid"], r["calling_name"], r["email"]))
            else:
                survivors.append(r)
        self._db.user_roles = survivors
        self._result = removed
        self.rowcount = len(removed)

    def _insert_access_audit(self, params):
        # columns: stake_id, stake_unit, action, role, unit_id, person_uuid, name, email, calling, source
        keys = ["stake_id", "stake_unit", "action", "role", "unit_id", "person_uuid",
                "name", "email", "calling"]
        row = dict(zip(keys, params))
        row["source"] = "provision"
        self._db.access_audit.append(row)
        self.rowcount = 1

    def _candidates(self, n, params):
        """Shared predicate for count + delete: which members WOULD be reconciled away."""
        stake_id, present, keep_unit_ids = params
        present_set = set(present or [])
        keep_set = {str(u) for u in (keep_unit_ids or [])}
        include_orphans = "unit_id is null" in n
        out = []
        for r in self._db.members:
            if r["stake_id"] != stake_id or r["person_uuid"] in present_set:
                continue
            uid = r["unit_id"]
            unit_match = (str(uid) in keep_set) if uid is not None else False
            if include_orphans and uid is None:
                unit_match = True
            if unit_match:
                out.append(r)
        return out

    def _count_reconcile(self, n, params):
        # db.count_reconcile_candidates gates on non-empty lists too (returns 0 otherwise).
        _stake_id, present, keep_unit_ids = params
        if not present or not keep_unit_ids:
            self._result = [(0,)]
            return
        self._result = [(len(self._candidates(n, params)),)]

    def _reconcile_members(self, n, params):
        # sql: delete from members where stake_id=%s and person_uuid <> all(%s) and <unit_clause>
        doomed = {id(r) for r in self._candidates(n, params)}
        removed = [r for r in self._db.members if id(r) in doomed]
        self._db.members = [r for r in self._db.members if id(r) not in doomed]
        self.rowcount = len(removed)

    def _prune_units(self, params):
        stake_id, keep_numbers = params
        keep_set = set(keep_numbers or [])
        removed_unit_ids = [u["id"] for u in self._db.units
                            if u["stake_id"] == stake_id and u["unit_number"] not in keep_set]
        self._db.units = [u for u in self._db.units
                          if not (u["stake_id"] == stake_id and u["unit_number"] not in keep_set)]
        # FK on delete set null: orphan affected members; cascade ward_leader roles for removed units.
        for m in self._db.members:
            if m["unit_id"] in removed_unit_ids:
                m["unit_id"] = None
        self._db.user_roles = [r for r in self._db.user_roles if r["unit_id"] not in removed_unit_ids]
        self.rowcount = len(removed_unit_ids)

    def _cred_update(self, stake_id, fields):
        cred = self._db.credential(stake_id)
        if cred is not None:
            cred.update(fields)
            self.rowcount = 1
        else:
            self.rowcount = 0


class FakeDB:
    """Holds the in-memory tables + hands out FakeCursors. commit() is a no-op (single process)."""

    def __init__(self):
        self.stakes: list[dict] = []
        self.units: list[dict] = []
        self.members: list[dict] = []
        self.user_roles: list[dict] = []
        self.access_audit: list[dict] = []
        self.stake_credentials: list[dict] = []
        self.app_admins: list[dict] = []
        self.calling_overrides: list[tuple] = []  # [(calling_match, grants_access)]
        self._frozen_now: str | None = None

    # psycopg2-ish surface
    def cursor(self, *a, **k):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    # time control (so freshness/staleness tests are deterministic)
    def now(self) -> str:
        return self._frozen_now or datetime.now(timezone.utc).isoformat()

    def set_now(self, iso: str | None):
        self._frozen_now = iso

    # seed helpers
    def add_stake(self, unit_number: int, name: str) -> str:
        sid = str(uuid.uuid4())
        self.stakes.append({"id": sid, "unit_number": unit_number, "name": name})
        return sid

    def add_unit(self, stake_id: str, unit_number: int, name: str, unit_type: str = "WARD") -> str:
        uid = str(uuid.uuid4())
        self.units.append({"id": uid, "stake_id": stake_id, "unit_number": unit_number,
                           "name": name, "unit_type": unit_type})
        return uid

    def add_member(self, stake_id: str, unit_id, person_uuid: str, **cols) -> dict:
        row = {"stake_id": stake_id, "unit_id": unit_id, "person_uuid": person_uuid,
               "field_meta": {}, **cols}
        self.members.append(row)
        return row

    def add_role(self, stake_id, role, *, unit_id=None, lcr_person_uuid=None, email=None,
                 source="calling", auth_id=None, calling_name=None):
        self.user_roles.append({
            "stake_id": stake_id, "unit_id": unit_id, "role": role,
            "lcr_person_uuid": lcr_person_uuid, "auth_id": auth_id or lcr_person_uuid,
            "email": email, "source": source, "invited_by_email": None,
            "calling_name": calling_name,
        })

    def add_admin(self, email: str):
        self.app_admins.append({"email": email.lower(), "invited_by_email": "test"})

    def add_credential(self, stake_id, **cols):
        row = {"stake_id": stake_id, "revoked": False, "principal_email": None,
               "last_failed_at": None, "last_error": None, "last_succeeded_at": None,
               "stale_notified_at": None, "access_rank": None, "coverage": None, **cols}
        self.stake_credentials.append(row)
        return row

    def credential(self, stake_id) -> dict | None:
        for c in self.stake_credentials:
            if c["stake_id"] == stake_id:
                return c
        return None

    # query helpers for assertions
    def member(self, person_uuid: str) -> dict | None:
        for m in self.members:
            if m["person_uuid"] == person_uuid:
                return m
        return None

    def roles_for(self, *, role=None) -> list[dict]:
        return [r for r in self.user_roles if role is None or r["role"] == role]


# --- execute_values shim ------------------------------------------------------
# db.upsert_members calls psycopg2.extras.execute_values(cur, sql, rows). The test patches that
# symbol to route here so the REAL upsert_members merge SQL semantics run against FakeDB rows.

# Mirror backend.db exactly (kept local to avoid importing db at module-load time).
_MEMBER_COLUMNS = [
    "person_uuid", "name", "unit_name", "baptism_date", "birth_date", "friends", "friends_count",
    "aaronic_priesthood", "melchizedek_priesthood", "calling",
    "ministering_brothers_sisters", "ministering_assignment", "temple_recommend",
    "patriarchal_blessing", "living_ordinance", "family_name_prepared", "first_temple_visit",
    "membership_duration", "sex",
    "kind", "baptism_goal_date", "details",
]
_GATED_COLUMNS = frozenset({
    "baptism_date", "aaronic_priesthood", "melchizedek_priesthood", "calling",
    "ministering_brothers_sisters", "ministering_assignment", "temple_recommend",
    "patriarchal_blessing", "living_ordinance", "family_name_prepared", "first_temple_visit",
})
_SENTINELS = ("needs-profile-api", "blocked: insufficient calling access")


def _unwrap(v):
    """psycopg2.extras.Json(x) wraps a value; the shim wants the raw python object back."""
    adapted = getattr(v, "adapted", None)
    return adapted if adapted is not None else v


def execute_values_shim(cur: FakeCursor, sql: str, rows):
    """Stand-in for psycopg2.extras.execute_values for the members upsert ONLY.

    Applies the same ON CONFLICT merge db._merge_expr encodes: gated columns preserve the last-good
    value when the incoming value is a sentinel; friends_count keeps last-good on NULL; everything
    else takes the fresh value; field_meta takes the freshly-computed map."""
    db = cur._db
    rows = list(rows)
    for row in rows:
        stake_id = row[0]
        unit_id = row[1]
        vals = dict(zip(_MEMBER_COLUMNS, row[2:2 + len(_MEMBER_COLUMNS)]))
        field_meta = _unwrap(row[2 + len(_MEMBER_COLUMNS)])
        vals["details"] = _unwrap(vals.get("details"))
        puid = vals["person_uuid"]

        existing = next((m for m in db.members
                         if m["stake_id"] == stake_id and m["person_uuid"] == puid), None)
        if existing is None:
            new = {"stake_id": stake_id, "unit_id": unit_id, "field_meta": field_meta}
            for c in _MEMBER_COLUMNS:
                new[c] = vals.get(c)
            db.members.append(new)
            continue
        # ON CONFLICT update
        existing["unit_id"] = unit_id
        existing["field_meta"] = field_meta
        for c in _MEMBER_COLUMNS:
            if c == "person_uuid":
                continue
            incoming = vals.get(c)
            if c == "friends_count":
                existing[c] = incoming if incoming is not None else existing.get(c)
            elif c in _GATED_COLUMNS:
                cleaned = None if (isinstance(incoming, str) and incoming in _SENTINELS) else incoming
                existing[c] = cleaned if cleaned is not None else existing.get(c)
            else:
                existing[c] = incoming
    cur.rowcount = len(rows)


# --- RLS scope mirror ---------------------------------------------------------
# The authoritative RLS is the SQL in migrations 0002/0004/0005 (proven by the LIVE test_rls.py /
# test_power_users.py). For the OFFLINE matrix we evaluate the SAME predicate in Python so we can
# assert WHO sees WHICH members per scenario without a database. Faithful to the policy:
#   members visible if EXISTS a user_role for this viewer (matched by auth_id OR lower(email)) whose
#   stake_id = member.stake_id AND (unit_id IS NULL OR unit_id = member.unit_id).

def members_visible_to(db: FakeDB, *, auth_id: str | None = None, email: str | None = None) -> list[dict]:
    em = (email or "").lower() or None
    return [m for m in db.members if _viewer_matches_member(db, m, auth_id, em)]


def _viewer_matches_member(db: FakeDB, member: dict, auth_id, email_lower) -> bool:
    for ur in db.user_roles:
        ident = (auth_id is not None and ur["auth_id"] == auth_id) or \
                (email_lower is not None and (ur["email"] or "").lower() == email_lower)
        if not ident:
            continue
        if ur["stake_id"] != member["stake_id"]:
            continue
        if ur["unit_id"] is None or ur["unit_id"] == member["unit_id"]:
            return True
    return False


def is_admin(db: FakeDB, email: str | None) -> bool:
    """Mirror of is_admin() (migration 0008): the verified email is in app_admins."""
    if not email:
        return False
    return any(a["email"] == email.lower() for a in db.app_admins)
