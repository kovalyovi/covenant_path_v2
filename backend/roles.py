"""
Auto-provision user_roles from LCR callings — the master plan's "permissions rebuilt
from callings, no manual role assignment."

For a synced stake we read the leadership directory (who holds each calling), keep only
callings that actually grant covenant-path data access (per the access matrix), and
map each to a role + scope:
  - a STAKE-level calling  -> role 'stake_leader', unit_id NULL  (sees the whole stake)
  - a WARD/branch calling   -> role 'ward_leader',  unit_id = their unit (sees that unit)

Rows are keyed by lcr_person_uuid (the viewer binds auth_id on first login). We UPSERT
the fresh set (preserving any existing auth_id binding) and DELETE rows for this stake
whose calling went away — i.e. a clean rebuild that also revokes released leaders.
"""

from __future__ import annotations

from lcr_client import leadership
from lcr_client.access import fetch_access_matrix
from lcr_client.logging_setup import get_logger

logger = get_logger()

# a calling is stake-scoped if its name starts with one of these (else ward/branch).
_STAKE_PREFIXES = ("Stake", "District", "Mission", "Area")

# "Can see covenant-path member data" = the calling is granted ANY of the CORE data features
# (not just the narrow member-profiles view). Gating on member-profiles alone wrongly locked out
# Stake Clerks / High Councilors, who hold progress-record + member-list access. Union these.
_ACCESS_FEATURES = (
    "menu.progress.record",        # the new-member / covenant-path list per unit (the core data)
    "menu.member.list",            # the roster + birth dates
    "menu.view.member.profiles",   # the detailed member profile
)

# Explicit safety net (reviewable): stake-level stewardship callings ALWAYS get data access even
# if the LCR menu matrix is incomplete — clerks, executive secretaries, the stake presidency, and
# high councilors have responsibility over every member in the stake.
_ALWAYS_ALLOWED_CALLINGS = (
    "Stake President", "Stake Presidency", "Counselor in the Stake Presidency",
    "Stake Clerk", "Stake Assistant Clerk", "Stake Executive Secretary",
    "Stake Assistant Executive Secretary", "High Council",
)


def _calling_always_allowed(calling: str | None) -> bool:
    c = calling or ""
    return any(k in c for k in _ALWAYS_ALLOWED_CALLINGS)


def _positions(objs) -> list[dict]:
    """All active leadership positions: {person_uuid, name, unit_name, role_id, calling}."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            pt = o.get("positionType")
            person = o.get("person")
            if isinstance(pt, dict) and isinstance(person, dict) and \
                    o.get("positionStatus") == "ACTIVE_POSITION":
                out.append({
                    "person_uuid": person.get("uuid"),
                    "name": person.get("name"),
                    "unit_name": person.get("currentUnitName"),
                    "role_id": pt.get("id"),
                    "calling": pt.get("name"),
                })
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(objs)
    return out


def _ward_positions(orgs_data: dict) -> list[dict]:
    """Active leadership callings from a unit's /mlt/api/orgs (positions -> person).

    Each position is {person:{uuid,name,currentUnitName}, positionType:{id,name,leadership},
    positionStatus}. We keep ACTIVE ones with a real person; the access matrix decides which
    callings actually grant member-data visibility (same gate as stake leaders)."""
    out: list[dict] = []

    def walk(orgs):
        for org in orgs or []:
            for p in (org.get("positions") or []):
                pt = p.get("positionType") or {}
                per = p.get("person") or {}
                if p.get("positionStatus") == "ACTIVE_POSITION" and per.get("uuid") and pt.get("id"):
                    out.append({
                        "person_uuid": per.get("uuid"),
                        "name": per.get("name"),
                        "unit_name": per.get("currentUnitName"),
                        "role_id": pt.get("id"),
                        "calling": pt.get("name"),
                    })
            walk(org.get("children"))

    walk(orgs_data.get("unitOrgs"))
    return out


def _email_by_uuid(client) -> dict[str, str]:
    """personUuid -> email across the stake's units (for matching app logins to roles)."""
    out: dict[str, str] = {}
    try:
        for u in client.user_context().child_units:
            if not u.unit_number:
                continue
            for m in client.member_list(u.unit_number):
                pu = m.raw.get("personUuid") or m.raw.get("uuid")
                em = m.raw.get("email") or m.raw.get("emailAddress")
                if pu and em:
                    out[pu] = em
    except Exception as exc:  # noqa: BLE001
        logger.warning("email enrichment skipped: %s", exc)
    return out


