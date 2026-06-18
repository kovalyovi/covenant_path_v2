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
# BACKEND-06: a signed URL is a bearer capability for facial PII (anyone holding the string can
# fetch the image, bypassing RLS). sync_photos_for_stake re-signs every member's photo on each daily
# run, so a short TTL stays fresh for active stakes while a leaked URL — or a paused stake's URLs —
# expire within a week instead of a year. (Full fix — on-demand minting via a gated route — tracked
# as a follow-up that needs a 3-surface client change.)
SIGNED_TTL = 60 * 60 * 24 * 7  # 7 days (re-signed daily by sync_photos_for_stake)


def _sb() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (url and key):
        # MUST be a normal Exception, NOT SystemExit: the photo pass is best-effort and the daily sync
        # wraps it in `except Exception` ("never fail the data sync over avatars"). SystemExit is a
        # BaseException, so it slipped past that guard and exited the whole sync with code 1 when the
        # service-role key was absent (the 2026-06-18 CI exit-1 bug). RuntimeError is caught and logged.
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY required")
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


def _downsize(data: bytes) -> bytes | None:
    """Decode any image (WebP from the bundle) → a small square-ish JPEG thumbnail."""
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((SIZE, SIZE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("photo downsize failed: %s", exc)
        return None


def sync_photos_from_bundle(conn, stake_id: str, stake_unit: int, access_token: str) -> dict:
    """Member + missionary avatars from the Member Tools /api/v5/sync/files ZIP — NO LCR session, no
    cmisId (supersedes sync_photos_for_stake). Member photos land on members.photo_url; missionary
    photos are uploaded keyed by uuid and the {uuid: signed_url} map is RETURNED so the caller can
    thread it onto the stake's missionary roster. The bundle is ~50MB → run this periodically (the
    daily --photos pass), not every sync."""
    import zipfile
    from lcr_client import membertools
    url, key = _sb()
    ensure_bucket()
    z = zipfile.ZipFile(io.BytesIO(membertools.fetch_sync_files(access_token)))
    members_photos: dict[str, str] = {}
    missionary_photos: dict[str, str] = {}
    for name in z.namelist():
        if not name.lower().endswith(".webp"):
            continue
        uuid = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if name.startswith("MEMBERS_PHOTOS/"):
            members_photos[uuid] = name
        elif name.startswith("MISSIONARIES_"):
            missionary_photos[uuid] = name
    # member photos: only THIS stake's covenant-path members that actually have a photo in the bundle.
    with conn.cursor() as cur:
        cur.execute("select person_uuid from members where stake_id = %s", (stake_id,))
        member_uuids = [r[0] for r in cur.fetchall() if r[0]]
    stats = {"member_photos": 0, "missionary_photos": 0, "skipped": 0}
    for uuid in member_uuids:
        entry = members_photos.get(uuid)
        if not entry:
            continue
        thumb = _downsize(z.read(entry))
        if not thumb:
            stats["skipped"] += 1
            continue
        path = f"{stake_unit}/{uuid}.jpg"
        if not _upload(url, key, path, thumb):
            stats["skipped"] += 1
            continue
        signed = _signed_url(url, key, path)
        with conn.cursor() as cur:
            cur.execute("update members set photo_url=%s, photo_path=%s where stake_id=%s and person_uuid=%s",
                        (signed, path, stake_id, uuid))
        conn.commit()
        stats["member_photos"] += 1
    # missionary photos → bucket keyed by uuid; return the signed-url map for the missionary roster.
    missionary_urls: dict[str, str] = {}
    for uuid, entry in missionary_photos.items():
        thumb = _downsize(z.read(entry))
        if not thumb:
            continue
        path = f"missionaries/{uuid}.jpg"
        if _upload(url, key, path, thumb):
            su = _signed_url(url, key, path)
            if su:
                missionary_urls[uuid] = su
                stats["missionary_photos"] += 1
    logger.info("photo bundle for stake %s: %s", stake_id, stats)
    return {"stats": stats, "missionary_urls": missionary_urls}


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
