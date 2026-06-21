"""
In-memory PostgREST-ish engine for the broker's Supabase REST calls.

Implements ONLY what backend/auth_broker actually sends (admin.py / enroll.py /
identity_cache.py / session_mint.py / app.py):
  - filters: eq. / neq. / is.null / not.is.null / in.(...) / gt|gte|lt|lte.
  - select projection, including the stakes -> stake_credentials embed. PostgREST returns a
    TO-ONE embed as a JSON OBJECT (or null) — the exact shape bug 2026-06-09 was about — so
    the relationship map marks it to_one and this engine reproduces that.
  - order=col.asc|desc[.nullslast], limit/offset, Range header, Prefer: count=exact
    (Content-Range "start-end/total"), return=representation|minimal,
    resolution=merge-duplicates (+ on_conflict).
  - rpc/enroll_stake_credential replicating migration 0041's upsert WHERE arms faithfully.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

RESERVED_PARAMS = {"select", "order", "limit", "offset", "on_conflict", "apikey", "columns"}

# parent table -> {embed name -> (parent key, child key, to_one)}
RELATIONSHIPS = {
    "stakes": {"stake_credentials": ("id", "stake_id", True)},
}

# upsert key when on_conflict isn't sent (PostgREST defaults to the primary key)
DEFAULT_PK = {
    "church_identities": "username",
    "app_admins": "email",
    "stake_settings": "stake_id",
    "stake_credentials": "stake_id",
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

    # ---- lifecycle -----------------------------------------------------------------
    def reset(self) -> None:
        with self.lock:
            self.tables.clear()
            self.users.clear()
            self.otps.clear()

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

    # ---- the 0055 enroll RPC ------------------------------------------------------------
    def rpc_enroll_stake_credential(self, body: dict) -> str:
        """Replicates backend/migrations/0055_credential_most_elevated_wins.sql:

          insert into stakes ... on conflict (unit_number) do update set name -> stake id
          insert into stake_credentials ... on conflict (stake_id) do update set
              <all enroll columns>, revoked=false, revoked_at=null, updated_at=now(),
              last_failed_at=null, last_error=null, stale_notified_at=null
          WHERE lower(existing.principal_email) = lower(excluded.principal_email)  -- same leader refresh
             OR existing.revoked                                                   -- dead -> anyone
             OR excluded.access_rank >= coalesce(existing.access_rank, -1)         -- most-elevated-wins

        STRICT most-elevated-wins: a LOWER-access leader can no longer clobber a higher one via the old
        incomplete/last_failed_at hatches (the Raleigh/Ricky incident). One stake_credential_history row
        is appended per attempt (enrolled | refreshed | took_over | blocked_downgrade).
        (A false WHERE leaves the existing row untouched; the stake id is returned either way.)
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

            new = {
                "stake_id": stake_id,
                "principal_name": body.get("p_principal_name"),
                "principal_email": (body.get("p_principal_email") or "").lower(),
                "granting_role_ids": body.get("p_granting_role_ids"),
                "credential_enc": body.get("p_credential_enc"),
                "coverage": body.get("p_coverage"),
                "access_rank": body.get("p_access_rank"),
                "expires_at": body.get("p_expires_at"),
                "has_refresh_token": body.get("p_has_refresh_token"),
                "revoked": False,
                "revoked_at": None,
                "updated_at": _now(),
                "last_failed_at": None,
                "last_error": None,
                "stale_notified_at": None,
            }
            creds = self.tables.setdefault("stake_credentials", [])
            history = self.tables.setdefault("stake_credential_history", [])
            in_email = new["principal_email"]

            def _log(action, prior_email, prior_rank):
                history.append({
                    "id": str(uuid.uuid4()), "stake_id": stake_id, "action": action,
                    "principal_name": new.get("principal_name"), "principal_email": in_email,
                    "access_rank": new.get("access_rank"),
                    "coverage_complete": bool((new.get("coverage") or {}).get("complete")),
                    "has_refresh_token": new.get("has_refresh_token"),
                    "prior_principal_email": prior_email, "prior_access_rank": prior_rank,
                    "created_at": _now()})

            existing = next((c for c in creds
                             if _as_str(c.get("stake_id")) == _as_str(stake_id)), None)
            if existing is None:
                creds.append({"id": str(uuid.uuid4()), **new})
                _log("enrolled", None, None)
                return stake_id

            prior_email = (existing.get("principal_email") or "").lower()
            prior_rank = existing.get("access_rank")
            new_rank = new.get("access_rank")
            old_rank = existing.get("access_rank")
            # STRICT most-elevated-wins (0055): same leader refresh, OR existing revoked, OR incoming
            # rank >= existing. The incomplete/last_failed_at hatches are GONE — a lower-access leader
            # can no longer clobber a higher one. `null >= x` is falsy (rank-less incoming can't win).
            replaced = (
                in_email == prior_email
                or bool(existing.get("revoked"))
                or (new_rank is not None and new_rank >= (old_rank if old_rank is not None else -1))
            )
            if replaced:
                existing.update(new)
                action = ("refreshed" if in_email == prior_email
                          else "took_over" if prior_email else "enrolled")
            else:
                action = "blocked_downgrade"
            _log(action, prior_email or None, prior_rank)
            return stake_id
