"""
Partner data API — the Mission-KPIs app reads/writes OUR transfer dates, ward goals, and manual
baptism candidates, so both apps share one source of truth (the sibling of partner_notes.py).

Ricky's app previously kept these in its own Google Sheet tabs (transfer_dates / ward_goals /
manual_people). These lanes replace that store with OUR Postgres tables (transfer_dates, ward_goals,
manual_members), which the web edits too. Same trust model as the notes lane — a single shared
`X-Partner-Token` (unset ⇒ the lane 503s = off) — and the same service-role REST access (the broker
has no psycopg2). The partner token is not stake-scoped, so a single mission stake is resolved from
`PARTNER_STAKE_UNIT` (default Raleigh 503991); his `unit_number`s are mapped to our `unit_id`s.

Contract (real HTTP status codes):
  GET  /partner/transfer-dates                      -> 200 {transfers: [{transfer_id, transfer_date}]}
  POST /partner/transfer-dates    {transfer_date, transfer_id?} -> 200 {transfer}
  POST /partner/transfer-dates/delete {transfer_id} -> 200 {deleted: true}

  GET  /partner/ward-goals                          -> 200 {goals: [{unit_number, unit_name, transfer_id, goal, updated_at, updated_by}]}
  POST /partner/ward-goals   {unit_number, transfer_id, goal, unit_name?} -> 200 {goal}
  POST /partner/ward-goals/delete {unit_number, transfer_id} -> 200 {deleted: true}

  GET  /partner/manual-people                       -> 200 {people: [{uuid, first_name, last_initial, baptism_date, unit_number, unit_name, notes, updated_at}]}
  POST /partner/manual-people {first_name, last_initial?, baptism_date?, unit_number?, unit_name?, notes?, uuid?} -> 200 {person}
  POST /partner/manual-people/delete {uuid}         -> 200 {deleted: true}
"""

from __future__ import annotations

import os

import requests

from backend.auth_broker import admin
from backend.auth_broker.partner_notes import PartnerError  # same error type + token guard as the notes lane

_TIMEOUT = 15
_PARTNER_UPDATER = "mission-kpis@partner.membercovenantpath.org"


def _stake_unit() -> str:
    return os.environ.get("PARTNER_STAKE_UNIT", "503991").strip() or "503991"


def _stake_id() -> str:
    """The stake this partner writes to (its mission's stake). 404s the whole lane if it isn't synced."""
    row = admin._one("stakes", {"select": "id", "unit_number": f"eq.{_stake_unit()}", "limit": "1"})
    if not row:
        raise PartnerError(404, "partner stake is not set up on Covenant Path")
    return row["id"]


