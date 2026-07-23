"""
Postgres/Supabase access for the covenant-path platform.

Connects via SUPABASE_DB_URL (the postgres role → bypasses RLS, so the scraper can
write freely while app readers stay RLS-scoped). Provides migration application and
idempotent upserts for stakes / units / members.

Env:
  SUPABASE_DB_URL = postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres
"""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from lcr_client.logging_setup import get_logger

logger = get_logger()
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# the 13 covenant-path fields + extras we persist (member dict key -> column)
_MEMBER_COLUMNS = [
    "person_uuid", "name", "unit_name", "baptism_date", "birth_date", "friends", "friends_count",
    "aaronic_priesthood", "melchizedek_priesthood", "calling",
    "ministering_brothers_sisters", "ministering_assignment", "temple_recommend",
    "patriarchal_blessing", "living_ordinance", "family_name_prepared", "first_temple_visit",
    "membership_duration", "sex",
    "kind", "baptism_goal_date",  # new_member|investigator|returning + planned baptism date
    "details",  # jsonb — the rich progress subtree (dict; wrapped as Json on write)
]

# Profile-/access-gated columns: a partial, no-profile, or access-blocked scrape emits a sentinel
# ('needs-profile-api' / 'blocked: insufficient calling access') for these. On upsert we MERGE
# rather than overwrite — keep the last-good value instead of clobbering it with a sentinel (so a
# degraded run never blanks priesthood/calling/etc). The sentinel strings mirror covenant_path.report.
_GATED_COLUMNS = frozenset({
    "baptism_date", "aaronic_priesthood", "melchizedek_priesthood", "calling",
    "ministering_brothers_sisters", "ministering_assignment", "temple_recommend",
    "patriarchal_blessing", "living_ordinance", "family_name_prepared", "first_temple_visit",
})
_SENTINELS = ("needs-profile-api", "blocked: insufficient calling access")


def _scrub_sentinel(column: str, value):
    """Map a GATED column's sentinel value -> None at the write boundary, so the RAW sentinel string
    ('needs-profile-api' / 'blocked: …') is NEVER persisted (and thus never served to a client).

    The sentinel's MEANING ("don't have it this run — preserve last-good") is fully retained: writing
    None instead is what the ON CONFLICT merge already collapses the sentinel to
    (`coalesce(nullif(excluded.c, sentinel), members.c)` keys off the STORED last-good, not the incoming
    value). The gap the old code left was the *first INSERT* of a member: no conflict fires, so the raw
    `vals` landed verbatim and a brand-new / restored member with no last-good stored the literal
    sentinel forever (the leak the client showed). Converting here closes both the INSERT and UPDATE
    paths: INSERT writes NULL; UPDATE's coalesce(NULL, members.c) still preserves last-good. Non-gated
    columns and non-sentinel values pass through untouched."""
    if column in _GATED_COLUMNS and isinstance(value, str) and value in _SENTINELS:
        return None
    return value


def _merge_expr(c: str) -> str:
    """ON CONFLICT update expr: gated columns preserve last-good when the incoming value is a
    sentinel; all other columns take the fresh value. Sentinel literals are constants (safe to inline)."""
    if c == "unit_id":
        return "unit_id = excluded.unit_id"
    if c == "friends_count":
        # numeric, not a sentinel: preserve the last-good count when a run couldn't determine it
        # (incoming NULL) but accept a genuine 0 (empty friends array).
        return "friends_count = coalesce(excluded.friends_count, members.friends_count)"
    if c in _GATED_COLUMNS:
        def _strip(expr: str) -> str:
            for s in _SENTINELS:
                expr = f"nullif({expr}, '{s}')"
            return expr
        # Incoming sentinel → keep the stored last-good. BUT strip the STORED value too, so a row that
        # already holds a sentinel (one that leaked before the write-boundary scrub, or never had data)
        # self-HEALS to NULL on the next sync instead of being preserved forever. A real stored value is
        # untouched (it isn't a sentinel). Closes the "existing needs-profile-api never goes away" gap.
        return f"{c} = coalesce({_strip(f'excluded.{c}')}, {_strip(f'members.{c}')})"
    return f"{c} = excluded.{c}"


