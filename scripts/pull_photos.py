#!/usr/bin/env python3
"""Pull member photos for the whole stake into tools/output/photos/<uuid>.jpg.

Usage:
    LCR_LOGIN='you@example.com' LCR_PASSWORD='...' python scripts/pull_photos.py

What it does:
  1. Headless Church-account login (same LcrSession as pull_stake_data.py).
  2. Silently mints a Member Tools token off the live Okta session.
  3. Downloads the /api/v5/sync/files photo bundle (ZIP of WebP avatars keyed
     by member UUID under MEMBERS_PHOTOS/<uuid>.webp).
  4. Writes each member photo as a downsized JPEG (max 240px) named by member
     UUID, plus tools/output/photos/index.json mapping uuid -> filename.

Only members who actually have a photo in Member Tools appear in the output;
everyone else is simply absent from index.json.
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tools" / "output" / "photos"

from lcr_client import membertools  # noqa: E402
from lcr_client.auth import LcrSession  # noqa: E402


def main() -> int:
    from PIL import Image

    session = LcrSession(auto_login=True)
    tok = membertools.mint_from_okta_session(session.session)
    access_token = tok.get("access_token")
    if not access_token:
        raise membertools.MemberToolsError("token mint returned no access_token")

    bundle = membertools.fetch_sync_files(access_token)
    z = zipfile.ZipFile(io.BytesIO(bundle))

    OUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}
    seen = skipped = 0
    for name in z.namelist():
        if not name.startswith("MEMBERS_PHOTOS/"):
            continue
        if not name.lower().endswith(".webp"):
            continue
        uuid = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if not uuid:
            continue
        seen += 1
        try:
            img = Image.open(io.BytesIO(z.read(name))).convert("RGB")
            img.thumbnail((960, 960))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=82, optimize=True)
            (OUT / f"{uuid}.jpg").write_bytes(out.getvalue())
            index[uuid] = f"{uuid}.jpg"
        except Exception as exc:  # noqa: BLE001 - one bad image must not sink the pull
            skipped += 1
            print(f"[!] skipped {name}: {exc}")

    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"[+] {len(index)} member photos ({seen} in bundle, {skipped} skipped) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
