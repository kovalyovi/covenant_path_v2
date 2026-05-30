"""
Stake-level covenant-path aggregator.

Loops over every unit in the stake, pulls each unit's covenant-path "new member"
list (LCR one-work progress record), enriches each person with the per-member
details + member-list birth date, and assembles one stake-wide dataset of the
covenant-path tracking fields.

Run:
    python -m covenant_path.report          # all new members, all units -> output/
    python -m covenant_path.report --include-returning
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lcr_client import LcrClient
from lcr_client.access import covenant_path_access
from lcr_client.auth import AuthExpiredError
from lcr_client.logging_setup import dump_debug, get_logger
from lcr_client.member_profile import profile_fields
# Shared, pure eligibility helpers (same rules the app + mailer use) — to gate priesthood display
# to eligible people (N/A for ineligible), matching the reference sheet.
from backend.milestones import is_at_least_now, member_one_year, turns_at_least
from covenant_path.profile_cache import ProfileCache

logger = get_logger()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
NA = "N/A"
NEEDS_PROFILE = "needs-profile-api"
BLOCKED = "blocked: insufficient calling access"

# covenant-path fields that come from the member-profile server actions, so they
# share the "menu.view.member.profiles" access gate.
_PROFILE_GATED_FIELDS = (
    "baptism_date", "temple_recommend", "patriarchal_blessing", "ministering_assignment",
)


# --- field parsing -----------------------------------------------------------

def parse_priesthood(ordinations: list[str] | None) -> tuple[str, str]:
    """Map LCR priesthoodOrdinations strings to (aaronic, melchizedek) Yes/No/N/A."""
    text = " | ".join(ordinations or [])
    if "Ordained Elder" in text or "Ordained High Priest" in text:
        return ("Yes", "Yes")
    if "Eligible to receive Melchizedek Priesthood" in text:
        return ("Yes", "No")
    if any(o in text for o in ("Ordained Priest", "Ordained Teacher", "Ordained Deacon")):
        return ("Yes", "No")
    if "Eligible to receive Aaronic Priesthood" in text:
        return ("No", NA)
    return (NA, NA)


# LCR currentPriesthoodOfficeType -> (aaronic, melchizedek). Melchizedek offices imply the holder
# also received the Aaronic Priesthood. This is the AUTHORITATIVE priesthood source (the per-member
# profile record); the sparse one-work progress record's priesthoodOrdinations is empty for most.
_MELCH_OFFICES = {"ELDER", "HIGH_PRIEST", "BISHOP", "SEVENTY", "PATRIARCH", "APOSTLE"}
_AARONIC_OFFICES = {"DEACON", "TEACHER", "PRIEST"}


def priesthood_from_office(office: str | None) -> tuple[str, str]:
    o = (office or "").upper().replace(" ", "_").replace("-", "_")
    if o in _MELCH_OFFICES:
        return ("Yes", "Yes")
    if o in _AARONIC_OFFICES:
        return ("Yes", "No")
    return ("No", "No")  # profile fetched, no office -> genuinely no priesthood (eligibility gates display)


def parse_endowment(temple_ordinances: list[str] | None) -> str:
    """living_ordinance = received temple endowment."""
    text = " | ".join(temple_ordinances or [])
    if not text:
        return NA
    if "Not yet endowed" in text:
        return "No"
    if "endowed" in text.lower() or "Endowment" in text:
        return "Yes"
    return NA


def yes_no(present: bool) -> str:
    return "Yes" if present else "No"


def _progress_subtree(d: dict) -> dict:
    """The covenant-path *progress* fields from a one-work details record, shaped for the
    rich member view (sacrament dots, friends, lessons, ministering, commitments).

    Deliberately drops contact PII — phoneNumbers / emailAddresses / socialMediaAccounts /
    contactInformation are NOT included, so none of that lands in Supabase.
    """
    def names(lst) -> list[str]:
        return [p.get("name") for p in (lst or []) if p.get("name")]

    def outbound(assigns) -> list[str]:
        out: list[str] = []
        for a in assigns or []:
            out += [x.get("name") for x in (a.get("assignments") or []) if x.get("name")]
        return out

    def commitments(lst) -> list[dict]:
        return [{"name": c.get("name"), "done": bool(c.get("isKeeping"))}
                for c in (lst or []) if c.get("name")]

    m = d.get("ministering") or {}
    return {
        "memberSince": d.get("memberSinceDisplayString"),
        "baptismGoalDate": d.get("baptismGoalDateString"),
        "firstLesson": d.get("firstLessonString"),
        "nextScheduledEvent": d.get("nextScheduledEventDateString"),
        "weeksSinceLastAttendance": d.get("weeksSinceLastAttendance"),
        "sacramentMissed": d.get("sacramentMeetingMessage"),
        "sacrament": [
            {"label": s.get("dateDisplay"), "attended": bool(s.get("attended")),
             "date": s.get("dateString") or s.get("date")}
            for s in (d.get("sacramentMeetingAttendanceList") or [])
        ],
        "friends": [
            {"name": f.get("name"), "unit": f.get("unitName"), "inStake": bool(f.get("inParentUnit"))}
            for f in (d.get("friends") or []) if f.get("name")
        ],
        "priesthoodOrdinations": list(d.get("priesthoodOrdinations") or []),
        "callings": list(d.get("callings") or []),
        "ministeringBrothers": names(m.get("ministeringBrothers")),
        "ministeringSisters": names(m.get("ministeringSisters")),
        "ministeringAssignments": outbound(m.get("ministeringBrothersAssignments"))
        + outbound(m.get("ministeringSistersAssignments")),
        "templeOrdinances": list(d.get("templeOrdinances") or []),
        "templeExperiences": commitments(d.get("newMemberOtherCommitments")),
        "lessons": [
            {
                "name": le.get("name"),
                "taught": le.get("numberTaughtDisplayString"),
                "principles": [
                    {"name": p.get("name"), "memberPresent": bool(p.get("memberPresent")),
                     "taughtLevel": p.get("taughtLevel")}
                    for p in (le.get("principles") or [])
                ],
            }
            for le in (d.get("lessons") or [])
        ],
        "selfReliance": commitments(d.get("selfRelianceCourses")),
        "tags": [(t.get("tagString") or {}).get("string")
                 for t in (d.get("tags") or []) if (t.get("tagString") or {}).get("string")],
        "cmisId": d.get("cmisId"),  # avatar/{cmisId} for the later photo pipeline
    }


# --- model -------------------------------------------------------------------

@dataclass
class CovenantPathMember:
    name: str | None
    unit: str | None
    baptism_date: str  # exact date not in covenant-path API
    birth_date: str | None
    friends: str
    aaronic_priesthood: str
    melchizedek_priesthood: str
    calling: str
    ministering_brothers_sisters: str
    ministering_assignment: str
    temple_recommend: str
    patriarchal_blessing: str
    living_ordinance: str
    # useful covenant-path extras the report exposes
    membership_duration: str | None
    weeks_since_last_attendance: Any | None
    baptism_goal_date: str | None
    friends_summary: str | None
    sex: str | None
    person_uuid: str | None = field(default=None)
    unit_number: int | None = field(default=None)  # stable key for DB unit mapping
    # 'new_member' (baptized), 'investigator' (being taught — has a planned baptism goal date),
    # or 'returning'. Drives the app's "being taught" vs "new members" split.
    kind: str = field(default="new_member")
    # full progress-only subtree (sacrament, friends, lessons, ministering, commitments)
    # for the rich member view — see _progress_subtree. None if details fetch failed.
    details: dict | None = field(default=None)


# --- build -------------------------------------------------------------------

def _details_with_retry(client: LcrClient, person_id: str, cmis_id: Any, attempts: int = 2) -> dict | None:
    for i in range(attempts):
        try:
            return client.progress_details(person_id, cmis_id)
        except AuthExpiredError:
            raise
        except Exception:  # noqa: BLE001  (LCR occasionally 500s; retry once)
            if i == attempts - 1:
                return None
            time.sleep(1.0)
    return None


def _retry(fn, attempts: int = 3, delay: float = 2.0, label: str = ""):
    """Retry a call on transient failures (LCR occasionally 500s). Returns None if all fail.

    AuthExpiredError propagates (it's already handled with one relogin in LcrSession);
    everything else (e.g. a 500) is retried so one flaky unit doesn't fail the whole run.
    """
    import random
    for i in range(attempts):
        try:
            return fn()
        except AuthExpiredError:
            raise
        except Exception as exc:  # noqa: BLE001
            if i == attempts - 1:
                logger.warning("giving up on %s after %d attempts: %s", label, attempts, exc)
                return None
            # exponential backoff + jitter — LCR 500s are often transient overload, so
            # spacing retries out (rather than hammering) recovers more of them.
            time.sleep(delay * (2 ** i) + random.uniform(0, delay))
    return None


def _build_member_maps(client: LcrClient, unit_number: int) -> dict[str, dict]:
    """uuid -> {'birth': display, 'sex': 'M'/'F'} from the member list — the AUTHORITATIVE source
    for sex (the one-work progress record has no sex, which broke all gender/priesthood eligibility)."""
    out: dict[str, dict] = {}
    for m in client.member_list(unit_number):
        birth = (m.raw.get("birth") or {}).get("date") or {}
        display = birth.get("display")
        sex = m.raw.get("sex")
        for key in (m.raw.get("personUuid"), m.raw.get("uuid")):
            if not key:
                continue
            info = out.setdefault(key, {})
            if display:
                info["birth"] = display
            if sex:
                info["sex"] = sex
    return out


def _assemble(person_raw: dict, details: dict | None, unit_name: str, birth: str | None,
              kind: str = "new_member") -> CovenantPathMember:
    d = details or person_raw
    # Priesthood, calling, and endowment live in the member PROFILE. Without it the bare progress
    # record lacks those keys — emit NEEDS_PROFILE (not a false "N/A"/"No"/empty) so a no-profile or
    # partial run is PRESERVED by the merge-upsert (backend/db.upsert_members) instead of clobbering
    # good data. (Root cause of the "priesthood/calling blank in app, right in sheet" bug.)
    def _has(k: str) -> bool:
        return details is not None or k in d
    if _has("priesthoodOrdinations"):
        aaronic, melch = parse_priesthood(d.get("priesthoodOrdinations"))
    else:
        aaronic = melch = NEEDS_PROFILE
    calling = yes_no(bool(d.get("callings"))) if _has("callings") else NEEDS_PROFILE
    living = parse_endowment(d.get("templeOrdinances")) if _has("templeOrdinances") else NEEDS_PROFILE
    ministering = d.get("ministering") or {}
    has_ministers = bool(ministering.get("ministeringBrothers") or ministering.get("ministeringSisters"))
    return CovenantPathMember(
        name=d.get("name") or person_raw.get("name"),
        unit=unit_name,
        baptism_date=NEEDS_PROFILE,
        birth_date=birth,
        friends=yes_no(bool(d.get("friends"))),
        aaronic_priesthood=aaronic,
        melchizedek_priesthood=melch,
        calling=calling,
        ministering_brothers_sisters=yes_no(has_ministers),
        ministering_assignment=NEEDS_PROFILE,
        temple_recommend=NEEDS_PROFILE,
        patriarchal_blessing=NEEDS_PROFILE,
        living_ordinance=living,
        membership_duration=d.get("memberSinceDisplayString") or person_raw.get("memberSinceDisplayString"),
        weeks_since_last_attendance=d.get("weeksSinceLastAttendance"),
        baptism_goal_date=d.get("baptismGoalDateString") or person_raw.get("baptismGoalDateString"),
        friends_summary=d.get("numberOfFriendsDisplayString") or person_raw.get("numberOfFriendsDisplayString"),
        sex=d.get("sex"),
        person_uuid=person_raw.get("personUuid") or person_raw.get("id"),
        kind=kind,
        details=_progress_subtree(d),
    )


def _apply_profile(member: CovenantPathMember, prof: dict) -> None:
    """Fill the profile-sourced fields from the AUTHORITATIVE per-member profile record. Priesthood
    comes from priesthood_office here (the one-work record's priesthoodOrdinations is empty for most
    members — the root cause of the priesthood discrepancy). calling / has-ministers are likewise
    overridden from the profile when it supplies them."""
    if prof.get("baptism_date"):
        member.baptism_date = prof["baptism_date"]
    if prof.get("temple_recommend"):
        member.temple_recommend = prof["temple_recommend"]
    if prof.get("patriarchal_blessing"):
        member.patriarchal_blessing = prof["patriarchal_blessing"]
    if prof.get("ministering_assignment"):
        member.ministering_assignment = prof["ministering_assignment"]
    if not member.birth_date and prof.get("birth_date"):
        member.birth_date = prof["birth_date"]
    if prof.get("sex"):  # profile record is authoritative for sex (member list was unreliable)
        member.sex = prof["sex"]
    # Priesthood from the profile's office (authoritative). Gate the DISPLAYED value to ELIGIBLE
    # people — N/A for females / under-age / (for Melch) <1yr members — matching the reference
    # sheet, where ineligible rows show N/A rather than a misleading "No".
    if "priesthood_office" in prof:
        a, mel = priesthood_from_office(prof.get("priesthood_office"))
        em = {"sex": member.sex, "birth_date": member.birth_date, "baptism_date": member.baptism_date}
        male = member.sex == "M"
        member.aaronic_priesthood = a if (male and turns_at_least(em, 12)) else NA
        member.melchizedek_priesthood = (
            mel if (male and is_at_least_now(em, 18) and member_one_year(em)) else NA)
    # calling / has-ministers when the profile supplies them (member_profile.extract_fields fills
    # these when the member record exposes them; absent -> keep the value _assemble derived).
    if prof.get("calling") in ("Yes", "No"):
        member.calling = prof["calling"]
    if prof.get("ministering_brothers_sisters") in ("Yes", "No"):
        member.ministering_brothers_sisters = prof["ministering_brothers_sisters"]


# Fields that come from the member profile and must be marked access-blocked (not blanked) when
# the profile can't be fetched — the merge-upsert preserves last-good for all of these sentinels.
_BLOCK_WHEN_UNFILLED = _PROFILE_GATED_FIELDS + (
    "aaronic_priesthood", "melchizedek_priesthood", "calling", "living_ordinance",
)


def _mark_profile_blocked(member: CovenantPathMember) -> None:
    """Annotate still-unfilled profile-gated fields as access-blocked (not silently blank)."""
    for fld in _BLOCK_WHEN_UNFILLED:
        if getattr(member, fld) == NEEDS_PROFILE:
            setattr(member, fld, BLOCKED)


def _feature_allowed(access: dict, feature_key: str) -> bool:
    """Whether the runner's calling is granted a feature (matrix view; default True)."""
    for row in access.get("features", []):
        if row["feature"] == feature_key:
            return row["allowed"]
    return True


def _print_access_preflight(access: dict, with_profile: bool) -> None:
    pos = ", ".join(p["name"] for p in access.get("runner_positions", [])) or "(unknown calling)"
    logger.info("report runner: %s", pos)
    print(f"[access] running as: {pos}")
    if access.get("can_pull_all"):
        print("[access] this calling is granted all covenant-path features.")
    else:
        print("[access] features NOT granted to this calling "
              "(LCR menu matrix; API may still allow — pulls are still attempted):")
        for m in access.get("missing", []):
            who = ", ".join(m["granted_by"]) or "(no named callings)"
            extra = f" (+{m['also_unnamed_roles']} other seats)" if m.get("also_unnamed_roles") else ""
            print(f"         - {m['feature']}  ->  ask: {who}{extra}")
    if with_profile and not _feature_allowed(access, "menu.view.member.profiles"):
        print("[access] note: 'Member Profiles' not granted to this calling; profile-sourced "
              "fields (baptism, recommend, patriarchal, ministering) may come back blocked.")


def build_stake_report(
    client: LcrClient,
    include_returning: bool = False,
    delay: float = 0.25,
    with_profile: bool = False,
    verbose: bool = True,
    access: dict | None = None,
    cache: ProfileCache | None = None,
) -> list[CovenantPathMember]:
    if access is None:
        access = covenant_path_access(client)
    if verbose:
        _print_access_preflight(access, with_profile)
    can_profiles = _feature_allowed(access, "menu.view.member.profiles")

    ctx = client.user_context()
    units = [u for u in ctx.child_units if u.unit_number and u.type in ("WARD", "BRANCH")]
    results: list[CovenantPathMember] = []
    seen_uuids: set[str] = set()

    # Attempt-then-annotate: the matrix isn't 1:1 with API access, so we always try.
    # If the calling lacks profile access AND fetches keep failing, stop hammering a
    # blocked endpoint and mark the rest as access-blocked.
    profile_blocked = False
    profile_fail_streak = 0
    stats = {"units": 0, "units_failed": 0, "failed_units": [], "members": 0, "profile_ok": 0,
             "profile_cached": 0, "profile_blocked": 0, "profile_error": 0, "details_missing": 0}

    for unit in units:
        if verbose:
            print(f"[*] {unit.name} ({unit.unit_number})")
        pr = _retry(lambda u=unit: client.progress_record(u.unit_number),
                    label=f"progress_record {unit.unit_number}")
        if pr is None:
            stats["units_failed"] += 1
            stats["failed_units"].append(unit.name)
            if verbose:
                print(f"    [!] skipped {unit.name}: progress-record unavailable after retries")
            continue
        member_maps = _retry(lambda u=unit: _build_member_maps(client, u.unit_number),
                             label=f"member_list {unit.unit_number}") or {}

        # has-calling per member: whoever holds a position in the unit's org tree (the same
        # org-callings endpoint roles.py uses). The member profile has no callings and the one-work
        # record is sparse, so this is the authoritative source. None => couldn't fetch (don't override).
        try:
            from backend.roles import _ward_positions
            calling_uuids: set | None = {
                p["person_uuid"] for p in _ward_positions(client.org_callings(unit.unit_number))
                if p.get("person_uuid")}
        except Exception as exc:  # noqa: BLE001
            logger.warning("org callings unavailable for %s (%s): %s", unit.name, unit.unit_number, exc)
            calling_uuids = None

        # newMemberList = baptized; investigatorList = people being taught (planned baptism
        # date in baptismGoalDateString). Tag each so the app can split the two populations.
        people = [(p, "new_member") for p in (pr.raw.get("newMemberList") or [])]
        people += [(p, "investigator") for p in (pr.raw.get("investigatorList") or [])]
        if include_returning:
            people += [(p, "returning") for p in (pr.raw.get("returningMemberList") or [])]

        # One-time PII-safe diagnostic for the calling under-count (#GH "double-check calling %"):
        # decides between two causes — (a) /mlt/api/orgs returns few callings (coverage), or (b) the
        # org-position uuids don't match the progress-record personUuids (matching). Logs counts +
        # one sample uuid from each source (uuids are opaque ids, not PII). On the next live sync,
        # check tools/output/logs: positions≈cohort but matched≈0 ⇒ uuid mismatch; positions small
        # ⇒ the orgs endpoint itself is sparse for this unit.
        if calling_uuids is not None:
            cohort_uuids = {p.get("personUuid") for p, _k in people if p.get("personUuid")}
            matched = cohort_uuids & calling_uuids
            stats["calling_positions"] = stats.get("calling_positions", 0) + len(calling_uuids)
            stats["calling_matched"] = stats.get("calling_matched", 0) + len(matched)
            if not stats.get("calling_shape_dumped"):
                stats["calling_shape_dumped"] = True
                pos_s, coh_s = next(iter(calling_uuids), None), next(iter(cohort_uuids), None)
                # logger.info → lands in the uploaded session log (dump_debug only writes to the
                # un-uploaded debug/ dir). uuids are opaque ids, not PII.
                logger.info("calling_match_shape unit=%s positions=%d cohort=%d matched=%d "
                            "pos_uuid=%s cohort_uuid=%s", unit.unit_number, len(calling_uuids),
                            len(cohort_uuids), len(matched), pos_s, coh_s)
                dump_debug("calling_match_shape", unit=unit.unit_number,
                           positions=len(calling_uuids), cohort=len(cohort_uuids),
                           matched=len(matched), position_uuid_sample=pos_s, cohort_uuid_sample=coh_s)

        for person, kind in people:
            details = _details_with_retry(client, person.get("id"), person.get("cmisId"))
            if details is None:
                stats["details_missing"] += 1
            info = member_maps.get(person.get("personUuid")) or member_maps.get(person.get("id")) or {}
            birth = info.get("birth")
            member = _assemble(person, details, unit.name, birth, kind=kind)
            member.sex = info.get("sex") or member.sex  # member list is authoritative for sex
            if calling_uuids is not None:  # org positions are authoritative for has-calling
                pu = person.get("personUuid")
                member.calling = "Yes" if (pu and pu in calling_uuids) else "No"
            member.unit_number = unit.unit_number
            uuid = person.get("personUuid")
            if uuid:
                seen_uuids.add(uuid)
            called_api = False
            if with_profile and uuid:
                cached = cache.get(uuid) if cache else None
                if cached is not None:
                    _apply_profile(member, cached)
                    stats["profile_cached"] += 1
                elif profile_blocked:
                    _mark_profile_blocked(member)
                    stats["profile_blocked"] += 1
                else:
                    called_api = True
                    try:
                        prof = profile_fields(client.session, uuid)
                        _apply_profile(member, prof)
                        if cache:
                            cache.put(uuid, prof)
                        stats["profile_ok"] += 1
                    except Exception as exc:  # noqa: BLE001
                        stats["profile_error"] += 1
                        profile_fail_streak += 1
                        _mark_profile_blocked(member)
                        logger.warning("profile fetch failed for %s (%s): %s",
                                       member.name, uuid, exc)
                        dump_debug("report_profile_fail", name=member.name,
                                   uuid=uuid, error=str(exc), can_profiles=can_profiles)
                        if not can_profiles and profile_fail_streak >= 3:
                            profile_blocked = True
                            if verbose:
                                print("    [access] profile fetches failing and calling lacks "
                                      "'Member Profiles' access -> marking remaining as blocked.")
                        elif verbose:
                            print(f"    [!] profile fetch failed for {member.name}: {exc}")
            results.append(member)
            stats["members"] += 1
            if called_api:
                time.sleep(delay)  # only throttle when we actually hit the API

        stats["units"] += 1
        if verbose:
            print(f"    {len(people)} covenant-path members")

    if cache:
        cache.prune(seen_uuids)
        cache.save()
        stats["cache"] = cache.stats
    logger.info("report complete: %s", stats)
    access["_run_stats"] = stats
    return results


def _field_coverage(dicts: list[dict]) -> dict[str, dict[str, int]]:
    """Per profile-gated field: how many rows are filled / blocked / pending."""
    cov: dict[str, dict[str, int]] = {}
    for fld in _PROFILE_GATED_FIELDS:
        c = {"filled": 0, "blocked": 0, "pending": 0}
        for d in dicts:
            v = d.get(fld)
            if v == BLOCKED:
                c["blocked"] += 1
            elif v in (NEEDS_PROFILE, None, ""):
                c["pending"] += 1
            else:
                c["filled"] += 1
        cov[fld] = c
    return cov


def _sanity_warnings(rows: list[CovenantPathMember], with_profile: bool) -> list[str]:
    """Flag distributions that suggest a silent failure (e.g. a stale action id).

    The data can look 'filled' while being uniformly wrong — the classic symptom of
    a rotated profile action id is EVERY member coming back with the empty value. We
    only warn above a sample size where uniformity is implausible.
    """
    warnings: list[str] = []
    n = len(rows)
    if not with_profile or n < 20:
        return warnings
    recs = [m.temple_recommend for m in rows]
    if all(v in (BLOCKED, NEEDS_PROFILE) for v in recs):
        return warnings  # access-blocked is already reported elsewhere
    active = sum(1 for v in recs if v in ("Active", "Expired"))
    if active == 0:
        warnings.append(
            f"temple_recommend is 'No' for all {n} members — the recommend action id "
            "may be stale. Verify with tools/health_check.py / re-run action discovery."
        )
    baptized = sum(1 for m in rows if m.baptism_date not in (NA, NEEDS_PROFILE, BLOCKED, None, ""))
    if baptized == 0:
        warnings.append(
            f"baptism_date is empty for all {n} members — the profile record action id "
            "may be stale."
        )
    for w in warnings:
        logger.warning("sanity: %s", w)
    return warnings


def export(rows: list[CovenantPathMember], access: dict | None = None,
           with_profile: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dicts = [asdict(r) for r in rows]
    (OUTPUT_DIR / "covenant_path_stake.json").write_text(
        json.dumps(dicts, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if dicts:
        # the JSON keeps the nested `details` subtree; the CSV stays flat/human-readable.
        flat_cols = [k for k in dicts[0].keys() if k != "details"]
        with (OUTPUT_DIR / "covenant_path_stake.csv").open(
            "w", newline="", encoding="utf-8-sig"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=flat_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(dicts)
    print(f"\n[+] {len(rows)} members -> {OUTPUT_DIR}")
    print("    - covenant_path_stake.json")
    print("    - covenant_path_stake.csv")

    if access is not None:
        coverage = _field_coverage(dicts)
        warnings = _sanity_warnings(rows, with_profile)
        summary = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "runner_positions": access.get("runner_positions"),
            "role_ids": access.get("role_ids"),
            "can_pull_all": access.get("can_pull_all"),
            "features": access.get("features"),
            "missing_who_to_ask": access.get("missing"),
            "run_stats": access.get("_run_stats"),
            "field_coverage": coverage,
            "sanity_warnings": warnings,
            "total_members": len(dicts),
        }
        (OUTPUT_DIR / "covenant_path_access.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("    - covenant_path_access.json  (access + field-coverage summary)")
        logger.info("field coverage: %s", coverage)
        blocked = [f for f, c in coverage.items() if c["blocked"]]
        if blocked:
            print(f"[access] blocked fields this run: {', '.join(blocked)} "
                  "(see covenant_path_access.json -> missing_who_to_ask)")
        for w in warnings:
            print(f"[!] SANITY: {w}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stake-level covenant-path report")
    parser.add_argument("--include-returning", action="store_true")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between detail calls")
    parser.add_argument("--with-profile", action="store_true",
                        help="also fetch baptism date / patriarchal blessing from the member-profile "
                             "server action (pure HTTP, one extra POST per member)")
    parser.add_argument("--no-cache", action="store_true",
                        help="disable the incremental profile cache (force fresh fetch of every member)")
    parser.add_argument("--cache-max-age-days", type=float, default=7.0,
                        help="reuse cached profile fields newer than this (0 = always refresh)")
    args = parser.parse_args()

    client = LcrClient()
    access = covenant_path_access(client)
    cache = ProfileCache(max_age_days=args.cache_max_age_days, enabled=not args.no_cache)
    rows = build_stake_report(
        client,
        include_returning=args.include_returning,
        delay=args.delay,
        with_profile=args.with_profile,
        access=access,
        cache=cache,
    )
    export(rows, access=access, with_profile=args.with_profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