# Per-field freshness (#data-correctness): the fields whose staleness we track. A SENTINEL value (or
# None) means the endpoint didn't return it this run — keep the prior last-fetched stamp (staleness
# grows); a real value (incl. a confirmed-empty like 'No' / 0) stamps it fresh.
_FRESHNESS_FIELDS = tuple(_GATED_COLUMNS) + ("friends_count",)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field_meta(m: dict, prior: dict | None, now: str) -> dict:
    """{field: {"f": last-fetched-iso, "t": last-tried-iso}}. A failed/missing fetch bumps `t` only
    and PRESERVES the prior `f`, so the UI shows growing staleness and we never blank a value we
    didn't actually get this run. A real value (or a confirmed empty) stamps both."""
    meta = {k: dict(v) for k, v in (prior or {}).items() if isinstance(v, dict)}
    for c in _FRESHNESS_FIELDS:
        v = m.get(c)
        fetched = v is not None and not (isinstance(v, str) and v in _SENTINELS)
        entry = dict(meta.get(c) or {})
        entry["t"] = now
        if fetched:
            entry["f"] = now
        meta[c] = entry
    return meta


def db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url or "[YOUR-PASSWORD]" in url:
        raise RuntimeError(
            "SUPABASE_DB_URL not set (or still a placeholder). Put the full connection "
            "string from Supabase → Settings → Database into .env."
        )
    return url


def connect():
    from dotenv import load_dotenv
    load_dotenv()
    return psycopg2.connect(db_url())