def _load_overrides(conn) -> list:
    """Admin-added calling→access overrides (#3c, table calling_access_overrides). Returns
    [(match_lower, grants_access)]. Best-effort: a missing table / read error → no overrides."""
    try:
        with conn.cursor() as cur:
            cur.execute("select lower(calling_match), grants_access from calling_access_overrides")
            return cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.debug("calling overrides unavailable: %s", exc)
        return []


def _audit_access(conn, stake_id, stake_unit, granted, revoked) -> None:
    """Persist who GAINED / LOST member-data access this run → access_audit (admin-only, migration
    0034) + a PII-safe Axiom count event. This is the over/under-visibility trail: an unexpected
    grant or a wrongly-revoked leader becomes queryable. Best-effort — never fail provisioning over
    the audit."""
    if not granted and not revoked:
        return
    try:
        from backend import observability as obs
        ins = ("insert into access_audit (stake_id, stake_unit, action, role, unit_id, person_uuid,"
               " name, email, calling, source) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'provision')")
        with conn.cursor() as cur:
            for row in granted:   # fresh value: (stake_id, unit_id, role, person_uuid, name, calling, email)
                cur.execute(ins, (stake_id, stake_unit, "granted", row[2], row[1], row[3],
                                  row[4], row[6], row[5]))
            for r in revoked:     # delete RETURNING: (role, unit_id, person_uuid, calling_name, email)
                cur.execute(ins, (stake_id, stake_unit, "revoked", r[0], r[1], r[2],
                                  None, r[4], r[3]))
        conn.commit()
        obs.event("access.change", stake=stake_unit, count=len(granted) + len(revoked),
                  status="ok", granted=len(granted), revoked=len(revoked))
        logger.info("access audit: +%d granted / -%d revoked (stake %s)",
                    len(granted), len(revoked), stake_unit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("access audit skipped (non-fatal): %s", exc)


def provision_roles(conn, client, stake_id: str, unit_id_by_name: dict[str, str]) -> dict:
    """Rebuild user_roles for one stake from its leadership directory. Returns counts."""
    matrix = fetch_access_matrix(client.session)
    allowed = set()  # role ids granted ANY core covenant-path data feature
    for _feature in _ACCESS_FEATURES:
        allowed |= set(matrix.feature_roles(_feature))
    email_by_uuid = _email_by_uuid(client)
    overrides = _load_overrides(conn)  # admin-added calling→access mappings (#3c)

    def _can_see(p: dict) -> bool:
        """A calling can view member data if its role is in the matrix union, it's a stake-level
        stewardship calling on the always-allowed list, OR an admin added a matching access override
        (#3c) — and it has a real person."""
        if not p.get("person_uuid"):
            return False
        calling = p.get("calling") or ""
        if p["role_id"] in allowed or _calling_always_allowed(calling):
            return True
        cl = calling.lower()
        return any(grants and m in cl for m, grants in overrides)

    fresh = {}  # provision-key -> row, dedup
    ctx = client.user_context()

    # Stake leaders from the STABLE /mlt/api/orgs on the stake unit (same clean JSON endpoint
    # wards use) — no rotating server-action id to go stale. Fall back to the leadership
    # directory action only if orgs returns nothing. We keep stake-prefixed callings (Stake
    # Presidency / clerks / stake auxiliaries); ward callings come from the per-unit loop below.
    stake_positions: list[dict] = []
    try:
        stake_positions = [p for p in _ward_positions(client.org_callings(ctx.unit_number))
                           if (p["calling"] or "").startswith(_STAKE_PREFIXES)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("stake org callings unavailable: %s", exc)
    if not stake_positions:
        try:
            stake_positions = [p for p in _positions(leadership.fetch_leadership(client.session))
                               if (p["calling"] or "").startswith(_STAKE_PREFIXES)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("stake leadership fallback failed: %s", exc)
    # If BOTH sources come back empty we must NOT treat that as "every stake leader was
    # released" — that once revoked everyone's stake access. Gate the revoke on stake_ok.
    stake_ok = len(stake_positions) > 0
    logger.info("stake positions found: %d", len(stake_positions))
    for p in stake_positions:
        if not _can_see(p):
            continue
        key = ("stake_leader", None, p["person_uuid"])
        fresh[key] = (stake_id, None, "stake_leader", p["person_uuid"], p["name"], p["calling"],
                      email_by_uuid.get(p["person_uuid"]))

    # ward leaders: the stake leadership directory has no per-ward bishoprics, so pull each
    # ward/branch's filled callings from /mlt/api/orgs (clean JSON, pure HTTP). A calling that
    # grants member-data access -> ward_leader scoped to that unit. One bad unit is skipped.
    ward_n_found = 0
    for u in client.user_context().child_units:
        if not u.unit_number or u.type not in ("WARD", "BRANCH"):
            continue
        unit_id = unit_id_by_name.get(u.name)
        if unit_id is None:
            continue
        try:
            positions = _ward_positions(client.org_callings(u.unit_number))
        except Exception as exc:  # noqa: BLE001 — never fail provisioning over one unit
            logger.warning("ward callings unavailable for %s (%s): %s", u.name, u.unit_number, exc)
            continue
        for p in positions:
            if not _can_see(p):
                continue
            key = ("ward_leader", unit_id, p["person_uuid"])
            fresh[key] = (stake_id, unit_id, "ward_leader", p["person_uuid"], p["name"],
                          p["calling"], email_by_uuid.get(p["person_uuid"]))
            ward_n_found += 1
    ward_ok = ward_n_found > 0
    logger.info("ward-leader positions found across units: %d", ward_n_found)

    with conn.cursor() as cur:
        # Snapshot existing calling-derived roles BEFORE the upsert so we can audit who NEWLY gains
        # member-data access this run (the over/under-visibility trail).
        cur.execute("select role, unit_id::text, lcr_person_uuid from user_roles "
                    "where stake_id=%s and lcr_person_uuid is not null", (stake_id,))
        existing_keys = {(r[0], r[1], r[2]) for r in cur.fetchall()}
        for row in fresh.values():
            # auth_id = LCR person uuid (login via Church identity is auto-scoped); email
            # lets a Supabase-Auth login (magic-link/Google) match a role by verified email.
            cur.execute("""
                insert into user_roles (stake_id, unit_id, role, lcr_person_uuid, auth_id, calling_name, email)
                values (%s,%s,%s,%s, nullif(%s,'')::uuid, %s, %s)
                on conflict (stake_id, coalesce(unit_id,'00000000-0000-0000-0000-000000000000'::uuid),
                             role, coalesce(lcr_person_uuid, lower(email), ''))
                do update set calling_name=excluded.calling_name, auth_id=excluded.auth_id,
                              email=coalesce(excluded.email, user_roles.email)
            """, (row[0], row[1], row[2], row[3], row[3], row[5], row[6]))
        # Revoke released leaders (calling-derived rows only — email/manual grants have a NULL
        # lcr_person_uuid and are preserved). Crucially, only revoke a role TYPE if we actually
        # got its directory this run, so an empty/failed stake or ward fetch can't wipe access.
        # RETURNING captures WHO lost access (for the audit).
        keep = [r[3] for r in fresh.values()]
        cur.execute("""delete from user_roles where stake_id=%s
                       and lcr_person_uuid is not null
                       and lcr_person_uuid <> all(%s)
                       and ((role = 'stake_leader' and %s) or (role = 'ward_leader' and %s))
                       returning role, unit_id::text, lcr_person_uuid, calling_name, email""",
                    (stake_id, keep or [""], stake_ok, ward_ok))
        revoked_rows = cur.fetchall()
        removed = len(revoked_rows)
    conn.commit()
    # Access-visibility audit: who GAINED / LOST member-data access this run. Granted = roles present
    # now that weren't before this run (compare on (role, unit_id-as-text, person_uuid)).
    granted = [r for k, r in fresh.items()
               if (k[0], (str(k[1]) if k[1] is not None else None), k[2]) not in existing_keys]
    _audit_access(conn, stake_id, ctx.unit_number, granted, revoked_rows)
    stake_n = sum(1 for r in fresh.values() if r[2] == "stake_leader")
    ward_n = len(fresh) - stake_n
    logger.info("provisioned roles for stake %s: %d stake_leader, %d ward_leader, %d revoked",
                stake_id, stake_n, ward_n, removed)
    return {"stake_leader": stake_n, "ward_leader": ward_n, "revoked": removed}
