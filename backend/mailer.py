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
from datetime import datetime
from email.mime.text import MIMEText

import psycopg2.extras
import requests

from lcr_client.logging_setup import get_logger

logger = get_logger()
DEFAULT_DAILY_CAP = 90


def _default_from() -> str:
    return (os.environ.get("SMTP_FROM") or os.environ.get("RESEND_FROM")
            or os.environ.get("MAIL_FROM") or "Covenant Path <noreply@membercovenantpath.org>")


def _smtp_config():
    return (os.environ.get("SMTP_HOST"), int(os.environ.get("SMTP_PORT", "587")),
            os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), _default_from())


def _send_resend(to: str, subject: str, html: str, sender: str) -> bool | None:
    """Send via Resend's HTTP API when RESEND_API_KEY is set (the key the broker already uses).
    Returns True/False on attempt, or None if Resend isn't configured (caller tries SMTP)."""
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return None
    try:
        r = requests.post("https://api.resend.com/emails",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"from": sender, "to": [to], "subject": subject, "html": html},
                          timeout=30)
        if r.status_code < 300:
            logger.info("email(resend) -> %s ok", to)
            return True
        logger.error("email(resend) -> %s failed %s: %s", to, r.status_code, r.text[:160])
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("email(resend) -> %s error: %s", to, exc)
        return False


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
    sender = from_email or default_from
    # Prefer Resend's HTTP API (one key, no SMTP setup); fall back to SMTP if not configured.
    resend = _send_resend(to, subject, html, sender)
    if resend is not None:
        return resend
    if not (host and user and password):
        logger.warning("no email transport configured; skipping email to %s "
                       "(set RESEND_API_KEY or SMTP_*)", to)
        return False
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


# --- weekly "what's missing" reminders (eligibility-aware, with week-over-week diff) --------
# Milestone eligibility lives in backend.milestones (pure, no-DB) so the broker's report builder
# (slim image, no psycopg2) can share it. Thin aliases keep the existing call sites unchanged.

from backend.milestones import member_missing as _member_missing, year as _year  # noqa: E402


def _snapshot_and_diff(conn) -> dict:
    """Per stake: compute each baptized member's missing-eligible steps, diff against last week's
    snapshot (so we can congratulate newly-finished steps), then save this week's snapshot.
    Returns {stake_id: {uuid: {name, unit_id, missing[], completed_since[]}}}."""
    out: dict = {}
    with conn.cursor() as cur:
        cur.execute("select id from stakes")
        stake_ids = [r[0] for r in cur.fetchall()]
    for sid in stake_ids:
        with conn.cursor() as cur:
            cur.execute(
                """select person_uuid, name, unit_id, sex, birth_date, baptism_date, friends,
                          calling, ministering_brothers_sisters, ministering_assignment,
                          aaronic_priesthood, melchizedek_priesthood
                   from members where stake_id=%s and coalesce(kind,'new_member') <> 'investigator'""",
                (sid,))
            cols = [d[0] for d in cur.description]
            members = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute("""select snapshot from reminder_snapshots where stake_id=%s
                           order by created_at desc limit 1""", (sid,))
            row = cur.fetchone()
            prev = (row[0] if row else {}) or {}
        cur_map, snap = {}, {}
        for m in members:
            uuid = m.get("person_uuid")
            if not uuid:
                continue
            missing = _member_missing(m)
            snap[uuid] = missing
            completed_since = sorted(set(prev.get(uuid, [])) - set(missing))
            cur_map[uuid] = {
                "name": m.get("name"),
                "unit_id": str(m["unit_id"]) if m.get("unit_id") else None,
                "missing": missing,
                "completed_since": completed_since,
            }
        with conn.cursor() as cur:
            cur.execute("insert into reminder_snapshots (stake_id, snapshot) values (%s,%s)",
                        (sid, psycopg2.extras.Json(snap)))
        conn.commit()
        out[sid] = cur_map
    return out


def _reminder_html(outstanding: list[dict], completed: int) -> str:
    congrats = (f"<p>🎉 <b>{completed} step{'s' if completed != 1 else ''} completed</b> since last "
                f"week — nice work!</p>") if completed else ""
    if not outstanding:
        return (f"<h2>Covenant Path — weekly update</h2>{congrats}"
                f"<p>Everyone in your scope is on track. Nothing needs attention this week.</p>"
                f"<p><a href=\"{_app_url()}\">Open the dashboard</a></p>")
    items = "".join(
        f"<li><b>{o['name']}</b> still needs: {', '.join(o['missing'])}</li>" for o in outstanding)
    return (f"<h2>Covenant Path — this week's next steps</h2>{congrats}"
            f"<p>{len(outstanding)} new member{'s' if len(outstanding) != 1 else ''} have outstanding "
            f"integration steps:</p><ul>{items}</ul>"
            f"<p><a href=\"{_app_url()}\">Open the dashboard</a> to see details.</p>")


