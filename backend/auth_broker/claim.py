"""
"I'm a leader, but I signed in with a different email" — the secure self-service claim (0065).

RLS matches a role row by verified email. A leader whose app sign-in address differs from the one we
hold resolves to NO scope and sees an empty app; their only route today is to track down a stake
leader and ask for an invite. (Migration 0063 fixed the case where we never learned an address at
all; this covers the case where we hold a DIFFERENT one.)

The flow, and why each step is safe:

  1. LOOKUP — a signed-in, scope-less user gives their first + last name. We search the leadership
     roster (`units.staffing`: person + person_uuid per unit) for a leader of that name who actually
     holds a calling-derived `user_roles` row.
  2. SEND — if we have an email on record for that person, we mail a single-use link THERE, and tell
     the claimant only a masked hint. The secret never goes to the address making the request, so a
     stranger who guesses a name receives nothing and learns nothing they could act on.
  3. VERIFY — clicking the link (while signed in as the same claimant) clones the matched leader's
     EXISTING rows onto the claimant's address: same stake, same unit, same role. It can never grant
     more than that leader already holds — the `invite_power_user` principle.

Tokens are stored hashed, are single-use, and expire. An ambiguous name (two matches) is refused
rather than guessed at. Every attempt is audited, matched or not, so a name-guessing spree is visible
to an admin.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from lcr_client.logging_setup import get_logger

from . import admin

logger = get_logger()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
_TIMEOUT = 15

#: How long a verification link stays usable. Short on purpose — the claimant is sitting in front of
#: the app when they ask for it, and a stale link in an inbox is a standing liability.
TOKEN_TTL_MINUTES = 30

#: Per-claimant cap over the audit window, so the flow can't be used to probe names at scale.
MAX_ATTEMPTS_PER_DAY = 5


class ClaimError(Exception):
    """Something the caller should see (bad input, rate limit, expired link)."""


def _headers() -> dict:
    if not (SUPABASE_URL and SERVICE_KEY):
        raise ClaimError("supabase not configured")
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


def _rows(table: str, params: dict) -> list[dict]:
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=_headers(),
                     params=params, timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise ClaimError(f"{table} read failed ({r.status_code})")
    return r.json() or []


def _insert(table: str, body: dict, *, returning: bool = True) -> dict | None:
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}",
                      headers={**_headers(), "Content-Type": "application/json",
                               "Prefer": "return=representation" if returning else "return=minimal"},
                      json=body, timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise ClaimError(f"{table} insert failed ({r.status_code}): {r.text[:160]}")
    rows = r.json() if returning and r.text else []
    return rows[0] if rows else None


def _patch(table: str, params: dict, body: dict) -> None:
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/{table}",
                       headers={**_headers(), "Content-Type": "application/json",
                                "Prefer": "return=minimal"},
                       params=params, json=body, timeout=_TIMEOUT)
    if r.status_code >= 300:
        raise ClaimError(f"{table} update failed ({r.status_code}): {r.text[:160]}")


# --- name matching ------------------------------------------------------------------------------

def normalize_name(s: str | None) -> str:
    """Casefold + strip accents/punctuation so "Sanhueza" matches "Sánchez"-style diacritics and
    "O'Brien" matches "OBrien". Deliberately loose on FORM, never on identity."""
    s = unicodedata.normalize("NFKD", (s or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip().casefold()


def name_matches(roster_name: str | None, first: str, last: str) -> bool:
    """Does the roster's "Surname, Given Middle" entry name this person?

    The surname must match exactly (normalized). The given name matches if the claimant's first name
    is any one of the recorded given names — so "Reed" matches "Hunsaker, Reed Garrett", and someone
    who goes by their middle name still gets in. We never match on surname alone."""
    raw = (roster_name or "").strip()
    if "," not in raw:
        return False
    surname, _, given = raw.partition(",")
    nf, nl = normalize_name(first), normalize_name(last)
    if not nf or not nl or normalize_name(surname) != nl:
        return False
    return nf in set(normalize_name(given).split())


def _staffing_candidates(first: str, last: str) -> list[dict]:
    """Every leadership-roster entry matching this name, as {person_uuid, person, unit_name}.

    De-duped by person_uuid: one leader can hold several callings across several rows, and that is
    ONE candidate — counting them separately would make every multi-calling leader look ambiguous."""
    out: dict[str, dict] = {}
    for unit in _rows("units", {"select": "name,staffing", "staffing": "not.is.null"}):
        for row in (unit.get("staffing") or []):
            if not isinstance(row, dict):
                continue
            uuid_, person = row.get("person_uuid"), row.get("person")
            if uuid_ and person and name_matches(person, first, last):
                out.setdefault(uuid_, {"person_uuid": uuid_, "person": person,
                                       "unit_name": unit.get("name")})
    return list(out.values())


def _roles_for(person_uuid: str) -> list[dict]:
    return _rows("user_roles", {
        "select": "id,stake_id,unit_id,role,email,calling_name",
        "lcr_person_uuid": f"eq.{person_uuid}"})


def _email_on_record(person_uuid: str, roles: list[dict]) -> str | None:
    """The address we already hold for this leader: whatever is on their role rows, else the verified
    email of a Church login bound to the same person uuid (`church_identities`, 0043)."""
    for r in roles:
        if (r.get("email") or "").strip():
            return r["email"].strip().lower()
    ident = _rows("church_identities", {"select": "email", "cmis_uuid": f"eq.{person_uuid}",
                                        "limit": "1"})
    email = (ident[0].get("email") if ident else "") or ""
    return email.strip().lower() or None


def mask_email(email: str) -> str:
    """`reed.hunsaker@gmail.com` -> `re•••••@g•••.com`. Enough for the owner to know which inbox to
    open, not enough for anyone else to reconstruct the address."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "•••"
    dom, _, tld = domain.rpartition(".")
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}{'•' * max(3, len(local) - len(keep))}@{dom[:1]}{'•' * 3}.{tld}"


