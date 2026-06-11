"""
Adapt the Member Tools `/api/v5/sync` bulk payload → our CovenantPathMember model.

This replaces the FRAGILE one-work source (progress-record + per-person details) with the reliable
Member Tools bulk call (lcr_client.membertools). It fills the covenant-path PROGRESS fields (the data
that used to come from the flaky cluster) + the rich `details` subtree the app's member view shows.
The PROFILE-sourced fields (patriarchal_blessing, temple_recommend, ministering, calling, priesthood,
birth_date, …) are left as the NEEDS_PROFILE sentinel — covenant_path.report's existing /mlt profile
merge fills those from the reliable /mlt cluster, exactly as before. So this is a SURGICAL swap of
only the broken part.

person_uuid mapping is load-bearing (wrong choice → duplicated members): VERIFIED live that members
match our DB on `memberUuid` (76/76) and investigators (no memberUuid) on `id` (17/17) — so
`memberUuid or id`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from covenant_path.report import CovenantPathMember, NEEDS_PROFILE


def _person_uuid(p: dict) -> str | None:
    return p.get("memberUuid") or p.get("id")


def _readable_name(names: Any) -> str | None:
    """A display name out of a Member Tools `names` value (dict or list of dicts), tolerant of drift."""
    if isinstance(names, list):
        names = names[0] if names else None
    if isinstance(names, dict):
        for k in ("listPreferred", "listPreferredLocal", "preferredName", "displayName", "fullName"):
            if names.get(k):
                return str(names[k])
        given = names.get("given") or names.get("givenPreferred") or names.get("givenName")
        family = names.get("family") or names.get("familyPreferred") or names.get("surname")
        if family or given:
            return f"{family}, {given}".strip(", ")
    return None


def _name(p: dict) -> str | None:
    return p.get("displayName") or _readable_name(p.get("names"))


def _sex(p: dict) -> str | None:
    s = (p.get("sex") or "").upper()
    return "F" if s.startswith("F") else "M" if s.startswith("M") else None


def _parse_date(s: Any) -> date | None:
    if not isinstance(s, str) or not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s[:len(fmt) + 6 if "%f" in fmt else len(s)], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _weeks_since_attendance(sacrament: list | None) -> int | None:
    """Weeks since the most recent ATTENDED sacrament meeting (Member Tools gives the raw list, not a
    precomputed count). None when there's no attended record."""
    dates = [d for d in (_parse_date(s.get("date")) for s in (sacrament or []) if s.get("attended")) if d]
    if not dates:
        return None
    return max(0, (date.today() - max(dates)).days // 7)


def _details_subtree(p: dict) -> dict:
    """The rich progress-only subtree for the member view, in our canonical `details` shape — sourced
    from Member Tools instead of the one-work details endpoint. Profile-sourced sub-keys (callings,
    ministering, templeOrdinances) are left for the /mlt merge; here we fill the PROGRESS sub-keys."""
    sacrament = [
        {"label": s.get("date"), "attended": bool(s.get("attended")), "date": s.get("date")}
        for s in (p.get("sacramentAttendance") or [])
    ]
    friends = [
        {"name": _name(f) or f.get("name"), "unit": None, "inStake": None}
        for f in (p.get("friends") or []) if (_name(f) or f.get("name"))
    ]
    lessons = [
        {
            "name": tr.get("title"),
            "taught": None,
            "principles": [
                {"name": pr.get("title"), "memberPresent": bool(pr.get("memberPresent")),
                 "taughtLevel": pr.get("taught")}
                for pr in (tr.get("principles") or [])
            ],
        }
        for tr in (p.get("teachingRecords") or [])
    ]
    commitments = [c.get("title") for c in (p.get("commitments") or []) + (p.get("otherCommitments") or [])
                   if c.get("title")]
    return {
        "baptismGoalDate": p.get("baptismGoalDate"),
        "firstLesson": p.get("firstTaught"),
        "nextScheduledEvent": p.get("nextAppointment"),
        "weeksSinceLastAttendance": _weeks_since_attendance(p.get("sacramentAttendance")),
        "sacrament": sacrament,
        "friends": friends,
        "lessons": lessons,
        "commitments": commitments,
        "sealedToParents": p.get("sealedToParents"),
        "sealedToSpouse": p.get("sealedToSpouse"),
        "source": "membertools",  # provenance, so the app/diagnostics can tell where it came from
    }


def unit_names(payload: dict) -> dict[int, str]:
    """{unitNumber: name} from the `units` tree (root + childUnits), for mapping members to a ward."""
    out: dict[int, str] = {}

    def walk(u: dict):
        if isinstance(u, dict):
            if u.get("unitNumber") is not None and u.get("name"):
                out[int(u["unitNumber"])] = u["name"]
            for c in (u.get("childUnits") or []):
                walk(c)

    for u in (payload.get("units") or []):
        walk(u)
    return out


def adapt_person(p: dict, kind: str, unit_name_by_number: dict[int, str]) -> CovenantPathMember:
    """One Member Tools covenant-path person → CovenantPathMember. Covenant-path PROGRESS fields are
    filled from the bulk payload; PROFILE fields use the NEEDS_PROFILE sentinel so the /mlt merge (in
    covenant_path.report) fills them from the reliable cluster — preserving the existing behaviour."""
    unum = p.get("unitNumber")
    friends_list = p.get("friends") or []
    friend_names = [n for n in (_name(f) or f.get("name") for f in friends_list) if n]
    return CovenantPathMember(
        name=_name(p),
        unit=unit_name_by_number.get(int(unum)) if unum is not None else None,
        unit_number=int(unum) if unum is not None else None,
        person_uuid=_person_uuid(p),
        kind=kind,
        sex=_sex(p),
        # covenant-path PROGRESS (from Member Tools — the data we're rescuing from the fragile cluster)
        baptism_date=p.get("confirmationDate") or NEEDS_PROFILE,
        baptism_goal_date=p.get("baptismGoalDate"),
        friends="Yes" if friend_names else "No",
        friends_count=len(friend_names),
        friends_summary=", ".join(friend_names) or None,
        weeks_since_last_attendance=_weeks_since_attendance(p.get("sacramentAttendance")),
        details=_details_subtree(p),
        # PROFILE-sourced fields — left for the /mlt merge (reliable cluster), exactly as before.
        birth_date=None,
        aaronic_priesthood=NEEDS_PROFILE,
        melchizedek_priesthood=NEEDS_PROFILE,
        calling=NEEDS_PROFILE,
        ministering_brothers_sisters=NEEDS_PROFILE,
        ministering_assignment=NEEDS_PROFILE,
        temple_recommend=NEEDS_PROFILE,
        patriarchal_blessing=NEEDS_PROFILE,
        living_ordinance=NEEDS_PROFILE,
        membership_duration=None,
    )


# Which top-level array maps to which `kind` (the app's being-taught vs new-members split).
_ARRAYS = {
    "covenantPathInvestigators": "investigator",
    "covenantPathMembers": "new_member",
    "covenantPathReturningMembers": "returning",
}


def adapt_sync(payload: dict, include_returning: bool = True) -> list[CovenantPathMember]:
    """The whole /api/v5/sync payload → CovenantPathMember rows (covenant-path progress filled; the
    profile fields await the /mlt merge). De-dupes by person_uuid (members can appear under multiple
    arrays); a real person_uuid is required (else the DB upsert key is meaningless)."""
    units = unit_names(payload)
    out: list[CovenantPathMember] = []
    seen: set[str] = set()
    for arr, kind in _ARRAYS.items():
        if arr == "covenantPathReturningMembers" and not include_returning:
            continue
        for p in (payload.get(arr) or []):
            uuid = _person_uuid(p)
            if not uuid or uuid in seen:
                continue
            seen.add(uuid)
            out.append(adapt_person(p, kind, units))
    return out
