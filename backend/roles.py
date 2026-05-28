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
# the feature whose role list defines "can see covenant-path member data".
_ACCESS_FEATURE = "menu.view.member.profiles"


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


def provision_roles(conn, client, stake_id: str, unit_id_by_name: dict[str, str]) -> dict:
    """Rebuild user_roles for one stake from its leadership directory. Returns counts."""
    matrix = fetch_access_matrix(client.session)
    allowed = set(matrix.feature_roles(_ACCESS_FEATURE))  # role ids with member-data access
    email_by_uuid = _email_by_uuid(client)

    fresh = {}  # provision-key -> row, dedup
    # If the stake leadership directory comes back empty/failed we must NOT treat that as
    # "every stake leader was released" — that would revoke everyone's stake access (it did
    # once). Track whether we actually got the directory and gate the revoke on it.
    try:
        stake_positions = _positions(leadership.fetch_leadership(client.session))
    except Exception as exc:  # noqa: BLE001
        logger.warning("stake leadership fetch failed: %s", exc)
        stake_positions = []
    stake_ok = len(stake_positions) > 0
    for p in stake_positions:
        if p["role_id"] not in allowed or not p["person_uuid"]:
            continue
        is_stake = (p["calling"] or "").startswith(_STAKE_PREFIXES)
        role = "stake_leader" if is_stake else "ward_leader"
        unit_id = None if is_stake else unit_id_by_name.get(p["unit_name"])
        if role == "ward_leader" and unit_id is None:
            continue  # ward calling we can't map to a known unit (e.g. a different stake)
        key = (role, unit_id, p["person_uuid"])
        fresh[key] = (stake_id, unit_id, role, p["person_uuid"], p["name"], p["calling"],
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
            if p["role_id"] not in allowed or not p["person_uuid"]:
                continue
            key = ("ward_leader", unit_id, p["person_uuid"])
            fresh[key] = (stake_id, unit_id, "ward_leader", p["person_uuid"], p["name"],
                          p["calling"], email_by_uuid.get(p["person_uuid"]))
            ward_n_found += 1
    ward_ok = ward_n_found > 0
    logger.info("ward-leader positions found across units: %d", ward_n_found)

    with conn.cursor() as cur:
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
        keep = [r[3] for r in fresh.values()]
        cur.execute("""delete from user_roles where stake_id=%s
                       and lcr_person_uuid is not null
                       and lcr_person_uuid <> all(%s)
                       and ((role = 'stake_leader' and %s) or (role = 'ward_leader' and %s))""",
                    (stake_id, keep or [""], stake_ok, ward_ok))
        removed = cur.rowcount
    conn.commit()
    stake_n = sum(1 for r in fresh.values() if r[2] == "stake_leader")
    ward_n = len(fresh) - stake_n
    logger.info("provisioned roles for stake %s: %d stake_leader, %d ward_leader, %d revoked",
                stake_id, stake_n, ward_n, removed)
    return {"stake_leader": stake_n, "ward_leader": ward_n, "revoked": removed}