# --- the flow -----------------------------------------------------------------------------------

def _audit(claimant: str, first: str, last: str, status: str, **extra) -> dict | None:
    body = {"claimant_email": claimant, "first_name": first[:80], "last_name": last[:80],
            "status": status, **extra}
    try:
        return _insert("role_claims", body)
    except ClaimError as exc:  # auditing must never break the flow
        logger.warning("role_claims audit failed: %s", exc)
        return None


def _recent_attempts(claimant: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return len(_rows("role_claims", {"select": "id", "claimant_email": f"eq.{claimant}",
                                     "at": f"gte.{since}", "limit": "50"}))


def _claim_email_html(name: str, calling: str | None, claimant: str, link: str) -> str:
    from html import escape
    role_line = (f"<p>Recorded calling: <b>{escape(calling)}</b></p>" if calling else "")
    return (
        f"<h2>Confirm your Covenant Path access</h2>"
        f"<p>Hello {escape(name)},</p>"
        f"<p>Someone signed in to Covenant Path as "
        f"<b>{escape(claimant)}</b> and asked to link that address to your leadership access.</p>"
        f"{role_line}"
        f"<p><b>If that was you</b>, confirm within {TOKEN_TTL_MINUTES} minutes:</p>"
        f"<p><a href=\"{escape(link)}\">Confirm and link my access</a></p>"
        f"<p><b>If it wasn't you</b>, do nothing — the link expires on its own and no access is "
        f"granted. You may want to tell your stake leadership someone tried.</p>"
        f"<p style='color:#666'>This link works once and only grants the access you already have.</p>")


def start_claim(claimant_email: str, first: str, last: str) -> dict:
    """Step 1+2: match the name, then mail a single-use link to the address ON RECORD.

    The reply deliberately reveals only a MASKED hint, and an unmatched name is reported as such
    without saying which part failed. Ambiguity (two different people of the same name) is refused
    rather than guessed."""
    claimant = (claimant_email or "").strip().lower()
    first, last = (first or "").strip(), (last or "").strip()
    if not claimant or "@" not in claimant:
        raise ClaimError("sign in first")
    if len(first) < 2 or len(last) < 2:
        raise ClaimError("Enter your first and last name as they appear in Church records.")
    if _recent_attempts(claimant) >= MAX_ATTEMPTS_PER_DAY:
        raise ClaimError("Too many attempts today. Ask your stake leader to invite you directly.")

    candidates = _staffing_candidates(first, last)
    # Only leaders who actually hold a role are claimable — this flow links an EXISTING scope, it
    # never creates one.
    claimable = [(c, r) for c in candidates if (r := _roles_for(c["person_uuid"]))]

    if len(claimable) != 1:
        _audit(claimant, first, last, "no_match")
        # Same answer for "no such leader" and "two of them": neither should confirm a name exists.
        return {"status": "no_match"}

    cand, roles = claimable[0]
    on_record = _email_on_record(cand["person_uuid"], roles)
    if not on_record:
        _audit(claimant, first, last, "no_email_on_record",
               matched_person_uuid=cand["person_uuid"], matched_name=cand["person"])
        return {"status": "no_email_on_record", "unit_name": cand.get("unit_name")}

    if on_record == claimant:
        # Already the address on file — nothing to verify. (0063's triggers should have bound it; say
        # so plainly instead of mailing them a pointless link.)
        _audit(claimant, first, last, "consumed", matched_person_uuid=cand["person_uuid"],
               matched_name=cand["person"], sent_to_email=on_record)
        return {"status": "already_on_record"}

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)
    _audit(claimant, first, last, "sent",
           matched_person_uuid=cand["person_uuid"], matched_name=cand["person"],
           sent_to_email=on_record, token_hash=hashlib.sha256(token.encode()).hexdigest(),
           expires_at=expires.isoformat())

    app_url = (os.environ.get("APP_URL") or "").rstrip("/")
    link = f"{app_url}/claim?token={token}"
    given = (cand["person"].partition(",")[2] or cand["person"]).strip()
    try:
        admin._send_email(on_record, "Confirm your Covenant Path access",
                          _claim_email_html(given, (roles[0] or {}).get("calling_name"),
                                            claimant, link))
    except Exception as exc:  # noqa: BLE001 — never leak mail-provider detail to the caller
        logger.warning("claim email failed: %s", exc)
        raise ClaimError("Could not send the confirmation email. Try again later.") from exc

    return {"status": "sent", "hint": mask_email(on_record), "unit_name": cand.get("unit_name")}