def apply_migrations(conn, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    applied = []
    with conn.cursor() as cur:
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            logger.info("applying migration %s", sql_file.name)
            cur.execute(sql_file.read_text(encoding="utf-8"))
            applied.append(sql_file.name)
    conn.commit()
    return applied


def upsert_stake(conn, unit_number: int, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """insert into stakes (unit_number, name) values (%s, %s)
               on conflict (unit_number) do update set name = excluded.name
               returning id""", (unit_number, name))
        return cur.fetchone()[0]


def upsert_unit(conn, stake_id: str, unit_number: int, name: str, unit_type: str | None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """insert into units (stake_id, unit_number, name, unit_type)
               values (%s, %s, %s, %s)
               on conflict (unit_number) do update
                 set name = excluded.name, unit_type = excluded.unit_type, stake_id = excluded.stake_id
               returning id""", (stake_id, unit_number, name, unit_type))
        return cur.fetchone()[0]


def prune_units(conn, stake_id: str, keep_unit_numbers: list[int]) -> int:
    """Delete this stake's units whose unit_number is no longer present — i.e. wards/branches that
    left the stake in a restructuring (#2). Safe by schema: members.unit_id -> NULL (FK on delete
    set null, so those members stay, just unscoped to a unit) and any ward_leader roles for the
    removed unit cascade away. Returns rows deleted.

    GATED: the caller MUST pass the CURRENT (non-empty) unit-number list. An empty list means we
    couldn't read the stake's units this run, and pruning then would wipe every unit — so we no-op.
    Mirrors the stake_ok/ward_ok gating in roles.provision_roles."""
    if not keep_unit_numbers:
        return 0
    with conn.cursor() as cur:
        cur.execute("delete from units where stake_id=%s and unit_number <> all(%s)",
                    (stake_id, list(keep_unit_numbers)))
        removed = cur.rowcount
    conn.commit()
    return removed


def stale_first_units(conn, stake_id: str) -> list[int]:
    """This stake's unit numbers ordered OLDEST-DATA-FIRST: units with no members yet (never synced)
    come first, then by their oldest member's `updated_at`. The sync refreshes the most-stale wards
    first, so when LCR's fragile one-work cluster degrades mid-run the units left unfinished are the
    LEAST stale (they simply keep their last-good rows and retry next run). Empty when nothing's synced
    yet (the report then uses LCR's natural order)."""
    with conn.cursor() as cur:
        cur.execute(
            """select u.unit_number, min(m.updated_at) as oldest
                 from units u
                 left join members m on m.unit_id = u.id
                where u.stake_id = %s and u.unit_number is not null
             group by u.unit_number
             order by oldest asc nulls first""",
            (stake_id,))
        return [int(r[0]) for r in cur.fetchall() if r[0] is not None]


def upsert_members(conn, stake_id: str, members: list[dict],
                   unit_id_by_number: dict[int, str],
                   unit_id_by_name: dict[str, str] | None = None) -> int:
    """Idempotent upsert keyed by (stake_id, person_uuid). Returns rows written.

    unit_id resolves by unit_number first, then unit name (so reports generated before
    `unit_number` existed still map to a unit). `unit_name` column ← the report's `unit`.
    """
    unit_id_by_name = unit_id_by_name or {}
    now = _now_iso()
    # Prior per-field freshness, so a not-fetched (sentinel) field keeps its last-fetched stamp.
    with conn.cursor() as cur:
        cur.execute("select person_uuid, field_meta from members where stake_id=%s", (stake_id,))
        prior_meta = {p: (fm or {}) for p, fm in cur.fetchall()}
    rows = []
    for m in members:
        if not m.get("person_uuid"):
            continue
        unit_name = m.get("unit") or m.get("unit_name")
        unit_id = unit_id_by_number.get(m.get("unit_number")) or unit_id_by_name.get(unit_name)
        vals = []
        for c in _MEMBER_COLUMNS:
            if c == "unit_name":
                vals.append(unit_name)
            elif c == "details":
                v = m.get("details")
                vals.append(psycopg2.extras.Json(v) if v is not None else None)
            else:
                # Scrub the raw sentinel -> NULL at the write boundary so a member with no last-good
                # (a brand-new / restored row, where ON CONFLICT never fires) can never persist the
                # literal 'needs-profile-api'/'blocked: …' string for the client to read. The
                # preserve-last-good meaning is unchanged (the on-conflict merge keys off members.c).
                vals.append(_scrub_sentinel(c, m.get(c)))
        # field_meta reads the ORIGINAL `m` (with sentinels intact) so a not-fetched field still leaves
        # its last-fetched `f` stamp untouched (staleness keeps growing) — only the stored VALUE is
        # scrubbed to NULL, not the freshness signal.
        fm = _field_meta(m, prior_meta.get(m.get("person_uuid")), now)
        rows.append((stake_id, unit_id, *vals, psycopg2.extras.Json(fm)))
    if not rows:
        return 0
    cols = "stake_id, unit_id, " + ", ".join(_MEMBER_COLUMNS) + ", field_meta"
    # on conflict, refresh everything except the conflict key (person_uuid); unit_id + field_meta
    # aren't in _MEMBER_COLUMNS so add them once. field_meta is the full merge (computed in Python).
    update_cols = ["unit_id"] + [c for c in _MEMBER_COLUMNS if c != "person_uuid"]
    updates = ", ".join(_merge_expr(c) for c in update_cols) + ", field_meta = excluded.field_meta"
    sql = (f"insert into members ({cols}) values %s "
           f"on conflict (stake_id, person_uuid) do update set {updates}")
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)


def adopt_orphan_notes(conn, stake_id: str) -> int:
    """Attach PENDING partner notes (member_comments with a NULL stake_id) to this stake once their
    person is synced. The partner-notes lane lets a leader record notes on someone not yet in `members`
    (e.g. dropped from a sync while the operator's calling changed) — those land stake-less and invisible
    to RLS. Here, after upsert, any pending comment whose member_person_uuid now matches a member in this
    stake inherits that member's stake_id/unit_id, becoming visible to the right leaders. Returns rows
    adopted. (Only member_comments can be pending; member_notes always references a real member.)"""
    with conn.cursor() as cur:
        cur.execute(
            """update member_comments mc
                  set stake_id = m.stake_id, unit_id = m.unit_id
                 from members m
                where m.stake_id = %s
                  and m.person_uuid = mc.member_person_uuid
                  and mc.stake_id is null""",
            (stake_id,))
        adopted = cur.rowcount
    conn.commit()
    return adopted


