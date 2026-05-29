"""
Ad-hoc leader reports (#73). A signed-in leader can generate a report of their RLS scope's
convert-integration status — viewed in-app and/or emailed on demand. The broker has no DB
(slim image, no psycopg2), so the report is built over the Supabase service-role REST API and
emailed via the existing Resend helper. Milestone eligibility comes from backend.milestones
(pure, shared with the mailer) so in-app, email, and the weekly digest never diverge.
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from backend import milestones
from backend.auth_broker import admin

_TIMEOUT = 15
_MEMBER_COLS = ("person_uuid,name,unit_name,unit_id,sex,birth_date,baptism_date,kind,"
                "friends,calling,ministering_brothers_sisters,ministering_assignment,"
                "aaronic_priesthood,melchizedek_priesthood")


def _scope(auth_id: str) -> dict | None:
    """Resolve the signed-in user's RLS scope from user_roles (stake-wide or specific units)."""
    r = requests.get(f"{admin.SUPABASE_URL}/rest/v1/user_roles", headers=admin._sb_headers(),
                     params={"select": "stake_id,unit_id", "auth_id": f"eq.{auth_id}", "limit": "200"},
                     timeout=_TIMEOUT)
    rows = r.json() if r.status_code == 200 else []
    if not rows:
        return None
    stake_id = rows[0]["stake_id"]
    units = [r["unit_id"] for r in rows if r.get("unit_id")]
    stake_wide = any(r.get("unit_id") is None for r in rows)
    return {"stake_id": stake_id, "units": units, "stake_wide": stake_wide}


def build_report(auth_id: str) -> dict:
    """Build the convert-integration report for the user's scope. Returns structured data the app
    renders in-app and the email path formats. Raises admin.AdminError on misconfig/failure."""
    scope = _scope(auth_id)
    if not scope:
        return {"scope": "none", "total": 0, "outstanding": [], "by_milestone": [],
                "generated_at": datetime.now(timezone.utc).isoformat()}
    stake_id = scope["stake_id"]
    params = {"select": _MEMBER_COLS, "stake_id": f"eq.{stake_id}", "limit": "5000"}
    if not scope["stake_wide"] and scope["units"]:
        params["unit_id"] = f"in.({','.join(scope['units'])})"
    r = requests.get(f"{admin.SUPABASE_URL}/rest/v1/members", headers=admin._sb_headers(),
                     params=params, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise admin.AdminError(f"could not load members ({r.status_code})")
    members = [m for m in r.json() if (m.get("kind") or "new_member") != "investigator"]

    stake = admin._one("stakes", {"select": "name", "id": f"eq.{stake_id}", "limit": "1"}) or {}
    outstanding = []
    milestone_counts: dict[str, int] = {}
    for m in members:
        missing = milestones.member_missing(m)
        for label in missing:
            milestone_counts[label] = milestone_counts.get(label, 0) + 1
        if missing:
            outstanding.append({"name": m.get("name"), "unit": m.get("unit_name"), "missing": missing})
    outstanding.sort(key=lambda o: (o["unit"] or "", o["name"] or ""))
    return {
        "stake_name": stake.get("name"),
        "scope": "stake" if scope["stake_wide"] else "units",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(members),
        "on_track": len(members) - len(outstanding),
        "outstanding": outstanding,
        "by_milestone": sorted(milestone_counts.items(), key=lambda kv: -kv[1]),
    }


def _report_html(rep: dict) -> str:
    when = rep.get("generated_at", "")[:10]
    head = (f"<h2>Covenant Path — convert report</h2>"
            f"<p><b>{rep.get('stake_name') or 'Your scope'}</b> · generated {when}</p>"
            f"<p>{rep['total']} new members · {rep['on_track']} on track · "
            f"{len(rep['outstanding'])} with outstanding steps.</p>")
    if rep["by_milestone"]:
        summary = "".join(f"<li>{label}: {n} still need this</li>" for label, n in rep["by_milestone"])
        head += f"<h3>Most-needed steps</h3><ul>{summary}</ul>"
    if not rep["outstanding"]:
        return head + "<p>Everyone in scope is on track. 🎉</p>"
    parts = []
    for o in rep["outstanding"]:
        unit = f" ({o['unit']})" if o.get("unit") else ""
        parts.append(f"<li><b>{o['name']}</b>{unit} — {', '.join(o['missing'])}</li>")
    return head + f"<h3>Outstanding by member</h3><ul>{''.join(parts)}</ul>"


def email_report(auth_id: str, reporter_email: str, to_email: str | None) -> dict:
    """Build the report for the user's scope and email it (default: to the requester)."""
    rep = build_report(auth_id)
    to = (to_email or reporter_email or "").strip()
    if "@" not in to:
        raise admin.AdminError("a valid recipient email is required")
    subject = f"Covenant Path report — {rep.get('stake_name') or 'your scope'}"
    admin._send_email(to, subject, _report_html(rep))
    return {"status": "sent", "to": to, "total": rep["total"],
            "outstanding": len(rep["outstanding"])}
