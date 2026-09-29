#!/usr/bin/env python3
"""Pull the whole stake into ONE local JSON file: tools/output/stake_data.json.

Usage:
    LCR_LOGIN='you@example.com' LCR_PASSWORD='...' python scripts/pull_stake_data.py
    # ...or put LCR_LOGIN / LCR_PASSWORD in a .env file at the repo root.

What it does:
  1. Headless Church-account login (lcr_client.okta_login) -> tools/output/storage_state.json
     (skipped when a live session file already exists).
  2. Silently mints a Member Tools token off the live Okta session.
  3. Pulls the whole-stake /api/v5/sync payload (one ~7MB call, no per-member fan-out).
  4. Writes tools/output/stake_data.json::

        {"meta": {"stake": ..., "pulled_at": ..., "members": N, "units": M},
         "units": [{"unit_number": ..., "name": ..., "type": ...}],
         "members": [{"uuid": ..., "full_name": ..., "preferred_name": ...,
                      "unit_number": ..., "unit_name": ..., "sex": ..., "birth_date": ...}],
         "leadership": {"<unit_number>": [{"position": ..., "person": ...,
                                           "person_uuid": ..., "set_apart": ...}]}}

Query it any time with scripts/stake.py (no login needed)::
    python scripts/stake.py find "nathan reading"
    python scripts/stake.py ward "cary 1st"
    python scripts/stake.py leadership
    python scripts/stake.py units

Notes:
  - No MFA prompt is expected for accounts without 2-step verification enrolled.
    If the account HAS MFA, capture the session once with
    ``python tools/lcr_crawler.py`` (writes the same storage_state.json),
    then re-run this script — it reuses the existing session file.
  - The Member Tools refresh token lives 45 days; this script mints a fresh one
    on every run instead of storing it, so each run is self-contained.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tools" / "output" / "stake_data.json"

from lcr_client import membertools  # noqa: E402
from lcr_client.auth import LcrSession  # noqa: E402
from covenant_path.membertools_adapter import staffing_by_unit  # noqa: E402


def _units(payload: dict) -> tuple[str, list[dict]]:
    """(stake name, [{unit_number, name, type}]) from the sync payload's units tree."""
    tree = payload.get("units") or []
    if not tree:
        return "", []
    root = tree[0]
    out = []
    if root.get("unitNumber") is not None:
        out.append({"unit_number": int(root["unitNumber"]),
                    "name": root.get("name") or "Stake",
                    "type": root.get("unitType")})
    for c in root.get("childUnits") or []:
        if c.get("unitNumber") is not None:
            out.append({"unit_number": int(c["unitNumber"]),
                        "name": c.get("name") or "",
                        "type": c.get("unitType")})
    return root.get("name") or "", out


def _preferred_name(member: dict, full: str | None) -> str | None:
    names = member.get("names")
    if isinstance(names, dict):
        for k in ("preferred", "preferredName", "givenPreferred"):
            v = names.get(k)
            if v:
                return str(v)
    for k in ("preferredName", "preferred_name", "displayName"):
        v = member.get(k)
        if v and v != full:
            return str(v)
    return None


def _readable_name(member: dict) -> str | None:
    if member.get("displayName"):
        return str(member["displayName"])
    names = member.get("names")
    if isinstance(names, str):
        return names or None
    if isinstance(names, list):
        names = names[0] if names else None
    if isinstance(names, dict):
        for k in ("listed", "full", "fullName"):
            v = names.get(k)
            if v:
                return str(v)
        given = names.get("given") or names.get("givenPreferred") or ""
        family = names.get("family") or names.get("familyPreferred") or ""
        return (f"{family}, {given}".strip(", ").strip()) or None
    return None


# Substrings that mark a raw payload key as contact info. The Member Tools
# sync schema is undocumented, so match broadly and record the key inventory
# (top-level `contact_key_inventory`) to confirm real field names per pull.
CONTACT_NEEDLES = ("phone", "email", "contact", "mobile", "tel", "fax")


def _contact_fields(d: dict) -> dict:
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if any(n in str(k).lower() for n in CONTACT_NEEDLES):
            if isinstance(v, (str, int)):
                out[k] = v
            elif isinstance(v, list) and v and all(isinstance(x, (str, int)) for x in v):
                out[k] = v
    return out


def pull() -> dict:
    t0 = datetime.now(timezone.utc)

    # 1. LCR session (headless login only when no session file exists).
    session = LcrSession(auto_login=True)

    # 2. Member Tools token, silently minted off the live Okta session.
    tok = membertools.mint_from_okta_session(session.session)
    access_token = tok.get("access_token")
    if not access_token:
        raise membertools.MemberToolsError("token mint returned no access_token")

    # 3. Whole-stake bulk pull.
    payload = membertools.fetch_sync(access_token)

    stake_name, units = _units(payload)
    unit_names = {u["unit_number"]: u["name"] for u in units}

    members = []
    key_inventory: set[str] = set()
    for hh in payload.get("households") or []:
        unum = hh.get("unitNumber")
        if isinstance(hh, dict):
            key_inventory.update(str(k) for k in hh.keys())
            hh_contact = _contact_fields(hh)
        else:
            hh_contact = {}
        for m in hh.get("members") or []:
            if not isinstance(m, dict):
                continue
            uuid = m.get("uuid") or m.get("memberUuid") or m.get("id")
            if not uuid:
                continue
            key_inventory.update(str(k) for k in m.keys())
            full = _readable_name(m)
            contact = _contact_fields(m)
            if hh_contact:
                contact = {f"household_{k}": v for k, v in hh_contact.items()} | contact
            members.append({
                "uuid": uuid,
                "full_name": full,
                "preferred_name": _preferred_name(m, full),
                "unit_number": unum,
                "unit_name": unit_names.get(int(unum)) if unum is not None else None,
                "sex": m.get("sex"),
                "birth_date": m.get("birthDate") or m.get("birth_date"),
                "contact": contact,
            })

    leadership = {str(k): v for k, v in staffing_by_unit(payload).items()}

    data = {
        "meta": {
            "stake": stake_name,
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "pull_seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
            "members": len(members),
            "units": len(units),
        },
        "contact_key_inventory": sorted(key_inventory),
        "units": units,
        "members": members,
        "leadership": leadership,
    }
    return data


def main() -> int:
    data = pull()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    meta = data["meta"]
    print(f"[+] {meta['members']} members, {meta['units']} units, "
          f"{sum(len(v) for v in data['leadership'].values())} leadership callings "
          f"-> {OUT} ({meta['pull_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
