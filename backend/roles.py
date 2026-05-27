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
    for p in _positions(leadership.fetch_leadership(client.session)):
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
        # revoke roles whose calling disappeared (rebuild), but keep this stake's rows only
        keep = [r[3] for r in fresh.values()]
        cur.execute("""delete from user_roles where stake_id=%s
                       and lcr_person_uuid is not null
                       and lcr_person_uuid <> all(%s)""", (stake_id, keep or [""]))
        removed = cur.rowcount
    conn.commit()
    stake_n = sum(1 for r in fresh.values() if r[2] == "stake_leader")
    ward_n = len(fresh) - stake_n
    logger.info("provisioned roles for stake %s: %d stake_leader, %d ward_leader, %d revoked",
                stake_id, stake_n, ward_n, removed)
    return {"stake_leader": stake_n, "ward_leader": ward_n, "revoked": removed}
