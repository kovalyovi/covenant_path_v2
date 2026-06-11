"""Fixture-row builders for the Supabase stub — all values FICTIONAL (Testvale 999001)."""

from __future__ import annotations

from tests.mock_lcr.personas import PERSONAS, STAKE_NAME, STAKE_UNIT, Persona

STAKE_ID = "a0000000-0000-4000-8000-000000000001"
PRESIDENT = PERSONAS["president.complete"]
WARD_LEADER = PERSONAS["wardleader.partial"]

COMPLETE_COVERAGE = {
    "complete": True,
    "features": ["menu.progress.record", "menu.member.list", "menu.view.member.profiles",
                 "menu.temple.recommend.status", "menu.patriarchal.blessing.status",
                 "menu.ward.leadership"],
    "missing": [],
}
PARTIAL_COVERAGE = {
    "complete": False,
    "features": ["menu.progress.record", "menu.member.list", "menu.view.member.profiles",
                 "menu.stake.leadership"],
    "missing": [{"feature": "Temple recommend status",
                 "granted_by": ["Stake President", "Stake Clerk"], "also_unnamed_roles": 0}],
}


def stake_row(**over) -> dict:
    row = {"id": STAKE_ID, "unit_number": STAKE_UNIT, "name": STAKE_NAME,
           "onboarded_at": "2026-06-01T00:00:00+00:00",
           "last_synced_at": "2026-06-09T10:00:00+00:00", "sync_state": None}
    row.update(over)
    return row


def credential_row(**over) -> dict:
    row = {"stake_id": STAKE_ID,
           "principal_name": PRESIDENT.name, "principal_email": PRESIDENT.email,
           "granting_role_ids": [1], "credential_enc": '{"v":2,"mock":"seeded"}',
           "coverage": COMPLETE_COVERAGE, "access_rank": 1000,
           "expires_at": None, "has_refresh_token": True,
           "revoked": False, "revoked_at": None,
           "updated_at": "2026-06-08T00:00:00+00:00",
           "last_failed_at": None, "last_error": None, "stale_notified_at": None}
    row.update(over)
    return row


def identity_row(p: Persona = PRESIDENT, **over) -> dict:
    row = {"username": p.username, "email": p.email, "name": p.name,
           "cmis_id": p.cmis_id, "cmis_uuid": p.cmis_uuid,
           "unit_number": p.unit_number, "stake_name": p.unit_name,
           "has_calling": True, "updated_at": "2026-06-09T00:00:00+00:00"}
    row.update(over)
    return row


def role_row(email: str, *, stake_id: str = STAKE_ID, unit_id: str | None = None,
             role: str = "stake_leader", **over) -> dict:
    row = {"auth_id": None, "stake_id": stake_id, "unit_id": unit_id, "role": role,
           "email": email, "lcr_person_uuid": None, "source": "calling"}
    row.update(over)
    return row
