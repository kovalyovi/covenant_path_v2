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


# --- effective-credential selection (migration 0068) --------------------------------------
# A stake may hold MULTIPLE credentials (one row per leader/calling). The EFFECTIVE credential —
# the one the daily sync, the profile refresh, and the alerts all use — is the HIGHEST access_rank
# among live (non-revoked) rows, freshest winning a tie. Every read/write below targets it, so a
# narrower standby row can never shadow the broadest live one, and a revoked/dead top row falls
# through to the next-highest standby with no re-enroll.
_EFFECTIVE_ORDER = "access_rank desc nulls last, updated_at desc"


def _effective_id_subquery() -> str:
    """`id = (<this>)` — the effective row for a stake (params: stake_id)."""
    return ("(select id from stake_credentials where stake_id=%s and not revoked "
            f"order by {_EFFECTIVE_ORDER} limit 1)")


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
    optional `coverage` (allowed-feature info) and `access_rank` for most-elevated comparison.

    One row per LEADER per stake (0068): upsert on (stake_id, principal_email), replacing only
    that leader's own row — another leader's row is never touched."""
    blob = _encrypt_envelope(json.dumps({
        "cookies": grant.get("cookies"),
        "refresh_token": grant.get("refresh_token"),
    }).encode("utf-8"))
    import psycopg2.extras  # lazy: keeps the broker (encrypt-only) from needing psycopg2
    coverage = grant.get("coverage")
    principal = grant.get("principal")
    principal_name = ((principal or {}).get("name") if isinstance(principal, dict)
                      else grant.get("principal_name"))
    principal_email = ((principal or {}).get("email") if isinstance(principal, dict)
                       else grant.get("principal_email") or "")
    with conn.cursor() as cur:
        cur.execute("""
            insert into stake_credentials
                (stake_id, principal_name, principal_email, granting_role_ids, credential_enc,
                 coverage, access_rank, expires_at, revoked, updated_at)
            values (%s,%s,%s,%s,%s,%s,%s,%s,false, now())
            on conflict (stake_id, principal_email) do update set
                principal_name=excluded.principal_name,
                granting_role_ids=excluded.granting_role_ids,
                credential_enc=excluded.credential_enc,
                coverage=excluded.coverage,
                access_rank=excluded.access_rank,
                expires_at=excluded.expires_at,
                revoked=false, revoked_at=null, updated_at=now()
        """, (stake_id, principal_name, (principal_email or "").lower(),
              grant.get("granting_role_ids"), blob,
              psycopg2.extras.Json(coverage) if coverage is not None else None,
              grant.get("access_rank"), grant.get("expires_at")))
    conn.commit()
    logger.info("stored stake credential for %s", stake_id)


def get_credential(conn, stake_id: str) -> dict | None:
    """Decrypt + return a stake's EFFECTIVE credential ({cookies, refresh_token, ...}) or None —
    the highest-rank live row (0068), never a narrower standby."""
    with conn.cursor() as cur:
        cur.execute(f"""select id, principal_name, principal_email, granting_role_ids,
                              credential_enc, expires_at, revoked, coverage, access_rank
                       from stake_credentials where stake_id=%s and not revoked
                       order by {_EFFECTIVE_ORDER} limit 1""", (stake_id,))
        row = cur.fetchone()
    if not row:
        return None
    secret = json.loads(_decrypt_envelope(row[4]).decode("utf-8"))
    return {"id": row[0], "principal_name": row[1], "principal_email": row[2],
            "granting_role_ids": row[3], "expires_at": row[5],
            "revoked": row[6], "coverage": row[7], "access_rank": row[8], **secret}


def list_active_stakes(conn) -> list[dict]:
    """Stakes with at least one non-revoked credential, for the daily multi-stake loop.
    DISTINCT: a stake with several enrolled leaders still syncs once, on its effective credential."""
    with conn.cursor() as cur:
        cur.execute("""select distinct c.stake_id, s.unit_number, s.name
                       from stake_credentials c join stakes s on s.id=c.stake_id
                       where not c.revoked""")
        return [{"stake_id": r[0], "unit_number": r[1], "name": r[2]} for r in cur.fetchall()]


def stake_id_for_unit(conn, unit_number: int) -> str | None:
    """Resolve a stake's UUID id from its LCR unit number (the daily sync keys by unit)."""
    with conn.cursor() as cur:
        cur.execute("select id from stakes where unit_number=%s", (unit_number,))
        row = cur.fetchone()
    return str(row[0]) if row else None