# NOTE: the reminder engine is still in development. For now it emails ONLY the owner so we can
# review the weekly digest before it ever reaches ward/stake leaders — set REMINDER_ALL=1 (env)
# to fan out to every leader once we're happy with the content/cadence.
_REMINDER_OWNER = os.environ.get("REMINDER_OWNER", "ilia.kovaliov@gmail.com").lower()
_REMINDERS_OWNER_ONLY = os.environ.get("REMINDER_ALL") != "1"


# --- responsibility handoff pings (#72: missionary/WML -> Elders Quorum / Relief Society) ------

def _handoff_thresholds() -> list[int]:
    """Months-post-baptism at which fellowship responsibility hands off. Configurable via env
    HANDOFF_MONTHS (default '6,12'). The Church convention: missionaries + the ward mission leader
    fellowship a new convert, then the Elders Quorum / Relief Society take over at 6–12 months."""
    raw = os.environ.get("HANDOFF_MONTHS", "6,12")
    out = [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
    return sorted(set(out)) or [6, 12]


def _handoff_window() -> int:
    """Only converts baptized within this many months are in scope (keeps lifelong members from
    being flagged as 'handoffs'). Default 24 — the app's new-member window."""
    try:
        return int(os.environ.get("HANDOFF_WINDOW_MONTHS", "24"))
    except ValueError:
        return 24


def _months_since(date_str) -> int | None:
    """Whole months between a YYYY-MM(-DD) date and now; year-only falls back to year*12."""
    m = re.search(r"(\d{4})-(\d{1,2})", str(date_str or ""))
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        now = datetime.now()
        return (now.year - y) * 12 + (now.month - mo)
    y = _year(date_str)
    return (datetime.now().year - y) * 12 if y else None


def _crossed_phase(months: int, thresholds: list[int]) -> str | None:
    """The highest threshold this convert has reached, as a phase label (e.g. '12mo'), or None."""
    crossed = [t for t in thresholds if months >= t]
    return f"{max(crossed)}mo" if crossed else None


def _new_handoffs(conn) -> dict:
    """Per stake: recent converts that have NEWLY crossed a responsibility threshold (the phase is
    not yet recorded in handoff_pings). Returns {stake_id: [{person_uuid,name,unit_id,quorum,
    phase,missing[]}]}. Long-tenured members are excluded by the baptism window."""
    thresholds, window = _handoff_thresholds(), _handoff_window()
    out: dict = {}
    with conn.cursor() as cur:
        cur.execute("select id from stakes")
        stake_ids = [r[0] for r in cur.fetchall()]
    for sid in stake_ids:
        with conn.cursor() as cur:
            cur.execute(
                """select person_uuid, name, unit_id, sex, birth_date, baptism_date, friends,
                          calling, ministering_brothers_sisters, ministering_assignment,
                          aaronic_priesthood, melchizedek_priesthood
                   from members where stake_id=%s and coalesce(kind,'new_member') <> 'investigator'""",
                (sid,))
            cols = [d[0] for d in cur.description]
            members = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.execute("select person_uuid, phase from handoff_pings where stake_id=%s", (sid,))
            already = {(r[0], r[1]) for r in cur.fetchall()}
        new = []
        for m in members:
            uuid = m.get("person_uuid")
            months = _months_since(m.get("baptism_date"))
            if not uuid or months is None or months > window:
                continue
            phase = _crossed_phase(months, thresholds)
            if not phase or (uuid, phase) in already:
                continue
            new.append({
                "person_uuid": uuid,
                "name": m.get("name"),
                "unit_id": str(m["unit_id"]) if m.get("unit_id") else None,
                "quorum": "Relief Society" if m.get("sex") == "F" else "Elders Quorum",
                "phase": phase,
                "missing": _member_missing(m),
            })
        out[sid] = new
    return out


def _handoff_html(handoffs: list[dict]) -> str:
    rows = "".join(
        f"<li><b>{h['name']}</b> has reached {h['phase'].replace('mo', ' months')} since baptism — "
        f"primary fellowship now moves to <b>{h['quorum']}</b>."
        + (f" Still needs: {', '.join(h['missing'])}." if h["missing"] else " They're on track! 🎉")
        + "</li>"
        for h in handoffs)
    return (f"<h2>Covenant Path — convert responsibility handoff</h2>"
            f"<p>These new members have reached a fellowship handoff point. Please make sure the "
            f"receiving quorum / Relief Society knows them and what's still needed:</p>"
            f"<ul>{rows}</ul>"
            f"<p><a href=\"{_app_url()}\">Open the dashboard</a> for details.</p>")


def send_handoff_pings(conn, cap: int = DEFAULT_DAILY_CAP) -> int:
    """Ping leaders when a convert crosses a responsibility threshold (6/12 months), with what's
    still missing. Each transition fires exactly once (recorded in handoff_pings only after it's
    actually emailed). Owner-only preview until REMINDER_ALL=1 (same gate as weekly reminders)."""
    by_stake = _new_handoffs(conn)
    if not any(by_stake.values()):
        logger.info("no new responsibility handoffs")
        return 0
    with conn.cursor() as cur:
        cur.execute("""select lower(email) as email, bool_or(unit_id is null) as stake_wide,
                              array_remove(array_agg(distinct unit_id), null) as units,
                              max(stake_id::text) as stake_id
                       from user_roles where email is not null group by lower(email) limit %s""", (cap,))
        leaders = cur.fetchall()
    sent = 0
    delivered: set = set()  # (stake_id, uuid, phase) actually emailed — only these get recorded
    for email, stake_wide, units, stake_id in leaders:
        if _REMINDERS_OWNER_ONLY and email != _REMINDER_OWNER:
            continue  # WIP preview — don't reach real leaders until reviewed
        items = by_stake.get(stake_id, [])
        unit_strs = {str(u) for u in (units or [])}
        scoped = [h for h in items if stake_wide or h["unit_id"] in unit_strs]
        if not scoped:
            continue
        if send_email(email, "Covenant Path — convert responsibility handoff",
                      _handoff_html(scoped), stake_from(conn, stake_id)):
            sent += 1
            for h in scoped:
                delivered.add((stake_id, h["person_uuid"], h["phase"]))
    if delivered:
        with conn.cursor() as cur:
            for sid, uuid, phase in delivered:
                cur.execute("""insert into handoff_pings (stake_id, person_uuid, phase)
                               values (%s,%s,%s) on conflict do nothing""", (sid, uuid, phase))
        conn.commit()
    logger.info("sent %d handoff ping(s); recorded %d transition(s)", sent, len(delivered))
    return sent


def send_weekly_reminders(conn, cap: int = DEFAULT_DAILY_CAP) -> int:
    """One weekly digest per leader (RLS scope) of converts with outstanding *eligible* steps,
    plus congratulations for steps finished since last week. Suppressed when there's nothing to
    nudge and nothing to celebrate. History lives in reminder_snapshots.

    WORK IN PROGRESS: gated to the owner only (see _REMINDERS_OWNER_ONLY) until the content is
    reviewed; the owner is a stake leader so the digest covers the whole stake."""
    diffs = _snapshot_and_diff(conn)
    with conn.cursor() as cur:
        cur.execute("""select lower(email) as email, bool_or(unit_id is null) as stake_wide,
                              array_remove(array_agg(distinct unit_id), null) as units,
                              max(stake_id::text) as stake_id
                       from user_roles where email is not null group by lower(email) limit %s""", (cap,))
        leaders = cur.fetchall()
    sent = 0
    for email, stake_wide, units, stake_id in leaders:
        if _REMINDERS_OWNER_ONLY and email != _REMINDER_OWNER:
            continue  # WIP — owner-only preview
        data = diffs.get(stake_id, {})
        unit_strs = {str(u) for u in (units or [])}
        scoped = [v for v in data.values() if stake_wide or v["unit_id"] in unit_strs]
        outstanding = sorted([v for v in scoped if v["missing"]], key=lambda v: v["name"] or "")
        completed = sum(len(v["completed_since"]) for v in scoped)
        if not outstanding and completed == 0:
            continue  # nothing to nudge, nothing to celebrate -> don't send
        if send_email(email, "Covenant Path — this week's next steps",
                      _reminder_html(outstanding, completed), stake_from(conn, stake_id)):
            sent += 1
    logger.info("sent %d/%d weekly reminders", sent, len(leaders))
    return sent