def _normalize_name(name: str | None) -> str:
    """Python twin of the web's logic/manualMembers.ts `normalizeName` (kept in lockstep — tests pin the
    parity): lowercased, diacritics folded (é→e, ñ→n), commas/periods → spaces, apostrophes/hyphens
    dropped ("O'Brien"→"obrien", "Mary-Jane"→"maryjane"), any remaining non-alphanumerics stripped, then
    the tokens SORTED so "Smith, John" == "John Smith" (order-insensitive)."""
    s = (name or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # drop combining marks
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"['’-]", "", s)          # apostrophes (straight + right-single) and hyphens
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(sorted(t for t in s.split() if t))


def _same_unit(a_unit_id, a_unit_name, b_unit_id, b_unit_name) -> bool:
    """Same unit? Prefer unit_id when both sides have it; else fall back to unit_name (case-insensitive).
    Mirrors the web's `sameUnit`."""
    if a_unit_id and b_unit_id:
        return str(a_unit_id) == str(b_unit_id)
    an = (a_unit_name or "").strip().lower()
    bn = (b_unit_name or "").strip().lower()
    return bool(an) and an == bn


def _merged_note(existing: str | None, preserved: str | None) -> str:
    """Combine a preserved manual note with the member's existing note without ever losing text — mirrors
    the web's `mergedNote` (append under a blank-line divider; idempotent if already contained)."""
    a = (existing or "").strip()
    b = (preserved or "").strip()
    if not b:
        return a
    if not a:
        return b
    if b in a:
        return a
    return f"{a}\n\n{b}"


def merge_manual_members(conn, stake_id: str) -> int:
    """Server-side dedup: when the daily sync brings a REAL member that matches a leader's manually-added
    person (by normalized name WITHIN THE SAME UNIT), auto-merge — preserve the manual person's notes onto
    the real member (member_notes) and soft-mark the manual row merged (merged_at + merged_into_uuid) so it
    stops showing but the link/notes survive. Exact-name-in-unit only (the same rule the client's Merge
    suggestion uses); the client still offers a manual Merge for near-but-inexact matches. Returns rows
    merged. Runs as the postgres role (RLS-bypassing), same as the rest of the sync."""
    with conn.cursor() as cur:
        cur.execute("select id, name, unit_id, unit_name, custom_notes from manual_members "
                    "where stake_id=%s and merged_at is null", (stake_id,))
        manuals = cur.fetchall()
        if not manuals:
            return 0
        cur.execute("select person_uuid, name, unit_id, unit_name from members where stake_id=%s",
                    (stake_id,))
        members = cur.fetchall()

    merged = 0
    for mid, mname, m_unit_id, m_unit_name, notes in manuals:
        want = _normalize_name(mname)
        if not want:
            continue
        match = next(((puid, unit_id) for puid, name, unit_id, unit_name in members
                      if puid and _same_unit(m_unit_id, m_unit_name, unit_id, unit_name)
                      and _normalize_name(name) == want), None)
        if not match:
            continue
        puid, unit_id = match
        with conn.cursor() as cur:
            if (notes or "").strip():
                cur.execute("select note from member_notes where stake_id=%s and member_person_uuid=%s",
                            (stake_id, puid))
                row = cur.fetchone()
                combined = _merged_note(row[0] if row else "", notes)
                cur.execute(
                    """insert into member_notes
                         (stake_id, unit_id, member_person_uuid, note, updated_by, updated_at)
                       values (%s, %s, %s, %s, 'manual-merge', now())
                       on conflict (stake_id, member_person_uuid)
                       do update set note = excluded.note, updated_by = excluded.updated_by,
                                     updated_at = now()""",
                    (stake_id, unit_id, puid, combined))
            cur.execute("update manual_members set merged_at = now(), merged_into_uuid = %s where id = %s",
                        (puid, mid))
        merged += 1
    conn.commit()
    return merged


