#!/usr/bin/env python3
"""Pull the whole stake into ONE local JSON file: tools/output/stake_data.json.

Usage:
    LCR_LOGIN='you@example.com' LCR_PASSWORD='...' python scripts/pull_stake_data.py
    # ...or put LCR_LOGIN / LCR_PASSWORD in a .env file at the repo root.
    python scripts/pull_stake_data.py --from-raw tools/output/stake_data_raw.json
    # ...normalize a previously captured raw /api/v5/sync payload (e.g. the
    # daily-sync CI artifact) with NO login at all — the unblock while the
    # headless Okta login is 428-blocked (2026-11-07/08).

What it does:
  1. Auth, token-first (2026-11-08): a stored Member Tools refresh token
     (MEMBERTOOLS_REFRESH_TOKEN env, 45-day life, no session needed) is tried
     first; else headless Church-account login (lcr_client.okta_login) ->
     tools/output/storage_state.json (skipped when a live session file
     already exists), then a Member Tools token is silently minted off the
     live Okta session. --from-raw skips all of this.
  2. Pulls the whole-stake /api/v5/sync payload (one ~7MB call, no per-member fan-out),
     and saves it VERBATIM to tools/output/stake_data_raw.json (the Families
     derivation needs households + unitStatistics + classifications +
     names.listed, which the normalized file discards). --save-raw PATH to
     override, --no-save-raw to skip.
  3. Writes tools/output/stake_data.json::

        {"meta": {"stake": ..., "pulled_at": ..., "members": N, "units": M},
         "units": [{"unit_number": ..., "name": ..., "type": ...}],
         "members": [{"uuid": ..., "full_name": ..., "preferred_name": ...,
                      "unit_number": ..., "unit_name": ..., "sex": ..., "birth_date": ...,
                      # RECORDED PRIESTHOOD (2026-11-08): the raw /api/v5/sync payload
                      # carries households[].members[].priesthood (enum
                      # DEACON/TEACHER/PRIEST/ELDER/HIGH_PRIEST/BISHOP/SEVENTY/PATRIARCH/
                      # APOSTLE, absent = no current office) and ordinances[]
                      # ({type, date} — BAPTISM/CONFIRMATION/ENDOWMENT plus ORDAIN_*
                      # dates). These are the ONLY LCR-recorded priesthood signal in
                      # the bulk pull, and they were previously dropped here, so a pull
                      # could not tell whether an MP ordination had been recorded.
                      # Keep them verbatim.
                      "priesthood": "ELDER" | None,
                      "ordinances": [{"type": ..., "date": ...}],
                      "positions": [{"name": ..., "unit_number": ..., "unit_name": ...,
                                     "set_apart": bool}],
                      "recommends": [{"status": ..., "type": ..., "expiration": ...,
                                      "raw": {full raw sync record incl. recommendNumber,
                                              mobile/paper format flags}}],
                      "recommend_in_process": bool}]
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
    on every run instead of storing it, so each run is self-contained. Pass a
    stored one via MEMBERTOOLS_REFRESH_TOKEN to skip the Okta login entirely
    (refresh() needs no session); an expired/invalid token falls back to the
    Okta login with a warning, it never aborts the pull.
  - The daily sync's stored token (Supabase, encrypted) is NOT retrievable
    locally — the CI daily sync remains the canonical fresh-capture route,
    and --from-raw is the local bridge from its raw-sync artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tools" / "output" / "stake_data.json"
RAW_OUT = ROOT / "tools" / "output" / "stake_data_raw.json"

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
# Known plural container keys — keep their raw values verbatim (list-of-dict
# shape), since the scalar filter below would drop them.
KEEP_RAW_KEYS = ("emails", "phones", "addresses", "coordinates")


def _contact_fields(d: dict) -> dict:
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        kl = str(k).lower()
        if kl in KEEP_RAW_KEYS:
            out[k] = v
            continue
        if any(n in kl for n in CONTACT_NEEDLES):
            if isinstance(v, (str, int)):
                out[k] = v
            elif isinstance(v, list) and v and all(isinstance(x, (str, int)) for x in v):
                out[k] = v
    return out


def _priesthood_fields(member: dict) -> dict:
    """Recorded priesthood from the raw sync member record.

    priesthood: direct enum (DEACON/TEACHER/PRIEST/ELDER/HIGH_PRIEST/BISHOP/
    SEVENTY/PATRIARCH/APOSTLE) or None when the key is absent (no office).
    ordinances: [{type, date}] verbatim — the bulk payload's ordinance list
    carries BAPTISM/CONFIRMATION/ENDOWMENT dates AND ORDAIN_* dates
    (ORDAIN_DEACON/TEACHER/PRIEST/ELDER/...), so both the office enum and the
    ordination date are recorded signals (the office changes e.g. PRIEST ->
    ELDER once Dave records it in LCR, and the ORDAIN_ELDER date appears).
    """
    office = member.get("priesthood")
    ords = []
    for o in member.get("ordinances") or []:
        if isinstance(o, dict) and o.get("type"):
            ords.append({"type": o.get("type"), "date": o.get("date")})
    return {
        "priesthood": office if isinstance(office, str) else None,
        "ordinances": ords,
    }


def _positions(member: dict, unit_names: dict[int, str]) -> list[dict]:
    out = []
    for pos in member.get("positions") or []:
        if not isinstance(pos, dict):
            continue
        name = pos.get("name")
        punit = pos.get("unitNumber")
        if not name or punit is None:
            continue
        try:
            punit_int = int(punit)
        except (TypeError, ValueError):
            continue
        out.append({
            "name": str(name),
            "unit_number": punit_int,
            "unit_name": unit_names.get(punit_int),
            "set_apart": bool(pos.get("setApart")),
        })
    return out


def _fetch_payload(*, save_raw: str | Path | None) -> dict:
    """Whole-stake /api/v5/sync payload, token-first.

    1. MEMBERTOOLS_REFRESH_TOKEN env -> membertools.refresh() (no session).
    2. Else headless Okta login -> mint a Member Tools token off the session.
    The raw payload is saved verbatim (save_raw path, or RAW_OUT by default)
    unless save_raw is False.
    """
    refresh_token = (os.getenv("MEMBERTOOLS_REFRESH_TOKEN") or "").strip()
    access_token = None
    if refresh_token:
        try:
            tok = membertools.refresh(refresh_token)
            access_token = tok.get("access_token")
            if access_token:
                print("[+] access token renewed from MEMBERTOOLS_REFRESH_TOKEN (no login)")
        except membertools.MemberToolsError as exc:
            print(f"[!] stored refresh token unusable ({exc}) — falling back to Okta login")
    if not access_token:
        # LCR session (headless login only when no session file exists).
        session = LcrSession(auto_login=True)
        # Member Tools token, silently minted off the live Okta session.
        tok = membertools.mint_from_okta_session(session.session)
        access_token = tok.get("access_token")
        if not access_token:
            raise membertools.MemberToolsError("token mint returned no access_token")

    payload = membertools.fetch_sync(access_token)
    if save_raw is not False:
        raw_path = Path(save_raw) if save_raw else RAW_OUT
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"[+] raw /api/v5/sync payload saved -> {raw_path}")
    return payload


def pull(payload: dict | None = None, *, save_raw: str | Path | None = None) -> dict:
    """Normalize a /api/v5/sync payload into the local roster dict.

    payload: an already-fetched payload (e.g. from --from-raw); when None the
    payload is fetched live (token-first auth, see _fetch_payload).
    """
    t0 = datetime.now(timezone.utc)

    if payload is None:
        payload = _fetch_payload(save_raw=save_raw)

    stake_name, units = _units(payload)
    unit_names = {u["unit_number"]: u["name"] for u in units}

    # Temple-recommend roster: payload["templeRecommendStatus"][].recommends[]
    # is a unit-wide list keyed by memberUuid with raw statuses
    # (ACTIVE/EXPIRED/ISSUED/CANCELED). An ISSUED recommend is one the
    # bishopric has entered that still awaits stake activation -- i.e. the
    # member appears on LCR's "Recommend Activations" list, which means the
    # bishop interview already happened. We keep the raw records (plus a
    # convenience flag) because the label mapping elsewhere collapses
    # ISSUED into "No", which would lose exactly this signal.
    recommends_by_uuid: dict[str, list[dict]] = {}
    recommend_keys: set[str] = set()
    recommend_status_values: dict[str, int] = {}
    recommend_unit_by_uuid: dict[str, object] = {}
    for unit in payload.get("templeRecommendStatus") or []:
        if not isinstance(unit, dict):
            continue
        for r in unit.get("recommends") or []:
            if not isinstance(r, dict):
                continue
            ruuid = r.get("memberUuid") or r.get("uuid")
            if not ruuid:
                continue
            recommend_keys.update(str(k) for k in r.keys())
            status_val = str(r.get("status"))
            recommend_status_values[status_val] = recommend_status_values.get(status_val, 0) + 1
            recommend_unit_by_uuid.setdefault(str(ruuid), unit.get("unitNumber"))
            # Keep the FULL raw record: earlier versions kept only
            # status/type/expiration, which silently dropped any other
            # fields the sync sends (e.g. a mobile/digital recommend
            # indicator). `raw` preserves everything for downstream checks.
            recommends_by_uuid.setdefault(str(ruuid), []).append({
                "status": r.get("status"),
                "type": r.get("type"),
                "expiration": r.get("expiration") or r.get("expirationDate"),
                "raw": r,
            })

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
            recs = recommends_by_uuid.get(str(uuid), [])
            members.append({
                "uuid": uuid,
                "full_name": full,
                "preferred_name": _preferred_name(m, full),
                "unit_number": unum,
                "unit_name": unit_names.get(int(unum)) if unum is not None else None,
                "sex": m.get("sex"),
                "birth_date": m.get("birthDate") or m.get("birth_date"),
                **_priesthood_fields(m),
                "contact": contact,
                "positions": _positions(m, unit_names),
                "recommends": recs,
                "recommend_in_process": any(
                    (r.get("status") or "").upper() == "ISSUED" for r in recs),
            })

    leadership = {str(k): v for k, v in staffing_by_unit(payload).items()}

    # Recommends whose memberUuid matched no directory member — kept visible
    # so a keying mismatch can never silently swallow someone's recommend.
    member_uuids = {str(m["uuid"]) for m in members}
    orphan_recommends = [
        {
            "uuid": ruuid,
            "unit_number": recommend_unit_by_uuid.get(ruuid),
            "unit_name": unit_names.get(int(recommend_unit_by_uuid[ruuid]))
            if recommend_unit_by_uuid.get(ruuid) is not None else None,
            "records": recs,
        }
        for ruuid, recs in recommends_by_uuid.items()
        if ruuid not in member_uuids
    ]

    data = {
        "meta": {
            "stake": stake_name,
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "pull_seconds": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
            "members": len(members),
            "units": len(units),
            "recommend_keys": sorted(recommend_keys),
            "recommend_status_values": recommend_status_values,
            "recommends_total": sum(len(v) for v in recommends_by_uuid.values()),
            "recommends_orphaned": len(orphan_recommends),
        },
        "orphan_recommends": orphan_recommends,
        "contact_key_inventory": sorted(key_inventory),
        "units": units,
        "members": members,
        "leadership": leadership,
    }
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull the whole stake into tools/output/stake_data.json.")
    parser.add_argument("--from-raw", metavar="PATH",
                        help="normalize a saved raw /api/v5/sync payload instead of "
                             "logging in (e.g. the daily-sync raw-sync artifact)")
    parser.add_argument("--save-raw", metavar="PATH", default=None,
                        help="where to save the raw payload on a live pull "
                             f"(default: {RAW_OUT})")
    parser.add_argument("--no-save-raw", action="store_true",
                        help="do not save the raw payload on a live pull")
    args = parser.parse_args(argv)
    if args.from_raw:
        payload = json.loads(Path(args.from_raw).read_text(encoding="utf-8"))
        data = pull(payload)
    else:
        data = pull(save_raw=False if args.no_save_raw else args.save_raw)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    meta = data["meta"]
    print(f"[+] {meta['members']} members, {meta['units']} units, "
          f"{sum(len(v) for v in data['leadership'].values())} leadership callings "
          f"-> {OUT} ({meta['pull_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
