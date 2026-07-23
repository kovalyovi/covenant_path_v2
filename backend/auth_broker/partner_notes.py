"""
Partner notes API — the Mission-KPIs app reads/writes member notes from OUR database.

Ricky's Mission-KPIs iOS app kept per-person notes as one markdown doc in a Google Sheet behind
an Apps Script web app (his docs/notes-backend.gs). This lane replaces that store with our
`member_comments` THREAD (the same table our web renders, D38/D59), so both apps see one
conversation per person. Trust model mirrors his existing one — a single shared token that ships
in the client — carried in the `X-Partner-Token` header and compared constant-time against
`PARTNER_NOTES_TOKEN` (unset ⇒ the whole lane answers 503, so it's off until a token is issued).
The person uuid is the LCR person UUID both systems already share.

Contract (real HTTP status codes — not the Apps Script 200-always envelope):
  GET    /partner/notes/{uuid}          -> 200 {entries: [{id, body, author, created_at, updated_at}]}
  POST   /partner/notes/{uuid}          {body, author?, client_id?} -> 200 {entry}
                                           400 empty body · 413 body over 32 KB
  POST   /partner/notes/{uuid}/update   {id, body, author?} -> 200 {entry}   (edit an entry in place)
  POST   /partner/notes/{uuid}/delete   {id} -> 200 {deleted: true}          (idempotent)

A note can be added/read for a person who ISN'T synced yet (no `members` row) — we no longer 404. When
the member is unknown we store a "pending" comment (null stake_id) that the daily sync later ADOPTS into
the right stake (db.adopt_orphan_notes); if the person once had comments we inherit their stake from
those so a transient sync gap doesn't hide new notes. Rationale: the operator's LCR calling can change
for a few days, dropping a person from the sync — a leader must still be able to record notes on them.

Writes go through the Supabase service-role REST (the broker has no psycopg2 — same as reports.py);
attribution keeps partner writes distinguishable: author_email is a fixed partner marker and the
author display name comes from the app (the signed-in leader).
"""

from __future__ import annotations

import hmac
import os

import requests

from backend.auth_broker import admin

_TIMEOUT = 15
MAX_BODY_BYTES = 32 * 1024  # parity with his Apps Script backend's markdown cap
PARTNER_EMAIL = "mission-kpis@partner.membercovenantpath.org"


class PartnerError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def check_token(presented: str | None) -> None:
    expected = os.environ.get("PARTNER_NOTES_TOKEN", "")
    if not expected:
        raise PartnerError(503, "partner notes lane is not configured")
    if not hmac.compare_digest((presented or "").strip(), expected):
        raise PartnerError(401, "invalid partner token")


def _member(uuid: str) -> dict | None:
    return admin._one("members", {"select": "person_uuid,stake_id,unit_id",
                                  "person_uuid": f"eq.{uuid}", "limit": "1"})


def _scope_for(uuid: str) -> tuple[str | None, str | None]:
    """The (stake_id, unit_id) a new comment for this person should carry. The member's own scope if
    they're synced; else inherit from an existing comment for this uuid (so a person who dropped out of
    the sync keeps their notes visible to the same leaders); else (None, None) — a PENDING comment the
    daily sync adopts once the real record appears."""
    member = _member(uuid)
    if member:
        return member["stake_id"], member.get("unit_id")
    prior = admin._one("member_comments", {"select": "stake_id,unit_id",
                                           "member_person_uuid": f"eq.{uuid}",
                                           "stake_id": "not.is.null", "limit": "1"})
    if prior:
        return prior.get("stake_id"), prior.get("unit_id")
    return None, None