def count_reconcile_candidates(conn, stake_id: str, present_uuids: list[str],
                               keep_unit_ids: list[str], include_orphans: bool) -> int:
    """How many members reconcile_members WOULD delete — same predicate, count only. Lets the sync
    DEFER deletions on a degraded run: LCR 500s can return thinner-but-200 rosters, so a burst of
    'departures' during an LCR outage is usually degraded data, not real moves (the 2026-06-09 case:
    10 'departed' while 2 units were 500-ing)."""
    if not present_uuids or not keep_unit_ids:
        return 0
    unit_clause = "unit_id::text = any(%s)"
    if include_orphans:
        unit_clause = f"({unit_clause} or unit_id is null)"
    sql = f"select count(*) from members where stake_id = %s and person_uuid <> all(%s) and {unit_clause}"
    with conn.cursor() as cur:
        cur.execute(sql, (stake_id, list(present_uuids), [str(u) for u in keep_unit_ids]))
        return cur.fetchone()[0]


def reconcile_members(conn, stake_id: str, present_uuids: list[str],
                      keep_unit_ids: list[str], include_orphans: bool) -> int:
    """Hard-delete people who left: members no longer in LCR for a unit that scraped CLEANLY this
    run (moved out, record removed, deceased). A member absent from this run's report whose unit is
    in `keep_unit_ids` — the units confirmed scraped OK — is deleted; with `include_orphans`, members
    orphaned to unit_id NULL (their ward was removed by prune_units) are deleted too.

    Members of units that FAILED to scrape this run are NOT in keep_unit_ids, so they're preserved —
    a transient LCR failure can never wipe a roster. GATED: both lists must be non-empty or it
    no-ops (an empty report / all-units-failed run never deletes), mirroring prune_units. Returns
    rows deleted."""
    if not present_uuids or not keep_unit_ids:
        return 0
    unit_clause = "unit_id::text = any(%s)"
    if include_orphans:
        unit_clause = f"({unit_clause} or unit_id is null)"
    sql = f"delete from members where stake_id = %s and person_uuid <> all(%s) and {unit_clause}"
    with conn.cursor() as cur:
        cur.execute(sql, (stake_id, list(present_uuids), [str(u) for u in keep_unit_ids]))
        removed = cur.rowcount
    conn.commit()
    return removed


