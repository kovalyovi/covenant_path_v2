# Regression for "missionary pictures disappeared" (2026-06-17): a plain daily sync rebuilds
# stakes.missionaries from the bulk companionships (which carry NO avatar) — only the periodic
# `--photos` pass attaches photo_url. Without carry-forward every nightly sync wiped the avatars
# (member photos survived because they live on the member row, not in the roster JSON).
# `carry_forward_missionary_photos` re-applies the previous roster's photo_url by uuid.

from backend.db import carry_forward_missionary_photos


def test_carries_forward_photo_url_by_uuid():
    prev = {
        "Ward A": [
            {"phone": "1", "missionaries": [
                {"uuid": "e1", "name": "Smith, John", "photo_url": "https://x/e1.jpg"},
                {"uuid": "e2", "name": "Doe, Mark", "photo_url": "https://x/e2.jpg"},
            ]},
        ],
    }
    # Freshly built roster from the bulk feed: same people, NO photo_url.
    new = {
        "Ward A": [
            {"phone": "1", "missionaries": [
                {"uuid": "e1", "name": "Smith, John"},
                {"uuid": "e2", "name": "Doe, Mark"},
            ]},
        ],
    }
    carry_forward_missionary_photos(prev, new)
    people = new["Ward A"][0]["missionaries"]
    assert people[0]["photo_url"] == "https://x/e1.jpg"
    assert people[1]["photo_url"] == "https://x/e2.jpg"


def test_new_photo_url_is_not_overwritten():
    prev = {"W": [{"missionaries": [{"uuid": "a", "photo_url": "old"}]}]}
    new = {"W": [{"missionaries": [{"uuid": "a", "photo_url": "fresh"}]}]}
    carry_forward_missionary_photos(prev, new)
    assert new["W"][0]["missionaries"][0]["photo_url"] == "fresh"


def test_tolerates_legacy_flat_shape_and_missing_uuid():
    prev = {"W": [{"uuid": "a", "name": "Old, One", "photo_url": "p"}]}  # flat (1 per entry)
    new = {"W": [{"uuid": "a", "name": "Old, One"}]}
    carry_forward_missionary_photos(prev, new)
    assert new["W"][0]["photo_url"] == "p"
    # No previous photos → nothing to carry, no error.
    carry_forward_missionary_photos({}, {"W": [{"uuid": "b"}]})


def test_uuid_not_present_in_new_roster_is_dropped():
    # A missionary who left keeps no stale photo on a roster that no longer lists them.
    prev = {"W": [{"missionaries": [{"uuid": "gone", "photo_url": "p"}]}]}
    new = {"W": [{"missionaries": [{"uuid": "here"}]}]}
    carry_forward_missionary_photos(prev, new)
    assert "photo_url" not in new["W"][0]["missionaries"][0]
