"""
Onboarding helpers for multi-stake delegated sync.

When a leader signs in with their Church account, the broker can store their session as one of
the stake's delegated credentials (see backend/credentials.save_credential), after which the daily
delegated sync pulls that stake automatically. Several leaders of one stake may onboard over
time; we keep them ALL and the sync always uses the *most elevated* one — the session whose
calling can see the most covenant-path data — so the sync gets the fullest dataset (a stake
president's session beats an assistant clerk's). A lower-access enrollment is never refused: it
is stored as a standby and becomes effective automatically if the broader credential is revoked
or lapses (0068). The old single-row "most-elevated-wins by refusal" rule (0055) discarded
narrower enrollments entirely — and refused the provider's own re-auth when their fresh session
scraped a lower rank than their stored credential (2026-11-08).

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
    """Whether a new session would become the stake's EFFECTIVE credential (0068): strictly more
    access than the current effective one. A lower/equal session is still STORED (as a standby) —
    this only decides effectiveness, never storage."""
    return existing_rank is None or new_rank > existing_rank


def coverage_of(access: dict | None) -> dict:
    """Summarize what a session can pull, for storage + the partial-access UI:
      {features: [allowed feature keys], complete: bool, missing: [who-to-ask rows]}."""
    if not access:
        return {"features": [], "complete": False, "missing": []}
    allowed = [f["feature"] for f in (access.get("features") or []) if f.get("allowed")]
    return {
        "features": allowed,
        "complete": bool(access.get("can_pull_all")),
        "missing": access.get("missing") or [],
    }


def should_take_over(active: dict | None, candidate_access: dict | None) -> bool:
    """Whether a newly-signed-in leader should be nudged to provide their credential. Only when
    the ACTIVE credential is missing data AND the candidate would strictly improve coverage
    (more access). If the active credential already pulls everything, nobody is ever nudged."""
    if active is None:  # no credential on file -> always offer
        return True
    if active.get("coverage", {}).get("complete"):
        return False  # active is already complete; don't bother anyone
    cand = coverage_of(candidate_access)
    if cand["complete"]:
        return True  # candidate completes what's missing
    # otherwise only if the candidate's access strictly exceeds the active credential's
    return access_rank(candidate_access) > (active.get("access_rank") or 0)