def touch_stake_synced(conn, stake_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("update stakes set last_synced_at = now() where id = %s", (stake_id,))
    conn.commit()


def update_stake_kpis(conn, stake_id: str, kpis: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("update stakes set kpis = %s, kpis_updated_at = now() where id = %s",
                    (psycopg2.extras.Json(kpis), stake_id))
    conn.commit()


def _iter_missionaries(comp):
    """Yield each person dict of a companionship entry — the new `{missionaries:[...]}` shape or a
    legacy flat record (one missionary per entry)."""
    if not isinstance(comp, dict):
        return
    people = comp.get("missionaries") if isinstance(comp.get("missionaries"), list) else [comp]
    for m in people:
        if isinstance(m, dict):
            yield m


def carry_forward_missionary_photos(prev: dict, new: dict) -> None:
    """Mutate `new` (the freshly-built roster) so each missionary KEEPS the photo_url it had in `prev`.
    The bulk companionships carry no avatar — those are attached only by the periodic `--photos` bundle
    pass (attach_missionary_photos). Without this carry-forward every plain daily sync (no `--photos`)
    would rebuild the roster and WIPE the avatars, so missionary pictures vanished after a nightly run
    even though member photos (stored on the member row) survived. Tolerant of both roster shapes."""
    photos: dict[str, str] = {}
    for comps in (prev.values() if isinstance(prev, dict) else []):
        for comp in (comps or []):
            for m in _iter_missionaries(comp):
                if m.get("uuid") and m.get("photo_url"):
                    photos[m["uuid"]] = m["photo_url"]
    if not photos:
        return
    for comps in (new.values() if isinstance(new, dict) else []):
        for comp in (comps or []):
            for m in _iter_missionaries(comp):
                if not m.get("photo_url") and m.get("uuid") in photos:
                    m["photo_url"] = photos[m["uuid"]]


def update_stake_missionaries(conn, stake_id: str, by_unit: dict) -> None:
    """Store the per-ward full-time-missionary roster (#29): {unit_name: [{name,phone,email}, ...]}.
    Carries forward any avatar already attached so a plain sync doesn't wipe missionary photos."""
    with conn.cursor() as cur:
        cur.execute("select missionaries from stakes where id=%s", (stake_id,))
        row = cur.fetchone()
    carry_forward_missionary_photos((row[0] if row else None) or {}, by_unit)
    with conn.cursor() as cur:
        cur.execute("update stakes set missionaries = %s where id = %s",
                    (psycopg2.extras.Json(by_unit), stake_id))
    conn.commit()


def update_unit_staffing(conn, unit_id: str, roster: list) -> None:
    """Store a unit's leadership roster on units.staffing (#12, migration 0053):
    [{position, person, person_uuid, set_apart}]. RLS-scoped per unit by units_select."""
    with conn.cursor() as cur:
        cur.execute("update units set staffing = %s where id = %s",
                    (psycopg2.extras.Json(roster), unit_id))
    conn.commit()


def attach_missionary_photos(conn, stake_id: str, uuid_to_url: dict) -> None:
    """Set photo_url on each stored missionary (in stakes.missionaries companionships) whose uuid has an
    uploaded avatar (#3a/#11). Best-effort; tolerates the new companionship shape + the old flat shape."""
    if not uuid_to_url:
        return
    with conn.cursor() as cur:
        cur.execute("select missionaries from stakes where id=%s", (stake_id,))
        row = cur.fetchone()
        roster = (row[0] if row else None) or {}
        changed = False
        for comps in roster.values():
            for comp in (comps or []):
                for m in _iter_missionaries(comp):
                    if m.get("uuid") in uuid_to_url:
                        m["photo_url"] = uuid_to_url[m["uuid"]]
                        changed = True
        if changed:
            cur.execute("update stakes set missionaries=%s where id=%s",
                        (psycopg2.extras.Json(roster), stake_id))
    conn.commit()


def set_sync_state(conn, stake_id: str, state: str) -> None:
    """Coarse live status for the app banner. 'running' stamps sync_started_at; any other
    state ('done'/'error') just updates the flag."""
    with conn.cursor() as cur:
        if state == "running":
            cur.execute(
                "update stakes set sync_state=%s, sync_started_at=now() where id=%s",
                (state, stake_id))
        else:
            cur.execute("update stakes set sync_state=%s where id=%s", (state, stake_id))
    conn.commit()


def insert_diagnostics(conn, stake_id: str | None, kind: str, payload: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("insert into sync_diagnostics (stake_id, kind, payload) values (%s,%s,%s)",
                    (stake_id, kind, psycopg2.extras.Json(payload)))
    conn.commit()


def field_staleness_summary(conn, stake_id: str) -> dict:
    """Per-field freshness rollup for diagnostics (#robust-logging): how many members' last-fetched is
    fresh / warn (>3d) / error (>7d) / never, from members.field_meta — so "what isn't being fetched"
    is visible at a glance."""
    now = datetime.now(timezone.utc)
    out: dict = {}
    with conn.cursor() as cur:
        cur.execute("select field_meta from members where stake_id=%s", (stake_id,))
        for (fm,) in cur.fetchall():
            for field, meta in (fm or {}).items():
                s = out.setdefault(field, {"fresh": 0, "warn": 0, "error": 0, "never": 0})
                f = (meta or {}).get("f")
                try:
                    age = (now - datetime.fromisoformat(f)).days if f else None
                except Exception:  # noqa: BLE001
                    age = None
                if age is None:
                    s["never"] += 1
                elif age > 7:
                    s["error"] += 1
                elif age > 3:
                    s["warn"] += 1
                else:
                    s["fresh"] += 1
    return out
