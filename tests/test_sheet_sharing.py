"""
Sheet-sharing access rules (catalog row C7) — offline, no Google, no DB.

1. backend.sheet_access.compute_recipients — the policy itself: WHO gets the stake (master)
   sheet vs each ward's sheet; missionaries attach by unit; stake leaders see every ward;
   callings outside the policy (ward clerks, instructors...) are NEVER auto-shared; a released
   leader simply isn't in the fresh role rows and so drops out.
2. sheets_sync.service.reconcile_viewers — the enforcement: the file's viewers become EXACTLY
   the target set; the notification email goes ONLY to NEWLY-added viewers (existing viewers are
   untouched — no notify fatigue); the file owner and the service account are never removed.

Run: python -m pytest tests/test_sheet_sharing.py -q
"""

from __future__ import annotations

from backend.sheet_access import compute_recipients

# --- 1. the policy -----------------------------------------------------------------------------

W1, W2 = "unit-1", "unit-2"


def _role(email: str, calling: str, unit_id: str | None = None, unit_name: str | None = None) -> dict:
    return {"email": email, "calling_name": calling, "role": "x",
            "unit_id": unit_id, "unit_name": unit_name}


def test_recipients_follow_the_sharing_policy_exactly():
    roles = [
        # stake-sheet callings (stake-wide stewardship)
        _role("pres@example.org", "Stake President"),
        _role("hc@example.org", "High Councilor"),
        _role("sclerk@example.org", "Stake Assistant Clerk"),
        # ward-1 sheet callings
        _role("bishop1@example.org", "Bishop", W1, "First Ward"),
        _role("eq1@example.org", "Elders Quorum President", W1, "First Ward"),
        _role("rs1@example.org", "Counselor in the Relief Society Presidency", W1, "First Ward"),
        _role("wml1@example.org", "Ward Mission Leader", W1, "First Ward"),
        # NOT on the sharing policy — must never be auto-shared anywhere
        _role("wclerk1@example.org", "Ward Clerk", W1, "First Ward"),
        _role("teacher1@example.org", "Sunday School Teacher", W1, "First Ward"),
        # ward-2 sheet calling
        _role("bishop2@example.org", "Bishop", W2, "Second Ward"),
        # junk rows the computation must tolerate
        _role("", "Bishop", W2, "Second Ward"),
        _role("no-at-sign", "Stake President"),
    ]
    missionaries = {"First Ward": [{"email": "Elder.One@example.org"}, {"email": ""}]}

    rec = compute_recipients(roles, missionaries)

    assert rec["stake"] == {"pres@example.org", "hc@example.org", "sclerk@example.org"}
    # Ward sheets = that ward's policy callings + its missionaries + EVERY stake recipient.
    assert rec["wards"][W1] == rec["stake"] | {
        "bishop1@example.org", "eq1@example.org", "rs1@example.org", "wml1@example.org",
        "elder.one@example.org",
    }
    assert rec["wards"][W2] == rec["stake"] | {"bishop2@example.org"}
    # The non-policy callings leaked nowhere.
    everyone = rec["stake"] | set().union(*rec["wards"].values())
    assert "wclerk1@example.org" not in everyone
    assert "teacher1@example.org" not in everyone
    assert rec["ward_names"] == {W1: "First Ward", W2: "Second Ward"}


def test_released_leader_drops_out_of_the_fresh_recipient_set():
    before = compute_recipients([_role("bishop1@example.org", "Bishop", W1, "First Ward")])
    after = compute_recipients([_role("newbishop@example.org", "Bishop", W1, "First Ward")])
    assert "bishop1@example.org" in before["wards"][W1]
    assert "bishop1@example.org" not in after["wards"][W1]  # reconcile will REMOVE them


# --- 2. the enforcement (reconcile_viewers vs a fake Drive) -------------------------------------


class _Call:
    def __init__(self, result=None):
        self.result = result

    def execute(self):
        return self.result


class _FakePermissions:
    """Records create/delete; serves one page of existing permissions."""

    def __init__(self, existing: list[dict]):
        self.existing = existing
        self.created: list[dict] = []
        self.deleted: list[str] = []

    def list(self, fileId, fields, pageToken=None):  # noqa: N803 — Google API casing
        return _Call({"permissions": self.existing})

    def create(self, fileId, sendNotificationEmail, body):  # noqa: N803
        self.created.append({"email": body["emailAddress"], "notify": sendNotificationEmail,
                             "role": body["role"]})
        return _Call({})

    def delete(self, fileId, permissionId):  # noqa: N803
        self.deleted.append(permissionId)
        return _Call({})


class _FakeDrive:
    def __init__(self, perms: _FakePermissions):
        self._perms = perms

    def permissions(self):
        return self._perms


def test_reconcile_notifies_only_new_viewers_and_never_touches_owner_or_sa(monkeypatch):
    from sheets_sync import service

    perms = _FakePermissions([
        {"id": "p-owner", "emailAddress": "leader-owner@example.org", "role": "owner", "type": "user"},
        {"id": "p-sa", "emailAddress": "sync-sa@example.org", "role": "writer", "type": "user"},
        {"id": "p-keep", "emailAddress": "bishop-keep@example.org", "role": "reader", "type": "user"},
        {"id": "p-old", "emailAddress": "released-leader@example.org", "role": "reader", "type": "user"},
    ])

    class _FakeCreds:
        service_account_email = "sync-sa@example.org"

    monkeypatch.setattr(service.Credentials, "from_service_account_file",
                        staticmethod(lambda *a, **k: _FakeCreds()))
    monkeypatch.setattr(service, "build", lambda *a, **k: _FakeDrive(perms))

    out = service.reconcile_viewers("sheet-1",
                                    ["bishop-keep@example.org", "Bishop-NEW@example.org"],
                                    service_account_file="ignored.json", notify=True)

    # Notification email goes ONLY to the newly-added viewer — the kept viewer is untouched.
    assert perms.created == [{"email": "bishop-new@example.org", "notify": True, "role": "reader"}]
    # Only the no-longer-entitled viewer is removed; owner + service account survive.
    assert perms.deleted == ["p-old"]
    assert out == {"added": 1, "removed": 1, "kept": 1}


def test_reconcile_notify_false_adds_silently(monkeypatch):
    from sheets_sync import service

    perms = _FakePermissions([])

    class _FakeCreds:
        service_account_email = "sync-sa@example.org"

    monkeypatch.setattr(service.Credentials, "from_service_account_file",
                        staticmethod(lambda *a, **k: _FakeCreds()))
    monkeypatch.setattr(service, "build", lambda *a, **k: _FakeDrive(perms))

    service.reconcile_viewers("sheet-1", ["quiet@example.org"],
                              service_account_file="ignored.json", notify=False)
    assert perms.created == [{"email": "quiet@example.org", "notify": False, "role": "reader"}]
