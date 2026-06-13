"""
READ-ONLY deep probe (one-off investigation): refresh the stored 503991 Member Tools 45-day token
-> access token, pull /api/v5/sync ONCE, and EXHAUSTIVELY map the payload for the still-PROFILE-only
covenant-path fields (priesthood office, temple recommend, patriarchal blessing, endowment / living
ordinance) so we can decide which can be rescued from the bulk payload (renews with the 45-day token)
instead of the dead-in-steady-state /mlt profile scrape.

PII SAFETY: this prints STRUCTURE only — keys, counts, enum-like short tokens (TYPE/STATUS values),
and boolean flags. It never prints names, dates, emails, addresses, or uuids' owners. The full payload
is written to a gitignored tools/output path for local inspection and is NOT committed.

    PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python tools/membertools_deep_probe.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from lcr_client import membertools  # noqa: E402

TARGET_UNIT = 503991

NEEDLES = [
    "priesthood", "ordination", "ordain", "office",
    "temple", "recommend", "endow", "ordinance",
    "patriarch", "blessing", "sealed", "sealing", "melch", "aaronic",
    "elder", "highpriest", "high_priest", "prospective", "convert",
]


def _safe_value(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return "<num>"
    if isinstance(v, str):
        s = v.strip()
        if (len(s) <= 40 and s
                and not any(ch.isdigit() for ch in s)
                and s.replace("_", "").replace("-", "").replace(" ", "").isalnum()
                and s.upper() == s):
            return repr(s)
        return "<str>"
    if isinstance(v, list):
        return f"<list[{len(v)}]>"
    if isinstance(v, dict):
        return f"<dict{sorted(v.keys())[:8]}>"
    return f"<{type(v).__name__}>"


def _walk(obj, path, hits, depth=0, maxdepth=8):
    if depth > maxdepth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(n in kl for n in NEEDLES):
                hits.append((".".join(path + [str(k)]), _safe_value(v)))
            _walk(v, path + [str(k)], hits, depth + 1, maxdepth)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:2]):
            _walk(item, path + [f"[{i}]"], hits, depth + 1, maxdepth)


def _dump_keys(arr, label):
    ks = Counter()
    for o in (arr or []):
        if isinstance(o, dict):
            ks.update(o.keys())
    n = len(arr or [])
    print(f"\n--- {label}: {n} entries; union keys ---")
    print("   ", sorted(ks))
    return n


def main() -> int:
    # secrets live at the REAL repo root, not the worktree
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    if not os.getenv("CP_TOKEN_KEY"):
        load_dotenv()  # fallback

    from backend import db, credentials

    conn = db.connect()
    sid = credentials.stake_id_for_unit(conn, TARGET_UNIT)
    rec = credentials.get_membertools_refresh(conn, sid)
    conn.close()
    if not rec or not rec.get("refresh_token"):
        print("NO refresh token for stake; abort.")
        return 1

    print("[*] refreshing 45-day token -> access token ...")
    tok = membertools.refresh(rec["refresh_token"])
    at = tok.get("access_token", "")
    print(f"[*] refresh OK: access_token len={len(at)}, scope={tok.get('scope')}, "
          f"expires_in={tok.get('expires_in')}, has_new_refresh={bool(tok.get('refresh_token'))}")

    try:
        parts = at.split(".")
        pad = "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        safe_claims = {k: (v if k in ("scp", "ver", "aud", "cid", "tokenType", "auth_time", "amr")
                           else "<redacted>") for k, v in claims.items()}
        print("\n=== ACCESS TOKEN CLAIMS (sensitive values redacted) ===")
        print(json.dumps(safe_claims, indent=2, sort_keys=True))
        print("granted scopes (scp):", claims.get("scp"))
    except Exception as exc:  # noqa: BLE001
        print("(claims decode failed:", exc, ")")

    print("\n[*] POST /api/v5/sync ...")
    data = membertools.fetch_sync(at)

    print("\n=== TOP-LEVEL KEYS ===")
    print(sorted(data.keys()) if isinstance(data, dict) else type(data).__name__)

    for key in ("templeRecommendStatus", "familyTempleRecommends", "ordinanceRecommends",
                "unitStatistics", "covenantPathMembers", "covenantPathInvestigators",
                "covenantPathReturningMembers"):
        v = data.get(key) if isinstance(data, dict) else None
        if isinstance(v, list):
            n = _dump_keys(v, key)
            if n and key in ("templeRecommendStatus", "ordinanceRecommends",
                             "familyTempleRecommends"):
                samp = v[0]
                print(f"    sample[0] keys -> {sorted(samp.keys())}")
                for subk, subv in samp.items():
                    if isinstance(subv, list) and subv and isinstance(subv[0], dict):
                        subks = Counter()
                        type_vals, status_vals = Counter(), Counter()
                        for it in subv:
                            subks.update(it.keys())
                            tv = it.get("type") or it.get("recommendType")
                            sv = it.get("status") or it.get("recommendStatus")
                            if isinstance(tv, str):
                                type_vals[tv] += 1
                            if isinstance(sv, str):
                                status_vals[sv] += 1
                        print(f"      .{subk}[{len(subv)}] keys -> {sorted(subks)}")
                        if type_vals:
                            print(f"        type values -> {dict(type_vals)}")
                        if status_vals:
                            print(f"        status values -> {dict(status_vals)}")
        elif isinstance(v, dict):
            print(f"\n--- {key}: dict keys -> {sorted(v.keys())}")

    us = data.get("unitStatistics") if isinstance(data, dict) else None
    if isinstance(us, list) and us:
        print("\n=== unitStatistics priesthood/temple UUID arrays (counts only) ===")
        office_keys = [k for k in us[0]
                       if any(t in k.lower() for t in ("deacon", "teacher", "priest", "elder",
                                                       "highpriest", "endow", "recommend", "ordain",
                                                       "prospective", "convert"))]
        for stat in us[:1]:
            for k in sorted(office_keys):
                v = stat.get(k)
                if isinstance(v, list):
                    print(f"   {k}: {len(v)} uuids")
                elif isinstance(v, (int, float)):
                    print(f"   {k}: {v}")

    print("\n=== EXHAUSTIVE needle search (key path -> safe value/type) ===")
    hits = []
    _walk(data, [], hits)
    seen = set()
    for path, val in hits:
        if path in seen:
            continue
        seen.add(path)
        print(f"   {path}  ->  {val}")

    for arr in ("covenantPathMembers", "covenantPathInvestigators"):
        people = data.get(arr) or []
        if not people:
            continue
        pe = sum(1 for p in people if isinstance(p, dict) and p.get("priesthoodEligibility") is not None)
        ee = sum(1 for p in people if isinstance(p, dict) and p.get("endowmentEligibilityDate"))
        sp = sum(1 for p in people if isinstance(p, dict) and p.get("sealedToParents") is not None)
        ss = sum(1 for p in people if isinstance(p, dict) and p.get("sealedToSpouse") is not None)
        print(f"\n[{arr}] n={len(people)}: priesthoodEligibility set={pe}, "
              f"endowmentEligibilityDate set={ee}, sealedToParents set={sp}, sealedToSpouse set={ss}")
        for p in people:
            v = p.get("priesthoodEligibility") if isinstance(p, dict) else None
            if v is not None:
                print(f"   priesthoodEligibility example type: {_safe_value(v)}")
                break

    out = Path(__file__).resolve().parent / "output" / "_mt_full_payload_503991.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[+] FULL payload (PII — gitignored, do NOT commit) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