# --- Member Tools 45-day refresh token (migration 0049): persisted in Supabase so the daily sync
#     renews the /api/v5/sync bearer with NO live Okta session — survives the ephemeral CI runners
#     the local file store can't. Encrypted with the same envelope key as the credential blob. -------

def save_membertools_refresh(conn, stake_id: str, refresh_token: str,
                             minted_at: str | None = None) -> None:
    """Persist a stake's Member Tools refresh token (encrypted) on the EFFECTIVE credential.
    Preserves the ORIGINAL mint date across refreshes (rotation is off) so the 45-day clock
    isn't reset by a renewal."""
    if not refresh_token:
        return
    blob = _encrypt_envelope(json.dumps({"refresh_token": refresh_token}).encode("utf-8"))
    with conn.cursor() as cur:
        cur.execute(
            f"""update stake_credentials
                  set membertools_refresh_enc = %s,
                      membertools_minted_at = coalesce(membertools_minted_at, %s, now())
                where id = {_effective_id_subquery()}""",
            (blob, minted_at, stake_id))
    conn.commit()
    logger.info("saved Member Tools refresh token for stake %s", stake_id)


def get_membertools_refresh(conn, stake_id: str) -> dict | None:
    """{refresh_token, minted_at} for a stake's EFFECTIVE credential (decrypted), or None."""
    with conn.cursor() as cur:
        cur.execute(f"""select membertools_refresh_enc, membertools_minted_at
                       from stake_credentials where stake_id=%s and not revoked
                       order by {_EFFECTIVE_ORDER} limit 1""", (stake_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        return None
    try:
        secret = json.loads(_decrypt_envelope(row[0]).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — a bad/old blob must not break the sync
        logger.warning("Member Tools token decrypt skipped for stake %s: %s", stake_id, exc)
        return None
    tok = secret.get("refresh_token")
    return {"refresh_token": tok, "minted_at": row[1]} if tok else None


def clear_membertools_refresh(conn, stake_id: str) -> None:
    """Drop a stake's Member Tools refresh token (it hit the 45-day wall / was revoked) from the
    EFFECTIVE credential so the next sync re-mints off a fresh Okta session instead of looping
    on a dead refresh token."""
    with conn.cursor() as cur:
        cur.execute(f"""update stake_credentials
                       set membertools_refresh_enc = null, membertools_minted_at = null
                       where id = {_effective_id_subquery()}""", (stake_id,))
    conn.commit()


def revoke(conn, stake_id: str, reason: str = "manual", principal_email: str | None = None) -> None:
    """Revoke a stake credential. With no principal_email this revokes the EFFECTIVE row (the one
    the sync ran with — what _revoke_if_ineligible and the scope-mismatch guard mean). Pass a
    principal_email to revoke one leader's own row, leaving the other holders untouched."""
    with conn.cursor() as cur:
        if principal_email:
            cur.execute("""update stake_credentials set revoked=true, revoked_at=now(),
                           audit = audit || %s::jsonb
                           where stake_id=%s and lower(principal_email)=lower(%s)""",
                        (json.dumps([{"event": "revoked", "reason": reason}]), stake_id,
                         principal_email))
        else:
            cur.execute(f"""update stake_credentials set revoked=true, revoked_at=now(),
                           audit = audit || %s::jsonb
                           where id = {_effective_id_subquery()}""",
                        (json.dumps([{"event": "revoked", "reason": reason}]), stake_id))
    conn.commit()
    logger.warning("revoked stake credential %s (%s)", stake_id, reason)


# --- staleness state (migration 0038): drives the app's re-authorize banner, the no-spam alert edge,
#     the enroll-RPC takeover clause, and the ops staleness view. -----------------------------------

def mark_failed(conn, stake_id: str, error: str) -> None:
    """Stamp the EFFECTIVE credential as currently FAILING (its delegated session couldn't mint).
    Records the reason; leaves stale_notified_at to the alert edge below."""
    with conn.cursor() as cur:
        cur.execute(f"update stake_credentials set last_failed_at=now(), last_error=%s "
                    f"where id={_effective_id_subquery()}",
                    ((error or "")[:500], stake_id))
    conn.commit()


def mark_succeeded(conn, stake_id: str) -> None:
    """Stamp the EFFECTIVE credential healthy after a successful sync — clears the failing +
    notified state so the NEXT failure re-alerts (the success->failure edge), never spamming on
    a streak of failures."""
    with conn.cursor() as cur:
        cur.execute(f"update stake_credentials set last_succeeded_at=now(), last_failed_at=null, "
                    f"last_error=null, stale_notified_at=null where id={_effective_id_subquery()}",
                    (stake_id,))
    conn.commit()


def claim_stale_notification(conn, stake_id: str) -> bool:
    """Atomically claim the right to send ONE stale-credential alert for this failure streak on
    the EFFECTIVE credential. Returns True only the FIRST failure after a success
    (mark_succeeded cleared stale_notified_at). Subsequent consecutive failures return False,
    so we email once per streak, not once per run."""
    with conn.cursor() as cur:
        cur.execute(f"update stake_credentials set stale_notified_at=now() "
                    f"where id={_effective_id_subquery()} and stale_notified_at is null",
                    (stake_id,))
        claimed = cur.rowcount > 0
    conn.commit()
    return claimed


def claim_age_notification(conn, stake_id: str, min_age_days: int) -> bool:
    """Atomically claim the ONE pre-emptive aging alert per credential GENERATION (migration 0047,
    B8): fires only when the stored session is older than `min_age_days`, cannot self-renew (no LCR
    refresh token), isn't revoked, and hasn't been age-notified since it was last (re)stored.

    The aging clock is `coalesce(membertools_minted_at, updated_at)` — the REAL Member Tools 45-day
    token clock when one is stored, else the cookie-session age. This is the #0 fix (F3): the daily
    sync renews the bearer off the stored 45-day token WITHOUT rewriting the credential blob, so
    `updated_at` is NOT the token's clock — a stake kept alive only by the Member Tools token could be
    nudged on the wrong date (too early after a fresh bootstrap mint, or not aligned with the real
    expiry). Keying off `membertools_minted_at` lands the ~day-40 nudge ~5 days before the token truly
    expires; a re-mint (which resets `membertools_minted_at`) re-arms it. When no token is stored
    (`membertools_minted_at is null`) this is byte-identical to the prior updated_at behavior."""
    with conn.cursor() as cur:
        cur.execute(
            f"""update stake_credentials set age_notified_at = now()
                 where id = (select id from stake_credentials where stake_id = %s
                   and not revoked
                   and coalesce(has_refresh_token, false) = false
                   and coalesce(membertools_minted_at, updated_at) < now() - make_interval(days => %s)
                   and (age_notified_at is null
                        or age_notified_at < coalesce(membertools_minted_at, updated_at))
                   order by {_EFFECTIVE_ORDER} limit 1)""",
            (stake_id, min_age_days))
        claimed = cur.rowcount > 0
    conn.commit()
    return claimed


def provider_email(conn, stake_id: str) -> str | None:
    """The email of the leader whose session backs this stake — the EFFECTIVE provider (highest
    live rank), for the stale-credential alert."""
    with conn.cursor() as cur:
        cur.execute(f"select principal_email from stake_credentials where stake_id=%s and not revoked "
                    f"order by {_EFFECTIVE_ORDER} limit 1", (stake_id,))
        row = cur.fetchone()
    return (row[0] if row else None) or None
