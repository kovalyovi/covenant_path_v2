"""
Access levels by calling (feedback #1) — the HARDCODED scheme + the DYNAMICALLY-scraped catalog.

Three layers answer "who can pull what":
  1. The NAMED LEVEL SCHEME (hardcoded here): full / most / partial / none, derived from how many
     covenant-path DATA features a calling can reach (perspective-only features excluded, mirroring
     onboarding.coverage_of / access.can_pull_all).
  2. The BASELINE (hardcoded here): the well-known stake callings and the level we EXPECT them to
     hold. Seeded into calling_access_catalog so the platform has answers before the first scrape
     and so drift is visible (a scrape that downgrades a baseline calling is worth investigating).
  3. The SCRAPED CATALOG (dynamic): every daily sync inverts the LCR access matrix
     (feature -> granting role ids) into per-calling rows and upserts calling_access_catalog —
     so when the Church changes a calling's permissions, the catalog follows within a day.

The catalog is the durable knowledge; the per-credential access_rank/coverage stored on
stake_credentials (at enroll time) remains the authoritative record for "do we need a higher
credential for THIS stake" (onboarding.should_take_over reads it).
"""

from __future__ import annotations

from lcr_client.logging_setup import get_logger

logger = get_logger()

# Perspective-only features carry "who to ask", not member data — excluded from level math,
# mirroring lcr_client.access._PERSPECTIVE_FEATURES / can_pull_all.
_PERSPECTIVE = {"menu.ward.leadership", "menu.stake.leadership"}


def level_of(granted_data_features: int, total_data_features: int) -> str:
    """The hardcoded level scheme: full = every data feature; most = ≥75%; partial = ≥1; none = 0."""
    if total_data_features <= 0:
        return "none"
    if granted_data_features >= total_data_features:
        return "full"
    if granted_data_features >= 0.75 * total_data_features:
        return "most"
    if granted_data_features > 0:
        return "partial"
    return "none"


# Hardcoded BASELINE — the levels we expect for the well-known stake/ward callings (LCR position-type
# ids, names for readability). Seeded with source='baseline'; the daily scrape overwrites with
# source='scrape' rows, so any drift from these expectations shows up as a changed level.
BASELINE: list[tuple[int, str, str]] = [
    (1, "Stake President", "full"),
    (2, "Stake Presidency First Counselor", "full"),
    (3, "Stake Presidency Second Counselor", "full"),
    (51, "Stake Executive Secretary", "full"),
    (52, "Stake Clerk", "full"),
    (55, "Stake Assistant Clerk", "full"),
    (4, "Bishop", "partial"),       # ward-scoped: full within their ward, not the stake
    (57, "Ward Clerk", "partial"),
    (94, "High Councilor", "partial"),
]


def seed_baseline(conn) -> int:
    """Insert the hardcoded baseline rows (only where no scraped row exists yet)."""
    n = 0
    with conn.cursor() as cur:
        for role_id, name, level in BASELINE:
            cur.execute(
                """insert into calling_access_catalog (role_id, calling_name, level, source)
                   values (%s, %s, %s, 'baseline')
                   on conflict (role_id) do nothing""",
                (role_id, name, level))
            n += cur.rowcount
    conn.commit()
    return n


def persist_catalog(conn, access_rows: list[dict]) -> int:
    """Invert the evaluated access matrix (feature -> granting callings) into per-calling rows and
    upsert the catalog. `access_rows` is covenant_path_access()['features']:
    [{feature, allowed, granting_roles: [{id, name}]}]. Returns rows written."""
    total_data = sum(1 for r in access_rows if r.get("feature") not in _PERSPECTIVE)
    by_role: dict[int, dict] = {}
    for row in access_rows:
        feature = row.get("feature")
        for g in row.get("granting_roles") or []:
            rid = g.get("id")
            if not isinstance(rid, int):
                continue
            ent = by_role.setdefault(rid, {"name": g.get("name"), "features": set()})
            if g.get("name"):
                ent["name"] = g["name"]
            ent["features"].add(feature)
    n = 0
    with conn.cursor() as cur:
        for rid, ent in by_role.items():
            feats = sorted(ent["features"])
            data_count = sum(1 for f in feats if f not in _PERSPECTIVE)
            cur.execute(
                """insert into calling_access_catalog
                       (role_id, calling_name, features, feature_count, level, source, updated_at)
                   values (%s, %s, %s, %s, %s, 'scrape', now())
                   on conflict (role_id) do update set
                       calling_name = coalesce(excluded.calling_name, calling_access_catalog.calling_name),
                       features = excluded.features,
                       feature_count = excluded.feature_count,
                       level = excluded.level,
                       source = 'scrape',
                       updated_at = now()""",
                (rid, ent["name"], feats, data_count, level_of(data_count, total_data)))
            n += 1
    conn.commit()
    logger.info("calling access catalog: %d callings persisted (%d data features)", n, total_data)
    return n
