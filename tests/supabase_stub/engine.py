"""
In-memory PostgREST-ish engine for the broker's Supabase REST calls.

Implements ONLY what backend/auth_broker actually sends (admin.py / enroll.py /
identity_cache.py / session_mint.py / app.py):
  - filters: eq. / neq. / is.null / not.is.null / in.(...) / gt|gte|lt|lte.
  - select projection, including the stakes -> stake_credentials embed. PostgREST returns a
    TO-MANY embed as a JSON LIST (0068 made the relationship one-stake-to-many-credentials) — the
    broker normalizes list-or-object defensively (the 2026-06-09 shape bug: a to-one embed arrived
    as an object and iterating it yielded keys).
  - order=col.asc|desc[.nullslast], limit/offset, Range header, Prefer: count=exact
    (Content-Range "start-end/total"), return=representation|minimal,
    resolution=merge-duplicates (+ on_conflict).
  - rpc/enroll_stake_credential replicating migration 0068 faithfully.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

RESERVED_PARAMS = {"select", "order", "limit", "offset", "on_conflict", "apikey", "columns"}

# parent table -> {embed name -> (parent key, child key, to_one)}
# stakes -> stake_credentials is TO-MANY since 0068 (one row per leader per stake).
RELATIONSHIPS = {
    "stakes": {"stake_credentials": ("id", "stake_id", False)},
}

# upsert key when on_conflict isn't sent (PostgREST defaults to the primary key).
# stake_credentials' PK is the surrogate id since 0068 (was stake_id under the single-row model).
DEFAULT_PK = {
    "church_identities": "username",
    "app_admins": "email",
    "stake_settings": "stake_id",
    "stake_credentials": "id",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _matches(row: dict, col: str, expr: str) -> bool:
    if expr.startswith("not."):
        return not _matches(row, col, expr[4:])
    op, _, val = expr.partition(".")
    v = row.get(col)
    if op == "eq":
        return _as_str(v) == val
    if op == "neq":
        return _as_str(v) != val
    if op == "is":
        if val == "null":
            return v is None
        return _as_str(v) == val  # is.true / is.false
    if op == "in":
        vals = [x.strip().strip('"') for x in val.strip("()").split(",")]
        return _as_str(v) in vals
    if op in ("gt", "gte", "lt", "lte"):
        try:
            left, right = float(v), float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            left, right = _as_str(v), val  # ISO timestamps compare lexicographically
        return {"gt": left > right, "gte": left >= right,
                "lt": left < right, "lte": left <= right}[op]
    raise ValueError(f"unsupported PostgREST operator: {col}={expr}")


def _split_select(select: str) -> list[str]:
    """Split a select list on top-level commas (embeds carry their own commas in parens)."""
    parts, depth, cur = [], 0, ""
    for ch in select:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


class Store:
    """All tables, plus the GoTrue-ish auth state (users / otps)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.tables: dict[str, list[dict]] = {}
        self.users: dict[str, dict] = {}   # email -> user row
        self.otps: dict[str, str] = {}     # email -> last issued otp
        # One-shot RPC failure injection (set via POST /__test/control {"fail_rpc": name}):
        # the next call to that RPC answers 500 instead of running. Lets e2e prove a failing
        # enroll surfaces its reason to the client instead of a bare "could not be set up".
        self.fail_next_rpc: set[str] = set()

    # ---- lifecycle -----------------------------------------------------------------
    def reset(self) -> None:
        with self.lock:
            self.tables.clear()
            self.users.clear()
            self.otps.clear()
            self.fail_next_rpc.clear()

    def seed(self, payload: dict) -> dict:
        """Replace the given tables' contents (only the tables present in the payload)."""
        out = {}
        with self.lock:
            for table, rows in payload.items():
                if not isinstance(rows, list):
                    raise ValueError(f"seed for {table!r} must be a list of rows")
                self.tables[table] = [self._with_id(table, dict(r)) for r in rows]
                out[table] = len(rows)
        return out

    def rows(self, table: str) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.tables.get(table, [])]

    @staticmethod
    def _with_id(table: str, row: dict) -> dict:
        if "id" not in row and table not in ("app_admins", "church_identities",
                                             "stake_settings", "login_audit"):
            row["id"] = str(uuid.uuid4())
        return row

    # ---- query ----------------------------------------------------------------------
    def select(self, table: str, params: dict[str, str]) -> list[dict]:
        with self.lock:
            rows = [r for r in self.tables.get(table, []) if self._row_ok(r, params)]
            order = params.get("order")
            if order:
                rows = self._order(rows, order)
            return [self._project(table, r, params.get("select")) for r in rows]

    def _row_ok(self, row: dict, params: dict[str, str]) -> bool:
        for col, expr in params.items():
            if col in RESERVED_PARAMS or "." in col:  # embedded-table filters unsupported
                continue
            if not _matches(row, col, expr):
                return False
        return True

    @staticmethod
    def _order(rows: list[dict], order: str) -> list[dict]:
        for term in reversed(order.split(",")):
            bits = term.split(".")
            col = bits[0]
            desc = "desc" in bits[1:]
            nones_last = "nullslast" in bits[1:] or desc  # postgres: desc puts nulls first by
            # default, but the broker always pairs desc with nullslast where it matters.
            rows = sorted(
                rows,
                key=lambda r: ((r.get(col) is None) if nones_last else (r.get(col) is not None),
                               _as_str(r.get(col))),
                reverse=desc,
            )
        return rows

    def _project(self, table: str, row: dict, select: str | None) -> dict:
        if not select or select.strip() == "*":
            return dict(row)
        out: dict = {}
        for item in _split_select(select):
            if "(" in item:
                name, _, inner = item.partition("(")
                inner = inner.rstrip(")")
                out[name] = self._embed(table, name, row, inner)
            else:
                out[item] = row.get(item)
        return out

    def _embed(self, table: str, embed_name: str, row: dict, inner_select: str):
        rel = RELATIONSHIPS.get(table, {}).get(embed_name)
        if rel is None:
            return None
        parent_key, child_key, to_one = rel
        matches = [r for r in self.tables.get(embed_name, [])
                   if _as_str(r.get(child_key)) == _as_str(row.get(parent_key))]
        projected = [self._project(embed_name, m, inner_select or "*") for m in matches]
        if to_one:
            return projected[0] if projected else None
        return projected

    # ---- mutate ----------------------------------------------------------------------
    def insert(self, table: str, payload, prefer: str, on_conflict: str | None) -> list[dict]:
        rows = payload if isinstance(payload, list) else [payload]
        merge = "merge-duplicates" in prefer
        key = on_conflict or DEFAULT_PK.get(table, "id")
        written: list[dict] = []
        with self.lock:
            existing = self.tables.setdefault(table, [])
            for r in rows:
                r = dict(r)
                target = None
                if merge:
                    target = next((e for e in existing
                                   if key in r and _as_str(e.get(key)) == _as_str(r.get(key))),
                                  None)
                if target is not None:
                    target.update(r)  # merge-duplicates updates ONLY the payload's columns
                    written.append(dict(target))
                else:
                    r = self._with_id(table, r)
                    existing.append(r)
                    written.append(dict(r))
        return written

    def update(self, table: str, payload: dict, params: dict[str, str]) -> list[dict]:
        updated = []
        with self.lock:
            for r in self.tables.get(table, []):
                if self._row_ok(r, params):
                    r.update(payload)
                    updated.append(self._project(table, r, params.get("select")))
        return updated

    def delete(self, table: str, params: dict[str, str]) -> int:
        with self.lock:
            before = self.tables.get(table, [])
            kept = [r for r in before if not self._row_ok(r, params)]
            self.tables[table] = kept
            return len(before) - len(kept)

    # ---- the 0039 unenroll-tier RPCs ------------------------------------------------------
    def rpc_wipe_stake_members(self, stake_id: str) -> int:
        """Replicates wipe_stake_members(p_stake_id): delete the stake's MEMBER rows only and
        reset its freshness (sync_state='idle', last_synced_at=null); roles + credential stay."""
        with self.lock:
            before = self.tables.get("members", [])
            kept = [r for r in before if _as_str(r.get("stake_id")) != _as_str(stake_id)]
            self.tables["members"] = kept
            for s in self.tables.get("stakes", []):
                if _as_str(s.get("id")) == _as_str(stake_id):
                    s["sync_state"] = "idle"
                    s["last_synced_at"] = None
            return len(before) - len(kept)

    def rpc_remove_stake(self, stake_id: str) -> None:
        """Replicates remove_stake(p_stake_id): full offboard — credential + members + roles +
        diagnostics + the stake row. Idempotent like the SQL (deleting nothing is fine)."""
        with self.lock:
            for table, col in (("stake_credentials", "stake_id"), ("members", "stake_id"),
                               ("user_roles", "stake_id"), ("sync_diagnostics", "stake_id"),
                               ("stakes", "id")):
                rows = self.tables.get(table, [])
                self.tables[table] = [r for r in rows
                                      if _as_str(r.get(col)) != _as_str(stake_id)]

    # ---- the 0068 enroll RPC ------------------------------------------------------------
    def rpc_enroll_stake_credential(self, body: dict) -> str:
        """Replicates backend/migrations/0068_multi_credential_highest_wins.sql:

          insert into stakes ... on conflict (unit_number) do update set name -> stake id
          insert into stake_credentials ... on conflict (stake_id, principal_email) do update set
              <all enroll columns>, revoked=false, revoked_at=null, updated_at=now(),
              last_failed_at=null, last_error=null, stale_notified_at=null,
              access_rank = greatest(old, new) (a degraded scrape never demotes a leader),
              coverage.complete = old-complete OR new-complete (complete side's features win)
          Effective holder = max access_rank among non-revoked rows (freshest wins a tie).

        D82 supersedes 0055's single-row most-elevated-wins: a narrower enrollment is no longer
        REFUSED — it is stored as a standby, and the sync keeps running on the highest live
        credential. History actions: enrolled | refreshed | took_over | stored_backup.
        (The stake id is returned either way.)
        """
        with self.lock:
            unit_number = body.get("p_unit_number")
            stakes = self.tables.setdefault("stakes", [])
            stake = next((s for s in stakes
                          if _as_str(s.get("unit_number")) == _as_str(unit_number)), None)
            if stake is None:
                stake = {"id": str(uuid.uuid4()), "unit_number": unit_number,
                         "name": body.get("p_stake_name"), "onboarded_at": _now(),
                         "last_synced_at": None}
                stakes.append(stake)
            else:
                stake["name"] = body.get("p_stake_name")
            stake_id = stake["id"]

            in_email = (body.get("p_principal_email") or "").lower()
            new_rank = body.get("p_access_rank")
            new_cov = body.get("p_coverage") or {}
            new_complete = bool(new_cov.get("complete"))
            creds = self.tables.setdefault("stake_credentials", [])
            history = self.tables.setdefault("stake_credential_history", [])

            def _effective(rows):
                live = [c for c in rows if not c.get("revoked")]
                if not live:
                    return None
                return max(live, key=lambda c: (
                    c.get("access_rank") if c.get("access_rank") is not None else -1,
                    c.get("updated_at") or ""))

            prior = _effective([c for c in creds if _as_str(c.get("stake_id")) == _as_str(stake_id)])
            prior_email = (prior or {}).get("principal_email") or None
            prior_rank = (prior or {}).get("access_rank")
            had_rows = any(_as_str(c.get("stake_id")) == _as_str(stake_id) for c in creds)
            own = next((c for c in creds
                        if _as_str(c.get("stake_id")) == _as_str(stake_id)
                        and (c.get("principal_email") or "").lower() == in_email), None)
            had_own_row = own is not None

            def _log(action):
                history.append({
                    "id": str(uuid.uuid4()), "stake_id": stake_id, "action": action,
                    "principal_name": body.get("p_principal_name"), "principal_email": in_email,
                    "access_rank": new_rank,
                    "coverage_complete": new_complete,
                    "has_refresh_token": body.get("p_has_refresh_token"),
                    "prior_principal_email": prior_email, "prior_access_rank": prior_rank,
                    "created_at": _now()})

            if own is None:
                # First enrollment for this leader: their own row (a standby when a broader
                # credential already provides the stake).
                creds.append({
                    "id": str(uuid.uuid4()), "stake_id": stake_id,
                    "principal_name": body.get("p_principal_name"),
                    "principal_email": in_email,
                    "granting_role_ids": body.get("p_granting_role_ids"),
                    "credential_enc": body.get("p_credential_enc"),
                    "coverage": body.get("p_coverage"),
                    "access_rank": new_rank,
                    "expires_at": body.get("p_expires_at"),
                    "has_refresh_token": body.get("p_has_refresh_token"),
                    "revoked": False, "revoked_at": None, "updated_at": _now(),
                    "last_failed_at": None, "last_error": None, "stale_notified_at": None,
                })
                # A fresh row is effective iff no broader live credential exists (tie → the fresh
                # row wins, matching SQL's updated_at-desc tie-break).
                effective = _effective([c for c in creds if _as_str(c.get("stake_id")) == _as_str(stake_id)])
                if not had_rows:
                    action = "enrolled"
                elif effective is not None and (effective.get("principal_email") or "").lower() == in_email:
                    action = "took_over"
                else:
                    action = "stored_backup"
            else:
                # Same leader re-authorizing: refresh their row, keeping their HIGHEST demonstrated
                # rank and the complete side's coverage (a degraded scrape never demotes them).
                old_complete = bool((own.get("coverage") or {}).get("complete"))
                own.update({
                    "principal_name": body.get("p_principal_name"),
                    "granting_role_ids": body.get("p_granting_role_ids"),
                    "credential_enc": body.get("p_credential_enc"),
                    "coverage": {
                        "complete": old_complete or new_complete,
                        "features": ((own.get("coverage") or {}).get("features")
                                     if old_complete else new_cov.get("features")),
                        "missing": ((own.get("coverage") or {}).get("missing")
                                    if old_complete else new_cov.get("missing")),
                    },
                    "access_rank": max(
                        [r for r in (own.get("access_rank"), new_rank) if r is not None],
                        default=None),
                    "expires_at": body.get("p_expires_at"),
                    "has_refresh_token": body.get("p_has_refresh_token"),
                    "revoked": False, "revoked_at": None, "updated_at": _now(),
                    "last_failed_at": None, "last_error": None, "stale_notified_at": None,
                })
                action = "refreshed"
            _log(action)
            return stake_id
