"""
Email via Resend — invitation emails + per-leader daily digests.

Free-tier aware (Resend free ≈ 100/day, 3000/mo): a per-run cap, and each stake can
supply its OWN Resend key (stake_settings.resend_api_key_enc) so its mail draws on its
own quota instead of the shared one. Falls back to the shared env RESEND_API_KEY.

Secrets: RESEND_API_KEY / RESEND_FROM / APP_URL from env; per-stake key Fernet-encrypted
(same CP_TOKEN_KEY). Never logs keys.
"""

from __future__ import annotations

import os

import requests
from cryptography.fernet import Fernet

from lcr_client.logging_setup import get_logger
from lcr_client.token_store import _load_key

logger = get_logger()
RESEND_URL = "https://api.resend.com/emails"
DEFAULT_DAILY_CAP = 90  # stay under the shared free-tier 100/day
# Resend's API is behind Cloudflare, which 403s (error 1010) on default urllib/requests
# User-Agents — send a normal browser UA.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")


def _shared_key() -> str | None:
    return os.environ.get("RESEND_API_KEY") or None


def _from(stake_from: str | None = None) -> str:
    return stake_from or os.environ.get("RESEND_FROM") or "Covenant Path <onboarding@resend.dev>"


def _app_url() -> str:
    return os.environ.get("APP_URL", "https://your-viewer.example.com")  # placeholder until deployed


def stake_key(conn, stake_id: str) -> tuple[str | None, str | None]:
    """(api_key, from_email) for a stake — its own if set, else the shared defaults."""
    try:
        with conn.cursor() as cur:
            cur.execute("select resend_api_key_enc, email_from from stake_settings where stake_id=%s",
                        (stake_id,))
            row = cur.fetchone()
    except Exception:
        row = None
    if row and row[0]:
        try:
            key = Fernet(_load_key()).decrypt(row[0].encode("ascii")).decode("utf-8")
            return key, _from(row[1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("stake %s resend key decrypt failed, using shared: %s", stake_id, exc)
    return _shared_key(), _from(row[1] if row else None)


def send_email(to: str, subject: str, html: str, api_key: str | None = None,
               from_email: str | None = None) -> bool:
    key = api_key or _shared_key()
    if not key:
        logger.warning("no Resend API key; skipping email to %s", to)
        return False
    try:
        r = requests.post(RESEND_URL, json={"from": _from(from_email), "to": [to],
                          "subject": subject, "html": html}, timeout=30,
                          headers={"Authorization": f"Bearer {key}", "User-Agent": _UA})
        if r.status_code in (200, 201):
            logger.info("email -> %s: %s", to, r.status_code)
            return True
        logger.error("email -> %s failed: %s %s", to, r.status_code, r.text[:200])
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("email -> %s failed: %s", to, exc)
        return False


def _invite_html(stake_name: str, scope: str, invited_by: str | None) -> str:
    by = f" by {invited_by}" if invited_by else ""
    return (
        f"<h2>You've been given access to Covenant Path</h2>"
        f"<p>You were invited{by} to view covenant-path data for <b>{stake_name}</b> ({scope}).</p>"
        f"<p>Sign in at <a href=\"{_app_url()}\">{_app_url()}</a> using <b>this email address</b> "
        f"(a one-time code is emailed to you — no Church account required).</p>"
        f"<p>You'll see the same information your inviter can, and you can invite others.</p>"
    )


def send_pending_invitations(conn, cap: int = DEFAULT_DAILY_CAP) -> int:
    """Email queued invitations (invitations.emailed=false). Returns #sent."""
    with conn.cursor() as cur:
        cur.execute("""select i.id, i.invited_email, i.invited_by_email, s.name, i.stake_id, i.unit_id, i.role
                       from invitations i join stakes s on s.id=i.stake_id
                       where i.emailed=false and i.status<>'revoked' order by i.created_at limit %s""", (cap,))
        rows = cur.fetchall()
    sent = 0
    for inv_id, email, by, stake_name, stake_id, unit_id, role in rows:
        api_key, frm = stake_key(conn, stake_id)
        scope = "whole stake" if unit_id is None else "your unit"
        if send_email(email, f"Access to {stake_name} — Covenant Path",
                      _invite_html(stake_name, scope, by), api_key, frm):
            with conn.cursor() as cur:
                cur.execute("update invitations set emailed=true, status='active' where id=%s", (inv_id,))
            conn.commit()
            sent += 1
    logger.info("sent %d/%d pending invitations", sent, len(rows))
    return sent


def _digest_html(name: str, scope_label: str, total: int, by_milestone: list[tuple[str, int]]) -> str:
    items = "".join(f"<li>{label}: {n}/{total}</li>" for label, n in by_milestone)
    return (
        f"<h2>Covenant Path — daily summary</h2>"
        f"<p>{scope_label}: <b>{total}</b> new members.</p>"
        f"<p>Golden Hour completion:</p><ul>{items}</ul>"
        f"<p><a href=\"{_app_url()}\">Open the dashboard</a></p>"
    )


# milestone label -> SQL predicate over the members row (mirrors the app's Golden Hour)
_DIGEST_MILESTONES = [
    ("Friends", "friends='Yes'"), ("Calling", "calling='Yes'"),
    ("Has ministers", "ministering_brothers_sisters='Yes'"),
    ("Ministers", "ministering_assignment='Yes'"),
    ("Temple recommend", "temple_recommend='Active'"),
    ("Patriarchal", "patriarchal_blessing='Yes'"),
]


def send_digests(conn, cap: int = DEFAULT_DAILY_CAP) -> int:
    """One digest per leader (by email), summarizing their RLS scope. Free-tier capped.

    NOTE: Resend's shared test sender (onboarding@resend.dev) only delivers to the
    account owner — real-recipient delivery needs a verified domain (RESEND_FROM).
    """
    with conn.cursor() as cur:
        cur.execute("""select lower(email) as email, bool_or(unit_id is null) as stake_wide,
                              array_remove(array_agg(distinct unit_id), null) as units,
                              max(stake_id::text) as stake_id
                       from user_roles where email is not null group by lower(email) limit %s""", (cap,))
        leaders = cur.fetchall()
    sent = 0
    for email, stake_wide, units, stake_id in leaders:
        with conn.cursor() as cur:
            if stake_wide:
                where, args = "stake_id=%s", (stake_id,)
            elif units:
                where, args = "unit_id = any(%s)", (units,)
            else:
                continue
            cur.execute(f"select count(*) from members where {where}", args)
            total = cur.fetchone()[0]
            if total == 0:
                continue
            by = []
            for label, pred in _DIGEST_MILESTONES:
                cur.execute(f"select count(*) from members where {where} and {pred}", args)
                by.append((label, cur.fetchone()[0]))
        api_key, frm = stake_key(conn, stake_id)
        scope = "Your stake" if stake_wide else "Your unit"
        if send_email(email, "Covenant Path — daily summary",
                      _digest_html(email, scope, total, by), api_key, frm):
            sent += 1
    logger.info("sent %d/%d digests", sent, len(leaders))
    return sent