def complete_claim(token: str, claimant_email: str) -> dict:
    """Step 3: consume the link and clone the matched leader's roles onto the claimant's address.

    Must be called by the SAME signed-in address that started the claim — holding the link is not by
    itself authority to attach an arbitrary account."""
    claimant = (claimant_email or "").strip().lower()
    tok = (token or "").strip()
    if not tok:
        raise ClaimError("Missing confirmation link.")
    digest = hashlib.sha256(tok.encode()).hexdigest()
    rows = _rows("role_claims", {
        "select": "id,claimant_email,matched_person_uuid,matched_name,expires_at,consumed_at",
        "token_hash": f"eq.{digest}", "limit": "1"})
    if not rows:
        raise ClaimError("That confirmation link isn't valid.")
    claim = rows[0]
    if claim.get("consumed_at"):
        raise ClaimError("That confirmation link has already been used.")
    expires = (claim.get("expires_at") or "").replace("Z", "+00:00")
    if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
        _patch("role_claims", {"id": f"eq.{claim['id']}"}, {"status": "expired"})
        raise ClaimError("That confirmation link has expired. Start again.")
    if (claim.get("claimant_email") or "").lower() != claimant:
        # The link belongs to a different sign-in; refuse rather than re-target it.
        raise ClaimError("Sign in with the address that requested this link, then open it again.")

    person_uuid = claim.get("matched_person_uuid") or ""
    source_roles = _roles_for(person_uuid)
    if not source_roles:
        raise ClaimError("That leader no longer holds a calling with access.")

    # Clone scope — never more than the matched leader already holds. The rows are keyed by EMAIL
    # with a NULL lcr_person_uuid, so provision_roles (which only deletes calling-derived rows) and
    # 0063's identity triggers both leave them alone.
    granted = 0
    for r in source_roles:
        body = {"stake_id": r["stake_id"], "unit_id": r.get("unit_id"), "role": r["role"],
                "email": claimant, "source": "claim",
                "calling_name": r.get("calling_name"), "invited_by_email": "self-claim"}
        try:
            requests.post(f"{SUPABASE_URL}/rest/v1/user_roles",
                          headers={**_headers(), "Content-Type": "application/json",
                                   "Prefer": "resolution=merge-duplicates,return=minimal"},
                          json=body, timeout=_TIMEOUT)
            granted += 1
        except requests.RequestException as exc:
            logger.warning("claim grant failed for role %s: %s", r.get("id"), exc)

    _patch("role_claims", {"id": f"eq.{claim['id']}"},
           {"consumed_at": datetime.now(timezone.utc).isoformat(), "status": "consumed",
            "granted_roles": granted, "token_hash": None})  # burn the token
    logger.info("claim consumed: %s granted %d role row(s)", claimant, granted)
    return {"status": "linked", "granted": granted, "name": claim.get("matched_name")}
