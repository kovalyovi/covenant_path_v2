"""
Member-photo pipeline: fetch each member's LCR avatar, downsize to a small JPEG, store it
in a PRIVATE Supabase Storage bucket, and save a signed URL on the member row.

Why this shape:
  - Clients can't call LCR (CORS) and avatars are access-gated, so the *backend* (which holds
    the LCR session) fetches them — same rule as all other data.
  - Avatars are facial PII → a **private** bucket. We store a long-lived **signed URL** on
    `members.photo_url`; the app reads it straight off the RLS-gated member row, so the URL is
    only ever exposed to a viewer already allowed to see that member. No Storage RLS needed.
  - We only upload members who actually have a photo (the manage-photos metadata says so),
    so everyone else keeps the nice initials avatar instead of a generic silhouette.

Run (needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY, and an LCR session):
    python -m backend.photos            # self login, this account's stake
"""

from __future__ import annotations

import io
import os
import sys

import requests

from backend import db
from lcr_client.hosts import LCR_BASE as LCR
from lcr_client.logging_setup import get_logger

logger = get_logger()
BUCKET = "member-photos"
SIZE = 96                      # px (square-ish thumbnail)
SIGNED_TTL = 60 * 60 * 24 * 365  # 1 year


def _sb() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (url and key):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY required")
    return url, key


def _sb_headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def ensure_bucket() -> None:
    url, key = _sb()
    r = requests.post(
        f"{url}/storage/v1/bucket",
        headers={**_sb_headers(key), "Content-Type": "application/json"},
        json={"id": BUCKET, "name": BUCKET, "public": False,
              "fileSizeLimit": "1048576", "allowedMimeTypes": ["image/jpeg"]},
        timeout=20,
    )
    if r.status_code in (200, 201):
        logger.info("created private storage bucket %s", BUCKET)
    elif r.status_code == 409 or "already exists" in r.text.lower() or "duplicate" in r.text.lower():
        logger.info("storage bucket %s already exists", BUCKET)
    else:
        logger.warning("bucket create returned %s: %s", r.status_code, r.text[:200])


def _has_photo(session, cmis_id: str) -> bool:
    """The manage-photos record reports image.tokenUrl=images/nophoto.svg when there's none."""
    try:
        r = session.get(f"{LCR}/api/photos/manage-photos/approved-image-individual/{cmis_id}",
                        timeout=30)
        if r.status_code != 200:
            return False
        token = ((r.json().get("image") or {}).get("tokenUrl") or "")
        return bool(token) and "nophoto" not in token.lower()
    except Exception:  # noqa: BLE001
        return False


def _fetch_thumbnail(session, cmis_id: str) -> bytes | None:
    from PIL import Image
    try:
        r = session.get(f"{LCR}/api/avatar/{cmis_id}/MEDIUM", timeout=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("avatar fetch failed for %s: %s", cmis_id, exc)
        return None
    if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image"):
        return None
    try:
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((SIZE, SIZE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("downsize failed for %s: %s", cmis_id, exc)
        return None


def _upload(url: str, key: str, path: str, data: bytes) -> bool:
    r = requests.post(
        f"{url}/storage/v1/object/{BUCKET}/{path}",
        headers={**_sb_headers(key), "Content-Type": "image/jpeg", "x-upsert": "true"},
        data=data, timeout=30,
    )
    if r.status_code in (200, 201):
        return True
    logger.warning("upload %s -> %s: %s", path, r.status_code, r.text[:150])
    return False


def _signed_url(url: str, key: str, path: str) -> str | None:
    r = requests.post(
        f"{url}/storage/v1/object/sign/{BUCKET}/{path}",
        headers={**_sb_headers(key), "Content-Type": "application/json"},
        json={"expiresIn": SIGNED_TTL}, timeout=20,
    )
    if r.status_code == 200:
        signed = r.json().get("signedURL") or r.json().get("signedUrl")
        return f"{url}/storage/v1{signed}" if signed and signed.startswith("/") else signed
    logger.warning("sign %s -> %s: %s", path, r.status_code, r.text[:150])
    return None


def sync_photos_for_stake(client, conn, stake_id: str, stake_unit: int) -> dict:
    """Fetch + store avatars for every member of the stake that has details.cmisId."""
    url, key = _sb()
    ensure_bucket()
    session = client.session.session  # the raw requests.Session with LCR cookies
    with conn.cursor() as cur:
        cur.execute("select person_uuid, details->>'cmisId' from members "
                    "where stake_id = %s and details ? 'cmisId'", (stake_id,))
        rows = cur.fetchall()
    stats = {"checked": 0, "uploaded": 0, "no_photo": 0, "skipped": 0}
    for person_uuid, cmis in rows:
        stats["checked"] += 1
        if not (person_uuid and cmis):
            stats["skipped"] += 1
            continue
        if not _has_photo(session, cmis):
            stats["no_photo"] += 1
            continue
        thumb = _fetch_thumbnail(session, cmis)
        if not thumb:
            stats["skipped"] += 1
            continue
        path = f"{stake_unit}/{person_uuid}.jpg"
        if not _upload(url, key, path, thumb):
            stats["skipped"] += 1
            continue
        signed = _signed_url(url, key, path)
        with conn.cursor() as cur:
            cur.execute("update members set photo_url = %s, photo_path = %s "
                        "where stake_id = %s and person_uuid = %s",
                        (signed, path, stake_id, person_uuid))
        conn.commit()
        stats["uploaded"] += 1
    logger.info("photo sync for stake %s: %s", stake_id, stats)
    return stats


def main() -> int:
    from lcr_client import LcrClient, okta_login
    okta_login.login()
    client = LcrClient()
    ctx = client.user_context()
    conn = db.connect()
    try:
        stake_id = db.upsert_stake(conn, ctx.unit_number, ctx.unit_name)
        stats = sync_photos_for_stake(client, conn, stake_id, ctx.unit_number)
    finally:
        conn.close()
    print(f"[+] photos: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