def list_entries(uuid: str) -> dict:
    # No existence gate: a person who isn't synced yet may still have (pending) notes to read.
    r = requests.get(f"{admin.SUPABASE_URL}/rest/v1/member_comments",
                     headers=admin._sb_headers(),
                     params={"select": "id,body,author_name,author_email,created_at,updated_at",
                             "member_person_uuid": f"eq.{uuid}",
                             "order": "created_at.asc", "limit": "500"},
                     timeout=_TIMEOUT)
    if r.status_code != 200:
        raise PartnerError(502, f"could not load notes ({r.status_code})")
    entries = [{
        "id": row["id"],
        "body": row["body"],
        # One display string — the partner app shouldn't care about our email-vs-name split.
        "author": row.get("author_name") or row.get("author_email") or "Leader",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    } for row in r.json()]
    return {"entries": entries}


def add_entry(uuid: str, body: str, author: str | None) -> dict:
    text = (body or "").strip()
    if not text:
        raise PartnerError(400, "note body is required")
    if len(text.encode("utf-8")) > MAX_BODY_BYTES:
        raise PartnerError(413, "note is too large (32 KB max)")
    stake_id, unit_id = _scope_for(uuid)  # (None, None) => a pending note, adopted on the next sync
    row = {
        "stake_id": stake_id,
        "unit_id": unit_id,
        "member_person_uuid": uuid,
        "author_email": PARTNER_EMAIL,
        "author_name": (author or "").strip()[:120] or "Mission KPIs leader",
        "body": text,
    }
    r = requests.post(f"{admin.SUPABASE_URL}/rest/v1/member_comments",
                      headers={**admin._sb_headers(), "Prefer": "return=representation"},
                      json=row, timeout=_TIMEOUT)
    if r.status_code not in (200, 201):
        raise PartnerError(502, f"could not save the note ({r.status_code})")
    saved = (r.json() or [{}])[0]
    return {"entry": {
        "id": saved.get("id"),
        "body": saved.get("body", text),
        "author": saved.get("author_name") or row["author_name"],
        "created_at": saved.get("created_at"),
        "updated_at": saved.get("updated_at"),
    }}


def update_entry(uuid: str, entry_id: str, body: str, author: str | None) -> dict:
    """Edit one thread entry in place (his UI needs to edit, not just add/delete). Scoped to the uuid so
    a leaked id can only ever touch a comment on the person it belongs to; stamps updated_at/updated_by."""
    if not (entry_id or "").strip():
        raise PartnerError(400, "entry id is required")
    text = (body or "").strip()
    if not text:
        raise PartnerError(400, "note body is required")
    if len(text.encode("utf-8")) > MAX_BODY_BYTES:
        raise PartnerError(413, "note is too large (32 KB max)")
    patch = {"body": text, "updated_at": "now()", "updated_by": PARTNER_EMAIL}
    if (author or "").strip():
        patch["author_name"] = author.strip()[:120]
    r = requests.patch(f"{admin.SUPABASE_URL}/rest/v1/member_comments",
                       headers={**admin._sb_headers(), "Prefer": "return=representation"},
                       params={"id": f"eq.{entry_id}", "member_person_uuid": f"eq.{uuid}"},
                       json=patch, timeout=_TIMEOUT)
    if r.status_code not in (200, 204):
        raise PartnerError(502, f"could not update the note ({r.status_code})")
    rows = r.json() if r.status_code == 200 else []
    if not rows:
        raise PartnerError(404, "note not found")
    saved = rows[0]
    return {"entry": {
        "id": saved.get("id"),
        "body": saved.get("body", text),
        "author": saved.get("author_name") or PARTNER_EMAIL,
        "created_at": saved.get("created_at"),
        "updated_at": saved.get("updated_at"),
    }}


def delete_entry(uuid: str, entry_id: str) -> dict:
    if not (entry_id or "").strip():
        raise PartnerError(400, "entry id is required")
    # Scoped to the uuid so a leaked id can only ever delete within the person it belongs to.
    r = requests.delete(f"{admin.SUPABASE_URL}/rest/v1/member_comments",
                        headers=admin._sb_headers(),
                        params={"id": f"eq.{entry_id}", "member_person_uuid": f"eq.{uuid}"},
                        timeout=_TIMEOUT)
    if r.status_code not in (200, 204):
        raise PartnerError(502, f"could not delete the note ({r.status_code})")
    return {"deleted": True}
