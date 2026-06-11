"""
READ-ONLY probe: mint a Member Tools bearer token off our existing Okta session and do ONE
POST /api/v5/sync, then dump the payload's structure (keys + counts only — no PII values) and check
which of our 13 covenant-path fields it carries.

This is the verification gate BEFORE any sync rewiring: it confirms (a) we can mint the token from
our broker's Okta session (silent prompt=none PKCE), and (b) the bulk payload actually contains the
data we currently scrape from the fragile /api/report/one-work/* cluster.

    python tools/membertools_probe.py

Recipe reverse-engineered from github.com/rickybloomfield/Mission-KPIs (docs/auth.md,
MemberToolsAuth.swift, MemberToolsClient.swift, prototype/phase1_okta_probe.py).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from lcr_client.logging_setup import get_logger  # noqa: E402

logger = get_logger()

OKTA = "https://id.churchofjesuschrist.org/oauth2/default/v1"
MT_API = "https://membertools-api.churchofjesuschrist.org/api/v5/sync"
CLIENT_ID = "0oa18r3fbarSYzU4V358"
REDIRECT = "membertoolsauth://login"
SCOPE = "openid profile offline_access cmisid no_links"
UA = "MLTools 5.5.2-(13763) / iOS 17.0 / iPhone"

# What we need today (covenant_path.report.CovenantPathMember + roster). Map our concept -> candidate
# field names seen in the Mission-KPIs Swift models, so we can confirm coverage from a REAL response.
OUR_FIELDS = {
    "person_uuid": ["uuid", "personUuid", "legacyCmisId", "cmisId"],
    "name": ["name", "nameFormats", "displayName", "spokenName"],
    "baptism_date": ["confirmationDate", "baptismDate", "baptismGoalDate"],
    "baptism_goal_date": ["baptismGoalDate"],
    "first_lesson": ["firstTaught", "firstLessonDate"],
    "lessons / being-taught": ["teachingRecords", "lessons", "principlesTaught"],
    "commitments": ["commitments", "otherCommitments", "investigatorCommitments"],
    "friends": ["friends", "numberOfFriends"],
    "weeks_since_attendance": ["sacramentAttendance", "weeksSinceLastAttendance", "attendance"],
    "temple_recommend": ["templeRecommend", "recommendStatus", "recommendExpiration"],
    "patriarchal_blessing": ["patriarchalBlessing", "hasPatriarchalBlessing"],
    "ministering": ["ministering", "ministeringBrothers", "ministeringSisters"],
    "callings": ["callings", "positions", "individualCallings"],
    "sex": ["sex", "gender"],
    "sealing": ["sealedToParents", "sealedToSpouse", "templeOrdinances"],
}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _pkce():
    v = _b64url(secrets.token_bytes(32))
    c = _b64url(hashlib.sha256(v.encode()).digest())
    return v, c


def mint_token(sess) -> dict:
    """Silent prompt=none Authorization-Code+PKCE mint against the live Okta session in `sess`."""
    verifier, challenge = _pkce()
    params = {
        "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "response_type": "code",
        "scope": SCOPE, "code_challenge": challenge, "code_challenge_method": "S256",
        "state": secrets.token_hex(8), "nonce": secrets.token_hex(8), "prompt": "none",
    }
    r = sess.get(f"{OKTA}/authorize", params=params, allow_redirects=False,
                 headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                 timeout=60)
    loc = r.headers.get("Location", "")
    if not (300 <= r.status_code < 400) or "code=" not in loc:
        raise RuntimeError(f"silent authorize did not return a code (HTTP {r.status_code}); "
                           f"Okta session not valid for this client. loc={loc[:120]}")
    q = parse_qs(urlparse(loc).query)
    if "error" in q:
        raise RuntimeError(f"authorize error: {q['error']}")
    code = q["code"][0]
    t = sess.post(f"{OKTA}/token",
                  data={"grant_type": "authorization_code", "client_id": CLIENT_ID, "code": code,
                        "code_verifier": verifier, "redirect_uri": REDIRECT},
                  headers={"User-Agent": UA, "Accept": "application/json",
                           "Content-Type": "application/x-www-form-urlencoded"}, timeout=60)
    t.raise_for_status()
    return t.json()


def fetch_sync(sess, access_token: str) -> dict:
    r = sess.post(MT_API,
                  headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json",
                           "Content-Type": "application/json", "Accept-Language": "en-US,en;q=0.9",
                           "User-Agent": UA}, timeout=180,
                  data=json.dumps({"manual": True, "automatic": True, "attempt": 1,
                                   "timeZone": "America/New_York"}))
    r.raise_for_status()
    return r.json()


def _member_keys(arr):
    """Union of keys across the objects in a list-of-dicts (the per-person fields)."""
    ks = set()
    for o in (arr or []):
        if isinstance(o, dict):
            ks |= set(o.keys())
    return ks


def main() -> int:
    # The silent prompt=none mint needs a LIVE Okta `sid` session — a stored LCR session has the LCR
    # cookies but the Okta session has lapsed (mint → error=login_required). So authenticate FRESH to
    # Okta and mint on that same session immediately, while the Okta session is live.
    import os
    from dotenv import load_dotenv
    from lcr_client import okta_login
    load_dotenv()
    sess = okta_login.new_session()
    logger.info("authenticating to Okta (fresh) to establish a live session…")
    okta_login._authenticate_okta(sess, os.getenv("LCR_LOGIN"), os.getenv("LCR_PASSWORD"))

    logger.info("minting Member Tools bearer (silent prompt=none)…")
    tok = mint_token(sess)
    at = tok.get("access_token", "")
    logger.info("MINTED: access_token len=%d, has_refresh=%s, expires_in=%s, scope=%s",
                len(at), bool(tok.get("refresh_token")), tok.get("expires_in"), tok.get("scope"))

    logger.info("POST /api/v5/sync …")
    data = fetch_sync(sess, at)

    print("\n=== /api/v5/sync TOP-LEVEL KEYS ===")
    top = sorted(data.keys()) if isinstance(data, dict) else [type(data).__name__]
    print(top)
    for k in ("covenantPathInvestigators", "covenantPathMembers", "covenantPathReturningMembers",
              "investigators", "newMembers", "returningMembers", "households", "units"):
        v = data.get(k) if isinstance(data, dict) else None
        if isinstance(v, list):
            print(f"\n{k}: {len(v)} entries; per-entry keys:")
            print("   ", sorted(_member_keys(v)))

    # Coverage check vs our 13 fields
    all_keys = set()
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                all_keys |= _member_keys(v)
    print("\n=== OUR-FIELD COVERAGE in the payload ===")
    for concept, candidates in OUR_FIELDS.items():
        hit = [c for c in candidates if c in all_keys]
        mark = "OK " if hit else "?? "
        print(f"  {mark}{concept:24} -> {hit if hit else 'NOT FOUND (candidates: %s)' % candidates}")

    # CORRECTNESS: which MT id matches our existing person_uuid? (wrong choice => duplicated members)
    try:
        from backend import db as _db
        ids_id, ids_member = set(), set()
        for arr in ("covenantPathInvestigators", "covenantPathMembers", "covenantPathReturningMembers"):
            for p in (data.get(arr) or []):
                if p.get("id"):
                    ids_id.add(str(p["id"]).lower())
                if p.get("memberUuid"):
                    ids_member.add(str(p["memberUuid"]).lower())
        conn = _db.connect(); cur = conn.cursor()
        cur.execute("select lower(person_uuid) from members where person_uuid is not null")
        ours = {r[0] for r in cur.fetchall()}
        conn.close()
        print("\n=== person_uuid MATCH vs our DB (which MT field to key on) ===")
        print(f"  our DB person_uuids: {len(ours)}")
        print(f"  MT 'id'        overlap: {len(ids_id & ours)} / {len(ids_id)}")
        print(f"  MT 'memberUuid' overlap: {len(ids_member & ours)} / {len(ids_member)}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n(person_uuid cross-check skipped: {exc})")

    out = Path(__file__).resolve().parent / "output" / "membertools_sync_shape.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    shape = {"top_level": top,
             "per_array_keys": {k: sorted(_member_keys(v)) for k, v in data.items()
                                if isinstance(v, list)} if isinstance(data, dict) else {}}
    out.write_text(json.dumps(shape, indent=2), encoding="utf-8")
    print(f"\n[+] structure (keys only, no PII) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
