"""
Per-stake credential store in Supabase (the cloud equivalent of token_store.py).

The daily multi-stake job pulls each stake's encrypted session from the
`stake_credentials` table (instead of a local file), so any onboarded stake syncs
from CI. The secret blob (session cookies / token) is Fernet-encrypted with the same
CP_TOKEN_KEY as the local store; the table is RLS-locked + ungranted so only the
postgres role (scraper) can read it.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet

from lcr_client.logging_setup import get_logger
from lcr_client.token_store import _load_key

logger = get_logger()


def _fernet() -> Fernet:
    return Fernet(_load_key())


def save_credential(conn, stake_id: str, grant: dict) -> None:
    """Encrypt + store a stake's delegated session. `grant` like token_store's record."""
    blob = _fernet().encrypt(json.dumps({
        "cookies": grant.get("cookies"),
        "refresh_token": grant.get("refresh_token"),
    }).encode("utf-8")).decode("ascii")
    with conn.cursor() as cur:
        cur.execute("""
            insert into stake_credentials
                (stake_id, principal_name, granting_role_ids, credential_enc, expires_at, revoked, updated_at)
            values (%s,%s,%s,%s,%s,false, now())
            on conflict (stake_id) do update set
                principal_name=excluded.principal_name,
                granting_role_ids=excluded.granting_role_ids,
                credential_enc=excluded.credential_enc,
                expires_at=excluded.expires_at,
                revoked=false, revoked_at=null, updated_at=now()
        """, (stake_id, (grant.get("principal") or {}).get("name") if isinstance(grant.get("principal"), dict)
              else grant.get("principal_name"),
              grant.get("granting_role_ids"), blob, grant.get("expires_at")))
    conn.commit()
    logger.info("stored stake credential for %s", stake_id)


def get_credential(conn, stake_id: str) -> dict | None:
    """Decrypt + return a stake's credential ({cookies, refresh_token, ...}) or None."""
    with conn.cursor() as cur:
        cur.execute("""select principal_name, granting_role_ids, credential_enc, expires_at, revoked
                       from stake_credentials where stake_id=%s""", (stake_id,))
        row = cur.fetchone()
    if not row:
        return None
    secret = json.loads(_fernet().decrypt(row[2].encode("ascii")).decode("utf-8"))
    return {"principal_name": row[0], "granting_role_ids": row[1], "expires_at": row[3],
            "revoked": row[4], **secret}


def list_active_stakes(conn) -> list[dict]:
    """Stakes with a non-revoked credential, for the daily multi-stake loop."""
    with conn.cursor() as cur:
        cur.execute("""select c.stake_id, s.unit_number, s.name
                       from stake_credentials c join stakes s on s.id=c.stake_id
                       where not c.revoked""")
        return [{"stake_id": r[0], "unit_number": r[1], "name": r[2]} for r in cur.fetchall()]


def revoke(conn, stake_id: str, reason: str = "manual") -> None:
    with conn.cursor() as cur:
        cur.execute("""update stake_credentials set revoked=true, revoked_at=now(),
                       audit = audit || %s::jsonb where stake_id=%s""",
                    (json.dumps([{"event": "revoked", "reason": reason}]), stake_id))
    conn.commit()
    logger.warning("revoked stake credential %s (%s)", stake_id, reason)
