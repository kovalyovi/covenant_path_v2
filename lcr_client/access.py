"""
Access-aware self-check: map the running user's callings to LCR feature access.

LCR publishes a calling -> feature access matrix at /other/access-table (embedded
in the page's `__NEXT_DATA__`, not a separate API). We parse it and intersect with
the runner's current positions (from /api/user-context) to answer three things:
  1. which features can THIS user reach,
  2. which can't they, and
  3. which callings would grant the missing ones — so the script can pull what it
     can and tell you exactly who to ask (or who must "authorize") for the rest.

Verified facts (2026-05-26):
  - The matrix lives at props.pageProps.initialProps.accessTableData.membership =
    list of {name: <section i18n key>, features: [{name: <feature key>, roles: [int]}]}.
  - Each feature's `roles[]` uses the SAME id-space as `positionType.id` in
    user-context (e.g. 53 = Stake Assistant Clerk, 52 = Stake Clerk, 4 = Bishop).
  - `props.pageProps.initialProps.rolesData` = {id(str): calling name}, ~102 entries
    but INCOMPLETE for the matrix — many ids are unnamed. Names are resolved
    best-effort (merged with names seen in user-context); unknowns show as "role <id>".

CLI:  python -m lcr_client.access
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lcr_client.logging_setup import get_logger

logger = get_logger()

ACCESS_TABLE_URL = "https://lcr.churchofjesuschrist.org/other/access-table"
USER_CONTEXT_URL = "https://lcr.churchofjesuschrist.org/api/user-context"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# Persistent, self-improving role-id -> calling-name cache. The access-table page
# only names ~102 of the ~203 matrix role ids (rolesData); the rest are secondary
# seats (second counselors, secretaries, specialists). We seed the cache from
# rolesData and merge any positionType {id,name} we observe elsewhere (user-context,
# and future sources). We never fabricate names — unknown ids stay "role <id>".
NAME_CACHE_PATH = Path(__file__).resolve().parent.parent / "tools" / "output" / "role_names.json"


def _load_name_cache() -> dict[str, str]:
    if NAME_CACHE_PATH.exists():
        try:
            return json.loads(NAME_CACHE_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def register_names(mapping: dict) -> int:
    """Merge observed {id: calling name} pairs into the persistent cache. Returns #new."""
    cache = _load_name_cache()
    new = {str(k): v for k, v in mapping.items() if v and str(k) not in cache}
    if new:
        cache.update(new)
        NAME_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        NAME_CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("role-name cache: +%d names (total %d)", len(new), len(cache))
    return len(new)

# The access-table features that gate our covenant-path pipeline, in pull order.
# key -> (human label, what it unlocks for us)
COVENANT_PATH_FEATURES: dict[str, tuple[str, str]] = {
    "menu.progress.record": ("Covenant-path progress record", "new-member list per unit (core)"),
    "menu.member.list": ("Member list", "roster + birth dates"),
    "menu.view.member.profiles": (
        "Member profiles",
        "baptism, patriarchal-blessing flag, priesthood office, ministering",
    ),
    "menu.temple.recommend.status": ("Temple recommend status", "temple_recommend field"),
    "menu.patriarchal.blessing.status": (
        "Patriarchal blessing status",
        "dedicated report (we normally read the profile flag instead)",
    ),
    # NOTE: these two are perspective-based. "ward.leadership" = a STAKE leader's
    # view of ward leadership (granted to stake roles); "stake.leadership" = a WARD
    # leader's view of stake leadership (granted to ward roles). For a stake-level
    # runner the first applies; for a ward-level runner, the second.
    "menu.ward.leadership": ("Ward leadership (stake's view)", "who holds ward callings (who to ask)"),
    "menu.stake.leadership": ("Stake leadership (ward's view)", "who holds stake callings (who to ask)"),
}


@dataclass
class AccessMatrix:
    """Parsed calling -> feature access matrix from /other/access-table."""

    sections: list[dict] = field(default_factory=list)  # [{key, features:[{key, roles}]}]
    role_names: dict[str, str] = field(default_factory=dict)  # str(id) -> calling name
    _by_feature: dict[str, list] = field(default_factory=dict)  # feature key -> roles[]

    def feature_roles(self, feature_key: str) -> list:
        return self._by_feature.get(feature_key, [])

    def name(self, role_id: Any) -> str:
        return self.role_names.get(str(role_id)) or f"role {role_id}"

    def allows(self, feature_key: str, role_ids: set) -> bool:
        return bool(role_ids & set(self.feature_roles(feature_key)))


def _humanize(key: str) -> str:
    """Best-effort prettify of an i18n key like 'menu.temple.recommend.status'."""
    label = COVENANT_PATH_FEATURES.get(key, (None,))[0]
    if label:
        return label
    return key.split(".", 1)[-1].replace(".", " ").replace("-", " ").strip().capitalize()


def fetch_access_matrix(session) -> AccessMatrix:
    """Fetch + parse the calling->feature access matrix (membership side)."""
    html = session.get_text(ACCESS_TABLE_URL)  # auth-aware: auto-recovers on expiry
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError("access-table: __NEXT_DATA__ not found "
                           "(session expired without recovery, or page layout changed?)")
    props = json.loads(m.group(1))["props"]["pageProps"]["initialProps"]
    membership = props["accessTableData"]["membership"]
    # rolesData (authoritative, ~102) seeds the persistent cache; cache may add more.
    page_roles = {str(k): v for k, v in (props.get("rolesData") or {}).items()}
    register_names(page_roles)
    role_names = {**_load_name_cache(), **page_roles}

    sections, by_feature = [], {}
    for sec in membership:
        feats = []
        for f in sec.get("features", []):
            by_feature[f["name"]] = f.get("roles", [])
            feats.append({"key": f["name"], "roles": f.get("roles", [])})
        sections.append({"key": sec["name"], "features": feats})
    logger.info("access matrix: %d sections, %d features, %d named roles",
                len(sections), len(by_feature), len(role_names))
    return AccessMatrix(sections=sections, role_names=role_names, _by_feature=by_feature)


