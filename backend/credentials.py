"""
Per-stake credential store in Supabase (the cloud equivalent of token_store.py).

The daily multi-stake job pulls each stake's encrypted session from the
`stake_credentials` table (instead of a local file), so any onboarded stake syncs
from CI. The secret blob (session cookies / token) is Fernet-encrypted with the same
CP_TOKEN_KEY as the local store; the table is RLS-locked + ungranted so only the
postgres role (scraper) can read it.
"""

from __future__ import annotations

import base64
import json
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lcr_client.logging_setup import get_logger
from lcr_client.token_store import _load_key

logger = get_logger()


def _fernet() -> Fernet:
    return Fernet(_load_key())


# --- envelope encryption (KMS pattern, done in-app, free) -------------------
# Each secret gets a fresh random AES-256-GCM data key; the data key is wrapped (encrypted) by
# the master CP_TOKEN_KEY (Fernet). We persist only {wrapped_key, nonce, ct} — never the plaintext
# data key. Benefits: per-credential isolation (one leak != all) + master-key rotation re-wraps
# only the tiny data keys. The master key lives solely in runtime secrets, never the DB.

def _encrypt_envelope(plaintext: bytes) -> str:
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ct = AESGCM(data_key).encrypt(nonce, plaintext, None)
    wrapped = _fernet().encrypt(data_key)
    return json.dumps({
        "v": 2,
        "wrapped_key": wrapped.decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
    })


def _decrypt_envelope(blob: str) -> bytes:
    try:
        d = json.loads(blob)
    except (ValueError, TypeError):
        d = None
    if not isinstance(d, dict) or d.get("v") != 2:
        # legacy single-key Fernet blob (pre-envelope) — still decryptable
        return _fernet().decrypt(blob.encode("ascii"))
    data_key = _fernet().decrypt(d["wrapped_key"].encode("ascii"))
    return AESGCM(data_key).decrypt(
        base64.b64decode(d["nonce"]), base64.b64decode(d["ct"]), None)


def save_credential(conn, stake_id: str, grant: dict) -> None:
    """Encrypt + store a stake's delegated session. `grant` like token_store's record, plus
    optional `coverage` (allowed-feature info) and `access_rank` for most-elevated comparison."""
    blob = _encrypt_envelope(json.dumps({
        "cookies": grant.get("cookies"),
        "refresh_token": grant.get("refresh_token"),
    }).encode("utf-8"))
    import psycopg2.extras  # lazy: keeps the broker (encrypt-only) from needing psycopg2
    coverage = grant.get("coverage")
    with conn.cursor() as cur:
        cur.execute("""
            insert into stake_credentials
                (stake_id, principal_name, granting_role_ids, credential_enc, coverage,
                 access_rank, expires_at, revoked, updated_at)
            values (%s,%s,%s,%s,%s,%s,%s,false, now())
            on conflict (stake_id) do update set
                principal_name=excluded.principal_name,
                granting_role_ids=excluded.granting_role_ids,
                credential_enc=excluded.credential_enc,
                coverage=excluded.coverage,
                access_rank=excluded.access_rank,
                expires_at=excluded.expires_at,
                revoked=false, revoked_at=null, updated_at=now()
        """, (stake_id, (grant.get("principal") or {}).get("name") if isinstance(grant.get("principal"), dict)
              else grant.get("principal_name"),
              grant.get("granting_role_ids"), blob,
              psycopg2.extras.Json(coverage) if coverage is not None else None,
              grant.get("access_rank"), grant.get("expires_at")))
    conn.commit()
    logger.info("stored stake credential for %s", stake_id)


def get_credential(conn, stake_id: str) -> dict | None:
    """Decrypt + return a stake's credential ({cookies, refresh_token, ...}) or None."""
    with conn.cursor() as cur:
        cur.execute("""select principal_name, granting_role_ids, credential_enc, expires_at,
                              revoked, coverage, access_rank
                       from stake_credentials where stake_id=%s""", (stake_id,))
        row = cur.fetchone()
    if not row:
        return None
    secret = json.loads(_decrypt_envelope(row[2]).decode("utf-8"))
    return {"principal_name": row[0], "granting_role_ids": row[1], "expires_at": row[3],
            "revoked": row[4], "coverage": row[5], "access_rank": row[6], **secret}


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
