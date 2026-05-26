"""
Encrypted, per-stake store for delegated LCR access grants.

When an authorized leader (e.g. a Stake President) authorizes the script on their
behalf (see lcr_client/delegated_login.py), the resulting session — the long-term
secret — is persisted here, encrypted at rest with Fernet (AES-128-CBC + HMAC).

A "grant" is keyed by stake unit number and records: who authorized it, their
callings/role-ids at grant time (for change-detection), consent, an expiry, the
encrypted session cookies (and optional refresh token), and an append-only audit
log. Secrets (cookies / refresh token) are NEVER logged; list_grants() returns a
redacted view only.

Encryption key resolution (first wins):
  1. env CP_TOKEN_KEY  — a urlsafe-base64 Fernet key (preferred for prod / CI).
  2. key file tools/output/.token_key (0600) — auto-generated for local dev.
Rotating the key invalidates existing grants (they must be re-authorized).

SECURITY NOTE: storing the key file next to the encrypted store only protects
against casual disk/backup exposure. For real protection, supply CP_TOKEN_KEY from
a secret manager and do NOT keep the key file on the same host.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from lcr_client.logging_setup import get_logger

logger = get_logger()

_OUTPUT = Path(__file__).resolve().parent.parent / "tools" / "output"
STORE_PATH = _OUTPUT / "delegated_grants.enc"
KEY_PATH = _OUTPUT / ".token_key"

# Secret fields redacted from any human-facing / logged view.
_SECRET_FIELDS = ("cookies", "refresh_token")


class TokenStoreError(RuntimeError):
    pass


def _load_key() -> bytes:
    env = os.getenv("CP_TOKEN_KEY")
    if env:
        return env.encode("ascii")
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()
    # generate a dev key
    _OUTPUT.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600 (best-effort on win32)
    except OSError:
        pass
    logger.warning("generated a new token key at %s — set CP_TOKEN_KEY for production", KEY_PATH)
    return key


def _fernet() -> Fernet:
    try:
        return Fernet(_load_key())
    except (ValueError, TypeError) as exc:
        raise TokenStoreError(f"invalid CP_TOKEN_KEY / key file: {exc}") from exc


def _read_all() -> dict[str, dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        raw = _fernet().decrypt(STORE_PATH.read_bytes())
    except InvalidToken as exc:
        raise TokenStoreError(
            "could not decrypt the grant store — the key changed or the file is corrupt. "
            "Existing grants must be re-authorized."
        ) from exc
    return json.loads(raw.decode("utf-8"))


def _write_all(grants: dict[str, dict]) -> None:
    _OUTPUT.mkdir(parents=True, exist_ok=True)
    blob = _fernet().encrypt(json.dumps(grants).encode("utf-8"))
    STORE_PATH.write_bytes(blob)
    try:
        os.chmod(STORE_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def save_grant(grant: dict) -> None:
    """Insert/replace the grant for grant['stake_unit'] (full record, incl. secrets)."""
    key = str(grant["stake_unit"])
    grants = _read_all()
    grants[key] = grant
    _write_all(grants)
    logger.info("saved delegated grant for stake %s (principal=%s)",
                key, grant.get("principal", {}).get("name"))


def get_grant(stake_unit: int | str) -> dict | None:
    """Full grant record (with secrets) for minting; None if absent."""
    return _read_all().get(str(stake_unit))


def append_audit(stake_unit: int | str, event: str, detail: Any = None) -> None:
    grants = _read_all()
    g = grants.get(str(stake_unit))
    if not g:
        return
    g.setdefault("audit", []).append({"ts": _now(), "event": event, "detail": detail})
    _write_all(grants)
    logger.info("audit[stake %s]: %s %s", stake_unit, event, detail if detail else "")


def revoke(stake_unit: int | str, reason: str = "manual") -> bool:
    """Kill switch: mark a grant revoked (kept for audit, refused on mint). Returns found."""
    grants = _read_all()
    g = grants.get(str(stake_unit))
    if not g:
        return False
    g["revoked"] = True
    g["revoked_at"] = _now()
    g.setdefault("audit", []).append({"ts": _now(), "event": "revoked", "detail": reason})
    _write_all(grants)
    logger.warning("revoked delegated grant for stake %s (%s)", stake_unit, reason)
    return True


def delete_grant(stake_unit: int | str) -> bool:
    grants = _read_all()
    if str(stake_unit) in grants:
        del grants[str(stake_unit)]
        _write_all(grants)
        logger.warning("deleted delegated grant for stake %s", stake_unit)
        return True
    return False


def _redact(grant: dict) -> dict:
    out = {k: v for k, v in grant.items() if k not in _SECRET_FIELDS}
    out["has_cookies"] = bool(grant.get("cookies"))
    out["has_refresh_token"] = bool(grant.get("refresh_token"))
    return out


def list_grants() -> list[dict]:
    """Redacted summaries of all grants (no secrets) — safe to print/log."""
    return [_redact(g) for g in _read_all().values()]