def _get(table: str, params: dict) -> list[dict]:
    r = requests.get(f"{admin.SUPABASE_URL}/rest/v1/{table}", headers=admin._sb_headers(),
                     params=params, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise PartnerError(502, f"could not load {table} ({r.status_code})")
    return r.json() or []


def _upsert(table: str, on_conflict: str, row: dict) -> dict:
    r = requests.post(f"{admin.SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}",
                      headers={**admin._sb_headers(), "Prefer": "resolution=merge-duplicates,return=representation"},
                      json=row, timeout=_TIMEOUT)
    if r.status_code not in (200, 201):
        raise PartnerError(502, f"could not save {table} ({r.status_code})")
    return (r.json() or [{}])[0]


def _delete(table: str, params: dict) -> None:
    r = requests.delete(f"{admin.SUPABASE_URL}/rest/v1/{table}", headers=admin._sb_headers(),
                        params=params, timeout=_TIMEOUT)
    if r.status_code not in (200, 204):
        raise PartnerError(502, f"could not delete from {table} ({r.status_code})")


def _units_by_number(stake_id: str) -> dict[int, dict]:
    """unit_number -> {id, name} for the partner stake, so his unit_number maps to our unit_id."""
    rows = _get("units", {"select": "id,unit_number,name", "stake_id": f"eq.{stake_id}"})
    out: dict[int, dict] = {}
    for r in rows:
        n = r.get("unit_number")
        if n is not None:
            out[int(n)] = {"id": r["id"], "name": r.get("name")}
    return out


def _unit_number_by_id(stake_id: str) -> dict[str, int]:
    return {v["id"]: n for n, v in _units_by_number(stake_id).items()}


# --- transfer dates ---------------------------------------------------------

def list_transfers() -> dict:
    stake_id = _stake_id()
    rows = _get("transfer_dates", {"select": "transfer_id,transfer_date",
                                   "stake_id": f"eq.{stake_id}", "order": "transfer_date.asc"})
    return {"transfers": [{"transfer_id": r["transfer_id"], "transfer_date": r["transfer_date"]} for r in rows]}


def set_transfer(transfer_date: str, transfer_id: str | None) -> dict:
    date = (transfer_date or "").strip()
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise PartnerError(400, "transfer_date must be YYYY-MM-DD")
    tid = (transfer_id or "").strip() or f"t-{date}"
    stake_id = _stake_id()
    row = _upsert("transfer_dates", "stake_id,transfer_id",
                  {"stake_id": stake_id, "transfer_id": tid, "transfer_date": date,
                   "updated_by": _PARTNER_UPDATER, "updated_at": "now()"})
    return {"transfer": {"transfer_id": row.get("transfer_id", tid), "transfer_date": row.get("transfer_date", date)}}


def delete_transfer(transfer_id: str) -> dict:
    if not (transfer_id or "").strip():
        raise PartnerError(400, "transfer_id is required")
    _delete("transfer_dates", {"stake_id": f"eq.{_stake_id()}", "transfer_id": f"eq.{transfer_id}"})
    return {"deleted": True}


# --- ward goals -------------------------------------------------------------

def list_ward_goals() -> dict:
    stake_id = _stake_id()
    num_by_id = _unit_number_by_id(stake_id)
    rows = _get("ward_goals", {"select": "unit_id,unit_number,unit_name,transfer_id,goal,updated_at,updated_by",
                               "stake_id": f"eq.{stake_id}"})
    # unit_number may be null on rows the WEB created (it writes unit_id only) — resolve it from unit_id
    # so the partner always receives a unit_number (Ricky's app keys ward goals on it).
    goals = []
    for r in rows:
        goals.append({
            "unit_number": r.get("unit_number") if r.get("unit_number") is not None
            else num_by_id.get(r.get("unit_id")),
            "unit_name": r.get("unit_name"),
            "transfer_id": r.get("transfer_id"),
            "goal": r.get("goal"),
            "updated_at": r.get("updated_at"),
            "updated_by": r.get("updated_by"),
        })
    return {"goals": goals}


def set_ward_goal(unit_number: int | None, transfer_id: str, goal: int, unit_name: str | None) -> dict:
    if unit_number is None:
        raise PartnerError(400, "unit_number is required")
    if not (transfer_id or "").strip():
        raise PartnerError(400, "transfer_id is required")
    stake_id = _stake_id()
    unit = _units_by_number(stake_id).get(int(unit_number))
    if not unit:
        raise PartnerError(404, f"unit {unit_number} is not in this stake")
    row = _upsert("ward_goals", "stake_id,unit_id,transfer_id",
                  {"stake_id": stake_id, "unit_id": unit["id"], "unit_number": int(unit_number),
                   "unit_name": unit_name or unit.get("name"), "transfer_id": transfer_id.strip(),
                   "goal": int(goal), "updated_by": _PARTNER_UPDATER, "updated_at": "now()"})
    return {"goal": {"unit_number": int(unit_number), "unit_name": row.get("unit_name"),
                     "transfer_id": row.get("transfer_id", transfer_id), "goal": row.get("goal", int(goal))}}


def delete_ward_goal(unit_number: int | None, transfer_id: str) -> dict:
    if unit_number is None or not (transfer_id or "").strip():
        raise PartnerError(400, "unit_number and transfer_id are required")
    stake_id = _stake_id()
    unit = _units_by_number(stake_id).get(int(unit_number))
    if not unit:
        return {"deleted": True}  # nothing to delete for an unknown unit (idempotent)
    _delete("ward_goals", {"stake_id": f"eq.{stake_id}", "unit_id": f"eq.{unit['id']}",
                           "transfer_id": f"eq.{transfer_id}"})
    return {"deleted": True}


# --- manual people ----------------------------------------------------------

def _display_name(first: str, last_initial: str | None) -> str:
    li = (last_initial or "").strip()
    return f"{first.strip()} {li}".strip() if li else first.strip()


def list_manual_people() -> dict:
    stake_id = _stake_id()
    num_by_id = _unit_number_by_id(stake_id)
    rows = _get("manual_members",
                {"select": "id,name,first_name,last_initial,baptism_date,unit_id,unit_name,custom_notes,updated_at",
                 "stake_id": f"eq.{stake_id}", "merged_at": "is.null"})
    people = []
    for r in rows:
        people.append({
            "uuid": r["id"],
            "first_name": r.get("first_name") or (r.get("name") or "").split(" ")[0],
            "last_initial": r.get("last_initial"),
            "baptism_date": r.get("baptism_date"),
            "unit_number": num_by_id.get(r.get("unit_id")),
            "unit_name": r.get("unit_name"),
            "notes": r.get("custom_notes") or "",
            "updated_at": r.get("updated_at"),
        })
    return {"people": people}


def upsert_manual_person(first_name: str, last_initial: str | None, baptism_date: str | None,
                         unit_number: int | None, unit_name: str | None, notes: str | None,
                         uuid: str | None) -> dict:
    if not (first_name or "").strip():
        raise PartnerError(400, "first_name is required")
    stake_id = _stake_id()
    unit_id = None
    resolved_name = unit_name
    if unit_number is not None:
        unit = _units_by_number(stake_id).get(int(unit_number))
        if unit:
            unit_id, resolved_name = unit["id"], (unit_name or unit.get("name"))
    row = {
        "stake_id": stake_id,
        "unit_id": unit_id,
        "unit_name": resolved_name,
        "name": _display_name(first_name, last_initial),
        "first_name": first_name.strip(),
        "last_initial": (last_initial or "").strip() or None,
        "baptism_date": (baptism_date or "").strip() or None,
        "custom_notes": (notes or "").strip(),
        "created_by": _PARTNER_UPDATER,
        "updated_at": "now()",
    }
    if (uuid or "").strip():
        r = requests.patch(f"{admin.SUPABASE_URL}/rest/v1/manual_members",
                           headers={**admin._sb_headers(), "Prefer": "return=representation"},
                           params={"id": f"eq.{uuid}", "stake_id": f"eq.{stake_id}"},
                           json=row, timeout=_TIMEOUT)
        rows = r.json() if r.status_code == 200 else []
        if r.status_code in (200, 204) and rows:
            return {"person": {"uuid": rows[0].get("id", uuid)}}
        # fall through to insert if the uuid didn't match a row in this stake
    r = requests.post(f"{admin.SUPABASE_URL}/rest/v1/manual_members",
                      headers={**admin._sb_headers(), "Prefer": "return=representation"},
                      json=row, timeout=_TIMEOUT)
    if r.status_code not in (200, 201):
        raise PartnerError(502, f"could not save the person ({r.status_code})")
    saved = (r.json() or [{}])[0]
    return {"person": {"uuid": saved.get("id")}}


def delete_manual_person(uuid: str) -> dict:
    if not (uuid or "").strip():
        raise PartnerError(400, "uuid is required")
    _delete("manual_members", {"id": f"eq.{uuid}", "stake_id": f"eq.{_stake_id()}"})
    return {"deleted": True}
