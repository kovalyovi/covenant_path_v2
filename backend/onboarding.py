"""
Onboarding helpers for multi-stake delegated sync.

When a leader signs in with their Church account, the broker can store their session as the
stake's delegated credential (see backend/credentials.save_credential), after which the daily
delegated sync pulls that stake automatically. Several leaders of one stake may onboard over
time; we keep the *most elevated* session — the one whose calling can see the most covenant-path
data — so the sync gets the fullest dataset (a stake president's session beats an assistant
clerk's, and a lower-access login never downgrades a stake a higher-access leader already set up).

Graceful low-access handling already lives in covenant_path.report: the access summary lists
which callings to ask for any blocked feature, so the app can say "have someone with <calling>
sign in" when the onboarding session can't see everything.
"""

from __future__ import annotations


def access_rank(access: dict | None) -> int:
    """Higher = sees more covenant-path data. 'can_pull_all' tops it; otherwise count granted
    features from the access matrix. Drives should_replace_credential()."""
    if not access:
        return 0
    if access.get("can_pull_all"):
        return 1000
    return sum(1 for f in (access.get("features") or []) if f.get("allowed"))


def should_replace_credential(existing_rank: int | None, new_rank: int) -> bool:
    """Store/replace the stake's credential only when the new session has strictly more access,
    so onboarding can elevate (clerk -> president) but never downgrade."""
    return existing_rank is None or new_rank > existing_rank
