"""
Build a complete, verified schema of the LCR API objects we consume.

Samples many real responses across every data source (member-list, unit-org,
user-context, auth/me, progress-record, one-work details, and the 3 member-
profile server actions), merges them into a per-object field schema (observed
types, optional vs required, nullable, example value), and writes:

  tools/output/lcr_schema.json   machine-readable schema tree
  tools/output/lcr_schema.md     human-readable field list per object

Broad sampling (esp. across many members) is how we capture optional fields
that only appear for some records (temple recommend, endowment, prior unit...).

Usage:
  python tools/build_schema.py [--profile-sample N] [--details-sample N]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcr_client import LcrClient
from lcr_client.member_profile import (
    MINISTERING_ACTION_ID, PROFILE_ACTION_ID, RECOMMEND_ACTION_ID,
    call_action, _find,
)

OUT = Path(__file__).parent / "output"


# --- schema inference --------------------------------------------------------

def observe(node: dict, value) -> None:
    node["count"] = node.get("count", 0) + 1
    if value is None:
        node["nulls"] = node.get("nulls", 0) + 1
        return
    if isinstance(value, dict):
        node["kind"] = "object"
        fields = node.setdefault("fields", {})
        present = node.setdefault("present", {})
        node["objCount"] = node.get("objCount", 0) + 1
        for k, v in value.items():
            observe(fields.setdefault(k, {}), v)
            present[k] = present.get(k, 0) + 1
    elif isinstance(value, list):
        node["kind"] = "array"
        items = node.setdefault("items", {})
        for el in value:
            observe(items, el)
    else:
        node["kind"] = "scalar"
        t = ("boolean" if isinstance(value, bool)
             else "number" if isinstance(value, (int, float)) else "string")
        node.setdefault("types", {})
        node["types"][t] = node["types"].get(t, 0) + 1
        ex = node.setdefault("examples", [])
        if len(ex) < 3 and value not in ex:
            ex.append(value)


def flatten(node: dict, path: str, rows: list, parent_obj_count: int | None = None,
            present: int | None = None) -> None:
    kind = node.get("kind", "?")
    nullable = node.get("nulls", 0) > 0
    optional = parent_obj_count is not None and present is not None and present < parent_obj_count
    if kind == "scalar":
        types = "|".join(sorted(node.get("types", {})))
        ex = node.get("examples", [])
        rows.append((path, types or "null", optional, nullable, ex[0] if ex else ""))
    elif kind == "object":
        rows.append((path, "object", optional, nullable, ""))
        oc = node.get("objCount", 0)
        for k, child in sorted(node.get("fields", {}).items()):
            flatten(child, f"{path}.{k}" if path else k, rows, oc, node["present"].get(k, 0))
    elif kind == "array":
        rows.append((path, "array", optional, nullable, ""))
        flatten(node.get("items", {}), path + "[]", rows, parent_obj_count, present)
    else:
        rows.append((path, "null/empty", optional, nullable, ""))


# --- sampling ----------------------------------------------------------------

def build(client: LcrClient, profile_sample: int, details_sample: int) -> dict:
    schemas: dict[str, dict] = {}

    def add(name, value):
        observe(schemas.setdefault(name, {}), value)

    print("[*] user-context + auth/me")
    ctx = client.user_context()
    add("UserContext", ctx.raw)
    add("AuthMe", client.whoami().raw)

    units = [u for u in ctx.child_units if u.unit_number and u.type in ("WARD", "BRANCH")]
    all_members = []  # (personUuid, cmisId, id) for profile/detail sampling
    progress_people = []

    for unit in units:
        print(f"[*] {unit.name}: member-list, unit-org, progress-record")
        for m in client.member_list(unit.unit_number):
            add("Member", m.raw)
            if m.raw.get("personUuid"):
                all_members.append(m.raw["personUuid"])
        for o in client.unit_orgs(unit.unit_number):
            add("UnitOrg", o.raw)
        pr = client.progress_record(unit.unit_number)
        add("ProgressRecord", pr.raw)
        for key in ("newMemberList", "returningMemberList", "investigatorList"):
            for p in pr.raw.get(key) or []:
                add("ProgressPerson", p)
                progress_people.append(p)

    # one-work details (sample of progress people)
    random.shuffle(progress_people)
    for p in progress_people[:details_sample]:
        try:
            add("OneWorkDetails", client.progress_details(p.get("id"), p.get("cmisId")))
        except Exception:
            pass

    # profile actions (broad member sample to catch optional fields)
    random.shuffle(all_members)
    sample = all_members[:profile_sample]
    print(f"[*] profile actions for {len(sample)} members (record/recommend/ministering)")
    for i, uuid in enumerate(sample):
        try:
            rec = _find(call_action(client.session, uuid, PROFILE_ACTION_ID, [uuid, "eng"]),
                        "uuid", "ordinances")
            if rec:
                add("ProfileRecord", rec)
        except Exception:
            pass
        try:
            r = _find(call_action(client.session, uuid, RECOMMEND_ACTION_ID, [uuid]), "recommend")
            if r:
                add("RecommendResult", r)
        except Exception:
            pass
        try:
            m = (_find(call_action(client.session, uuid, MINISTERING_ACTION_ID, [uuid]),
                       "ministeringBrothersAssignments")
                 or _find(call_action(client.session, uuid, MINISTERING_ACTION_ID, [uuid]),
                          "ministeringSistersAssignments"))
            if m:
                add("MinisteringResult", m)
        except Exception:
            pass
        if (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(sample)}")

    return schemas


def render_md(schemas: dict) -> str:
    lines = ["# LCR API Object Schema", "",
             "Inferred from live responses. `optional` = absent in some samples; "
             "`nullable` = observed null. Sample counts in parentheses.", ""]
    for name in sorted(schemas):
        node = schemas[name]
        lines.append(f"## {name}  (sampled {node.get('count', 0)})")
        lines.append("")
        lines.append("| field | type | presence | example |")
        lines.append("|---|---|---|---|")
        rows = []
        flatten(node, "", rows)
        for path, types, optional, nullable, ex in rows:
            if not path:
                continue
            presence = "optional" if optional else "required"
            if nullable:
                presence += ", nullable"
            ex_s = json.dumps(ex)[:50] if ex != "" else ""
            lines.append(f"| `{path}` | {types} | {presence} | {ex_s} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile-sample", type=int, default=50)
    ap.add_argument("--details-sample", type=int, default=60)
    args = ap.parse_args()

    client = LcrClient()
    schemas = build(client, args.profile_sample, args.details_sample)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lcr_schema.json").write_text(json.dumps(schemas, indent=2, default=list), encoding="utf-8")
    (OUT / "lcr_schema.md").write_text(render_md(schemas), encoding="utf-8")

    print("\n=== schema built ===")
    for name in sorted(schemas):
        rows = []
        flatten(schemas[name], "", rows)
        print(f"  {name:18} sampled={schemas[name].get('count',0):4}  fields={len(rows)}")
    print(f"\n-> {OUT/'lcr_schema.json'}\n-> {OUT/'lcr_schema.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
