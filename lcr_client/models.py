"""
Typed models for LCR API responses.

These cover the fields the sync platform actually uses. Every model keeps the
full untouched payload in `.raw` so nothing is lost when LCR adds fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _first_email(raw: dict[str, Any]) -> str | None:
    emails = raw.get("emails") or []
    if emails and isinstance(emails[0], dict):
        return emails[0].get("email")
    return raw.get("email")


@dataclass
class AuthMe:
    """Identity from GET /api/auth/me."""

    name: str | None
    preferred_username: str | None
    cmis_id: str | None
    cmis_uuid: str | None
    personal_email: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "AuthMe":
        return cls(
            name=raw.get("name"),
            preferred_username=raw.get("preferred_username"),
            cmis_id=raw.get("churchCMISID"),
            cmis_uuid=raw.get("churchCMISUUID"),
            personal_email=raw.get("personalEmail"),
            raw=raw,
        )


@dataclass
class UnitRef:
    name: str | None
    unit_number: int | None
    type: str | None


@dataclass
class UserContext:
    """Current user, their active position, and the units they can access."""

    individual_id: str | None
    active_position: str | None
    unit_name: str | None
    unit_number: int | None
    positions: list[dict[str, Any]]
    roles: list[Any]
    child_units: list[UnitRef]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "UserContext":
        unit = raw.get("unit") or {}
        children = [
            UnitRef(c.get("unitName"), c.get("unitNumber"), c.get("type"))
            for c in (unit.get("children") or [])
        ]
        return cls(
            individual_id=raw.get("individualId"),
            active_position=raw.get("activePositionEnglish") or raw.get("activePosition"),
            unit_name=unit.get("unitName"),
            unit_number=unit.get("unitNumber"),
            positions=raw.get("positions") or [],
            roles=raw.get("roles") or [],
            child_units=children,
            raw=raw,
        )


@dataclass
class Member:
    """A member row from GET /api/umlu/report/member-list."""

    uuid: str | None
    name: str | None
    given_name: str | None
    family_name: str | None
    age: int | None
    sex: str | None
    email: str | None
    phone: str | None
    priesthood_office: str | None
    unit_name: str | None
    unit_number: int | None
    is_convert: bool
    is_member: bool
    is_out_of_unit: bool
    org_uuids: list[str]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Member":
        names = raw.get("nameFormats") or {}
        return cls(
            uuid=raw.get("uuid"),
            name=names.get("listPreferredLocal") or raw.get("nameListPreferredLocal"),
            given_name=names.get("givenPreferredLocal"),
            family_name=names.get("familyPreferredLocal"),
            age=raw.get("age"),
            sex=raw.get("sex"),
            email=_first_email(raw),
            phone=raw.get("phoneNumber"),
            priesthood_office=raw.get("priesthoodOffice"),
            unit_name=raw.get("unitName"),
            unit_number=raw.get("unitNumber"),
            is_convert=bool(raw.get("convert")),
            is_member=bool(raw.get("isMember")),
            is_out_of_unit=bool(raw.get("isOutOfUnitMember")),
            org_uuids=raw.get("unitOrgsCombined") or [],
            raw=raw,
        )


@dataclass
class UnitOrg:
    """An org/quorum/class from GET /api/umlu/unit-org."""

    uuid: str | None
    name: str | None
    unit_number: int | None
    org_type_ids: list[int]
    is_class: bool
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "UnitOrg":
        return cls(
            uuid=raw.get("unitOrgUuid"),
            name=raw.get("unitOrgName"),
            unit_number=raw.get("unitNumber"),
            org_type_ids=raw.get("unitOrgTypeIds") or [],
            is_class=bool(raw.get("isClass")),
            raw=raw,
        )


@dataclass
class ProgressPerson:
    """A person in the covenant-path progress record."""

    id: str | None
    name: str | None
    person_uuid: str | None
    cmis_id: Any | None
    sex: str | None
    weeks_since_last_attendance: int | None
    baptism_goal_date: str | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "ProgressPerson":
        return cls(
            id=raw.get("id"),
            name=raw.get("name"),
            person_uuid=raw.get("personUuid"),
            cmis_id=raw.get("cmisId"),
            sex=raw.get("sex"),
            weeks_since_last_attendance=raw.get("weeksSinceLastAttendance"),
            baptism_goal_date=raw.get("baptismGoalDateString"),
            raw=raw,
        )


@dataclass
class ProgressRecord:
    """GET /api/report/one-work/progress-record — the covenant-path report."""

    investigators: list[ProgressPerson]
    new_members: list[ProgressPerson]
    returning_members: list[ProgressPerson]
    parent_unit: Any | None
    read_only: bool
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "ProgressRecord":
        def people(key: str) -> list[ProgressPerson]:
            return [ProgressPerson.from_api(p) for p in (raw.get(key) or [])]

        return cls(
            investigators=people("investigatorList"),
            new_members=people("newMemberList"),
            returning_members=people("returningMemberList"),
            parent_unit=raw.get("parentUnit"),
            read_only=bool(raw.get("readOnly")),
            raw=raw,
        )
