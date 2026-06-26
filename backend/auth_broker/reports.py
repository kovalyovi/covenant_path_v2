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


def _scope(auth_id: str, email: str | None = None) -> dict | None:
    """Resolve the signed-in user's RLS scope from user_roles (stake-wide or specific units).

    Match by bound auth_id OR verified email — mirrors RLS (0004). Matching auth_id alone missed
    every email/Google login (auth_id holds the LCR person uuid, never the Supabase uid), which
    made "Generate report" come back empty + errored."""
    def _q(params: dict) -> list:
        # Deterministic stake selection for a multi-stake leader: order by earliest-provisioned so
        # rows[0] (the reported stake) is stable rather than arbitrary PostgREST row order.
        r = requests.get(f"{admin.SUPABASE_URL}/rest/v1/user_roles", headers=admin._sb_headers(),
                         params={"select": "stake_id,unit_id", "order": "created_at.asc",
                                 "limit": "200", **params},
                         timeout=_TIMEOUT)
        return r.json() if r.status_code == 200 else []
    rows = _q({"auth_id": f"eq.{auth_id}"}) if auth_id else []
    if not rows and email:
        rows = _q({"email": f"eq.{email.lower()}"})
    if not rows:
        return None
    stake_id = rows[0]["stake_id"]
    units = [r["unit_id"] for r in rows if r.get("unit_id")]
    stake_wide = any(r.get("unit_id") is None for r in rows)
    return {"stake_id": stake_id, "units": units, "stake_wide": stake_wide}


def build_report(auth_id: str, email: str | None = None) -> dict:
    """Build the convert-integration report for the user's scope. Returns structured data the app
    renders in-app and the email path formats. Raises admin.AdminError on misconfig/failure."""
    scope = _scope(auth_id, email)
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
    # BACKEND-02: member names/units/milestones flow from LCR (lower trust) into an HTML email —
    # escape every interpolated value so a crafted name can't inject markup into the leader's inbox.
    from html import escape
    when = escape(rep.get("generated_at", "")[:10])
    head = (f"<h2>Covenant Path — convert report</h2>"
            f"<p><b>{escape(rep.get('stake_name') or 'Your scope')}</b> · generated {when}</p>"
            f"<p>{rep['total']} new members · {rep['on_track']} on track · "
            f"{len(rep['outstanding'])} with outstanding steps.</p>")
    if rep["by_milestone"]:
        summary = "".join(f"<li>{escape(str(label))}: {n} still need this</li>"
                          for label, n in rep["by_milestone"])
        head += f"<h3>Most-needed steps</h3><ul>{summary}</ul>"
    if not rep["outstanding"]:
        return head + "<p>Everyone in scope is on track. 🎉</p>"
    parts = []
    for o in rep["outstanding"]:
        unit = f" ({escape(str(o['unit']))})" if o.get("unit") else ""
        missing = escape(", ".join(str(m) for m in o["missing"]))
        parts.append(f"<li><b>{escape(str(o['name'] or ''))}</b>{unit} — {missing}</li>")
    return head + f"<h3>Outstanding by member</h3><ul>{''.join(parts)}</ul>"


def email_report(auth_id: str, reporter_email: str, to_email: str | None) -> dict:
    """Build the report for the user's scope and email it (default: to the requester)."""
    rep = build_report(auth_id, reporter_email)
    to = (to_email or reporter_email or "").strip()
    if "@" not in to:
        raise admin.AdminError("a valid recipient email is required")
    subject = f"Covenant Path report — {rep.get('stake_name') or 'your scope'}"
    admin._send_email(to, subject, _report_html(rep))
    return {"status": "sent", "to": to, "total": rep["total"],
            "outstanding": len(rep["outstanding"])}
