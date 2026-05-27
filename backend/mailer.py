"""
Email via SMTP — invitation emails + per-leader daily digests.

Provider-agnostic (one code path) so you can send WITHOUT owning a domain:
  • Gmail  — smtp.gmail.com:587, user=your gmail, pass=an App Password (zero setup, ~500/day)
  • Brevo  — smtp-relay.brevo.com:587, free 300/day, verify your gmail as a sender (no domain)
  • Resend — smtp.resend.com:587 once you verify a domain (branded, scalable)
A stake can override the From display via stake_settings.email_from. Per-stake SMTP creds
can be added later for full quota isolation (see docs/CUSTOM_API_KEYS.md).

Env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, APP_URL. Never logs creds.
Free-tier aware: a per-run cap. If SMTP isn't configured, sends are skipped (no crash) —
invitations still work (the role is granted; the email is just a notification).
"""

from __future__ import annotations

import os
import re
import smtplib
from email.mime.text import MIMEText

from lcr_client.logging_setup import get_logger

logger = get_logger()
DEFAULT_DAILY_CAP = 90


def _smtp_config():
    return (os.environ.get("SMTP_HOST"), int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"),
            os.environ.get("SMTP_FROM") or os.environ.get("RESEND_FROM")
            or "Covenant Path <noreply@example.com>")


def _addr(from_header: str) -> str:
    m = re.search(r"<([^>]+)>", from_header)
    return m.group(1) if m else from_header


def _app_url() -> str:
    return os.environ.get("APP_URL", "https://your-viewer.example.com")


def stake_from(conn, stake_id: str) -> str | None:
    """Per-stake From display, if configured (else the shared SMTP_FROM)."""
    try:
        with conn.cursor() as cur:
            cur.execute("select email_from from stake_settings where stake_id=%s", (stake_id,))
            row = cur.fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def send_email(to: str, subject: str, html: str, from_email: str | None = None) -> bool:
    host, port, user, password, default_from = _smtp_config()
    if not (host and user and password):
        logger.warning("SMTP not configured; skipping email to %s (set SMTP_* in env)", to)
        return False
    sender = from_email or default_from
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(_addr(sender), [to], msg.as_string())
        logger.info("email -> %s ok", to)
        return True
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
    with conn.cursor() as cur:
        cur.execute("""select i.id, i.invited_email, i.invited_by_email, s.name, i.stake_id, i.unit_id
                       from invitations i join stakes s on s.id=i.stake_id
                       where i.emailed=false and i.status<>'revoked' order by i.created_at limit %s""", (cap,))
        rows = cur.fetchall()
    sent = 0
    for inv_id, email, by, stake_name, stake_id, unit_id in rows:
        scope = "whole stake" if unit_id is None else "your unit"
        if send_email(email, f"Access to {stake_name} — Covenant Path",
                      _invite_html(stake_name, scope, by), stake_from(conn, stake_id)):
            with conn.cursor() as cur:
                cur.execute("update invitations set emailed=true, status='active' where id=%s", (inv_id,))
            conn.commit()
            sent += 1
    logger.info("sent %d/%d pending invitations", sent, len(rows))
    return sent


_DIGEST_MILESTONES = [
    ("Friends", "friends='Yes'"), ("Calling", "calling='Yes'"),
    ("Has ministers", "ministering_brothers_sisters='Yes'"),
    ("Ministers", "ministering_assignment='Yes'"),
    ("Temple recommend", "temple_recommend='Active'"),
    ("Patriarchal", "patriarchal_blessing='Yes'"),
]


def _digest_html(scope_label: str, total: int, by_milestone: list[tuple[str, int]]) -> str:
    items = "".join(f"<li>{label}: {n}/{total}</li>" for label, n in by_milestone)
    return (f"<h2>Covenant Path — daily summary</h2>"
            f"<p>{scope_label}: <b>{total}</b> new members.</p>"
            f"<p>Golden Hour completion:</p><ul>{items}</ul>"
            f"<p><a href=\"{_app_url()}\">Open the dashboard</a></p>")


def send_digests(conn, cap: int = DEFAULT_DAILY_CAP) -> int:
    """One digest per leader (by email), summarizing their RLS scope. Free-tier capped."""
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
        scope = "Your stake" if stake_wide else "Your unit"
        if send_email(email, "Covenant Path — daily summary",
                      _digest_html(scope, total, by), stake_from(conn, stake_id)):
            sent += 1
    logger.info("sent %d/%d digests", sent, len(leaders))
    return sent
