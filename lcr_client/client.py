"""
High-level LCR client.

Wraps the reverse-engineered LCR JSON endpoints (see tools/output/lcr_api_catalog.md)
with typed return values. Auth/session handling lives in LcrSession.

Example:
    from lcr_client import LcrClient
    lcr = LcrClient()
    me = lcr.whoami()
    ctx = lcr.user_context()
    for u in ctx.child_units:
        members = lcr.member_list(u.unit_number)
"""

from __future__ import annotations

from pathlib import Path

from lcr_client.auth import LcrSession
from lcr_client.models import (
    AuthMe,
    Member,
    ProgressRecord,
    UnitOrg,
    UserContext,
)

LCR = "https://lcr.churchofjesuschrist.org"


class LcrClient:
    def __init__(self, session: LcrSession | None = None, **session_kwargs) -> None:
        self.session = session or LcrSession(**session_kwargs)

    # --- identity / context ------------------------------------------------

    def whoami(self) -> AuthMe:
        return AuthMe.from_api(self.session.get_json(f"{LCR}/api/auth/me"))

    def user_context(self) -> UserContext:
        return UserContext.from_api(self.session.get_json(f"{LCR}/api/user-context"))

    # --- members / orgs ----------------------------------------------------

    def member_list(self, unit_number: int) -> list[Member]:
        data = self.session.get_json(
            f"{LCR}/api/umlu/report/member-list", {"unitNumber": unit_number}
        )
        return [Member.from_api(m) for m in data]

    def unit_orgs(self, unit_number: int) -> list[UnitOrg]:
        data = self.session.get_json(
            f"{LCR}/api/umlu/unit-org", {"unitNumber": unit_number}
        )
        return [UnitOrg.from_api(o) for o in data]

    # --- covenant path (one-work) -----------------------------------------

    def progress_record(self, unit_number: int) -> ProgressRecord:
        data = self.session.get_json(
            f"{LCR}/api/report/one-work/progress-record", {"unitNumber": unit_number}
        )
        return ProgressRecord.from_api(data)

    def progress_details(self, person_uuid: str, legacy_cmis_id: int | str) -> dict:
        return self.session.get_json(
            f"{LCR}/api/report/one-work/details/{person_uuid}",
            {"legacyCmisId": legacy_cmis_id},
        )

    # --- reports -----------------------------------------------------------

    def quarterly_report(self, unit_number: int | None = None) -> dict:
        params = {"unitNumber": unit_number} if unit_number else None
        return self.session.get_json(f"{LCR}/api/cld/reports/quarterly-report", params)


if __name__ == "__main__":
    # Smoke test against the live session captured by the crawler.
    import json

    client = LcrClient()
    me = client.whoami()
    print("Authenticated as:", me.name, f"({me.preferred_username})")

    ctx = client.user_context()
    print(f"Active position: {ctx.active_position}")
    print(f"Unit: {ctx.unit_name} ({ctx.unit_number})")
    print(f"Accessible child units: {len(ctx.child_units)}")
    for u in ctx.child_units[:5]:
        print(f"  - {u.name} ({u.unit_number}) [{u.type}]")

    if ctx.child_units:
        sample = ctx.child_units[0]
        members = client.member_list(sample.unit_number)
        print(f"\n{sample.name}: {len(members)} members")
        if members:
            print("  e.g.", members[0].name, "-", members[0].age, members[0].sex)

    state = Path(__file__).resolve().parent.parent / "tools" / "output"
    (state / "smoke_test.json").write_text(
        json.dumps({"me": me.raw, "context_unit": ctx.unit_name}, indent=2),
        encoding="utf-8",
    )