def runner_positions(session) -> list[dict]:
    """The running user's current callings: [{id, name, unit, unit_number}]."""
    ctx = session.get_json(USER_CONTEXT_URL)
    user = ctx.get("platformUserContext", {}).get("user", {})
    target = user.get("targetUser", {}) or {}
    seen, out = set(), []

    def add(pos):
        if not pos:
            return
        pt = pos.get("positionType") or {}
        pid = pt.get("id")
        if pid is None or pid in seen:
            return
        seen.add(pid)
        unit = pos.get("unit") or {}
        out.append({
            "id": pid,
            "name": pt.get("name") or f"position {pid}",
            "unit": unit.get("name"),
            "unit_number": unit.get("unitNumber"),
        })

    add(target.get("currentPosition"))
    for p in target.get("supportedPositions", []) or []:
        add(p)
    return out


def evaluate(matrix: AccessMatrix, role_ids: set, feature_keys: list[str] | None = None) -> list[dict]:
    """Per feature: can `role_ids` reach it, and which callings grant it if not."""
    keys = feature_keys if feature_keys is not None else list(matrix._by_feature)
    rows = []
    for key in keys:
        roles = matrix.feature_roles(key)
        allowed = bool(role_ids & set(roles))
        rows.append({
            "feature": key,
            "label": _humanize(key),
            "allowed": allowed,
            "granting_roles": [
                {"id": rid, "name": matrix.name(rid)}
                for rid in roles
                if not (isinstance(rid, str) and rid.startswith("ECC_ONLY_"))
            ],
        })
    return rows


def covenant_path_access(client) -> dict:
    """High-level access report for the covenant-path pipeline (runner-aware)."""
    session = client.session
    _maybe_enrich_names(client)  # one-time: fill the catalog from the leadership directory
    matrix = fetch_access_matrix(session)
    positions = runner_positions(session)
    role_ids = {p["id"] for p in positions}
    # persist + merge any names we learned from the runner's own positions
    register_names({p["id"]: p["name"] for p in positions})
    for p in positions:
        matrix.role_names.setdefault(str(p["id"]), p["name"])

    rows = evaluate(matrix, role_ids, list(COVENANT_PATH_FEATURES))
    missing = [r for r in rows if not r["allowed"]]
    return {
        "runner_positions": positions,
        "role_ids": sorted(i for i in role_ids if isinstance(i, int)),
        "features": rows,
        "can_pull_all": not missing,
        "missing": [_clean_missing(r) for r in missing],
    }


def _maybe_enrich_names(client) -> None:
    """One-time: enrich the name cache from the leadership directory (lazy, best-effort).

    rolesData seeds ~102 names; the leadership action adds the rest actually present in
    the stake. Once enriched the cache is large enough that this no-ops. Failures are
    non-fatal — names just stay as cached / "role N".
    """
    if len(_load_name_cache()) >= 150:  # rolesData ~102; post-leadership ~174
        return
    try:
        from lcr_client.leadership import enrich_role_names  # lazy: avoid import cycle
        enrich_role_names(client)
    except Exception as exc:  # noqa: BLE001
        logger.debug("role-name enrichment skipped: %s", exc)


def _clean_missing(row: dict) -> dict:
    """Actionable 'who to ask': named callings only (deduped), plus an unnamed count."""
    named, unnamed = [], 0
    for g in row["granting_roles"]:
        if str(g["name"]).startswith("role "):
            unnamed += 1
        elif g["name"] not in named:
            named.append(g["name"])
    return {"feature": row["label"], "granted_by": named, "also_unnamed_roles": unnamed}


def print_report(client) -> dict:
    rep = covenant_path_access(client)
    print("Runner positions:")
    for p in rep["runner_positions"]:
        unit = f" @ {p['unit']} ({p['unit_number']})" if p.get("unit") else ""
        print(f"  - {p['name']} [id {p['id']}]{unit}")
    print("\nCovenant-path data access:")
    for r in rep["features"]:
        mark = "OK " if r["allowed"] else "NO "
        gate = COVENANT_PATH_FEATURES.get(r["feature"], ("", ""))[1]
        print(f"  [{mark}] {r['label']:<28} {('- ' + gate) if gate else ''}")
    if rep["can_pull_all"]:
        print("\n=> This calling can reach ALL covenant-path features.")
    else:
        print("\n=> Features not granted to this calling (callings that grant them):")
        for m in rep["missing"]:
            names = ", ".join(m["granted_by"]) or "(no named callings)"
            extra = f" (+{m['also_unnamed_roles']} other seats)" if m.get("also_unnamed_roles") else ""
            print(f"   - {m['feature']}: {names}{extra}")
    print("\nNote: this reflects LCR's UI-menu access matrix, which is not 1:1 with")
    print("API access. Confirm actual data reachability with `tools/health_check.py`.")
    return rep


def main() -> int:
    from lcr_client import LcrClient

    print_report(LcrClient())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
