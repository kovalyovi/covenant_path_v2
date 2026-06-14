"""
Deep, PII-safe profiler of the Member Tools `/api/v5/sync` payload (+ a few LCR endpoints).

Reuses the project's own auth (lcr_client.okta_login) — one sync-equivalent call, read-only.
Produces a COMPLETE recursive field map (every nested path, type, fill count, array sizes, and
low-cardinality enum values) — going well beyond tools/membertools_probe.py's top-level key dump.

Outputs (tools/output/api_profile/, gitignored):
  raw/*.json            full responses (REAL data — local only)
  schema/*.schema.json  flat path -> {types,count,examples,array lens}   (PII-safe)
  schema/*.schema.md    rendered indented tree                            (PII-safe)
  profile_summary.txt   human summary (printed too)

PII safety: leaf example VALUES are captured only for booleans and short, low-cardinality strings
whose key is not name/email/phone/address/birth/uuid/id/etc. Numbers are never sampled (could be
ids/dates). The raw/ dump has real values and stays gitignored.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"D:\dev\covenant_path_v2")
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

OUT = ROOT / "tools" / "output" / "api_profile"
(OUT / "raw").mkdir(parents=True, exist_ok=True)
(OUT / "schema").mkdir(parents=True, exist_ok=True)

_PII = ("name", "email", "phone", "mobile", "address", "street", "city", "state", "postal",
        "zip", "birth", "dob", "uuid", "guid", "cmis", "legacy", "spoken", "given", "surname",
        "preferred", "nickname", "latitude", "longitude", "coord", "photo", "image", "household",
        "principal", "login", "password", "token", "secret", "ssn", "displayname", "fullname",
        # additional leaf keys that carry member PII in /api/v5/sync
        "listed", "formatted", "mrn", "number", "e164", "monogram", "family", "username",
        "county", "handle", "official", "spokensort", "listedsort", "familysort")
_DATEISH = re.compile(r"^\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}")


def _is_pii_key(key: str) -> bool:
    k = key.lower()
    return any(p in k for p in _PII)


class Schema:
    """Accumulates a flat path -> typeinfo map over one or more JSON documents."""

    def __init__(self) -> None:
        self.paths: dict[str, dict] = defaultdict(
            lambda: {"types": set(), "count": 0, "examples": set(), "min_len": None, "max_len": None})

    def walk(self, node, path: str = "") -> None:
        rec = self.paths[path]
        rec["count"] += 1
        if isinstance(node, bool):
            rec["types"].add("bool")
            if len(rec["examples"]) < 4:
                rec["examples"].add(str(node))
        elif isinstance(node, dict):
            rec["types"].add("object")
            for k, v in node.items():
                self.walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            rec["types"].add("array")
            ln = len(node)
            rec["min_len"] = ln if rec["min_len"] is None else min(rec["min_len"], ln)
            rec["max_len"] = ln if rec["max_len"] is None else max(rec["max_len"], ln)
            for item in node:
                self.walk(item, path + "[]")
        elif node is None:
            rec["types"].add("null")
        elif isinstance(node, (int, float)):
            rec["types"].add(type(node).__name__)
        else:  # string
            rec["types"].add("str")
            leaf = path.split(".")[-1].replace("[]", "")
            s = str(node)
            if (not _is_pii_key(leaf) and 0 < len(s) <= 28 and not _DATEISH.match(s)
                    and sum(c.isdigit() for c in s) < 5   # skip phones / MRNs / account numbers
                    and len(rec["examples"]) < 10):
                rec["examples"].add(s)

    def to_json(self) -> dict:
        out = {}
        for p in sorted(self.paths):
            r = self.paths[p]
            out[p or "(root)"] = {
                "types": sorted(r["types"]),
                "count": r["count"],
                "array_len": None if r["min_len"] is None else [r["min_len"], r["max_len"]],
                "examples": sorted(r["examples"])[:10],
            }
        return out

    def to_md(self) -> str:
        lines = []
        for p in sorted(self.paths):
            depth = p.count(".") + p.count("[]")
            r = self.paths[p]
            label = p.split(".")[-1] if p else "(root)"
            types = "/".join(sorted(r["types"]))
            extra = ""
            if r["min_len"] is not None:
                extra += f" len={r['min_len']}..{r['max_len']}"
            if r["examples"]:
                extra += f"  e.g. {', '.join(sorted(r['examples'])[:8])}"
            lines.append(f"{'  ' * depth}- `{label}` — {types} (×{r['count']}){extra}")
        return "\n".join(lines)


def field_fill(arr: list) -> dict:
    """Per-key fill counts across a list-of-objects (how many entries have a non-null value)."""
    keys = set()
    for o in arr:
        if isinstance(o, dict):
            keys |= set(o.keys())
    fill = {}
    for k in sorted(keys):
        n = sum(1 for o in arr if isinstance(o, dict) and o.get(k) not in (None, "", [], {}))
        fill[k] = f"{n}/{len(arr)}"
    return fill


def save(name: str, raw, schema: Schema, summary: list) -> None:
    (OUT / "raw" / f"{name}.json").write_text(json.dumps(raw, indent=2)[:25_000_000], encoding="utf-8")
    (OUT / "schema" / f"{name}.schema.json").write_text(
        json.dumps(schema.to_json(), indent=2), encoding="utf-8")
    (OUT / "schema" / f"{name}.schema.md").write_text(schema.to_md(), encoding="utf-8")
    summary.append(f"[{name}] {len(schema.paths)} distinct field paths -> schema/{name}.schema.md")


def main() -> int:
    summary: list[str] = []
    from lcr_client import membertools, okta_login

    login_id, pw = os.getenv("LCR_LOGIN"), os.getenv("LCR_PASSWORD")

    # --- acquire a Member Tools access token WITHOUT a fresh (MFA-blocked) login ---
    access_token = how = None
    ss_path = ROOT / "tools" / "output" / "storage_state.json"
    # 1) mint off the existing (fresh) Okta session captured in storage_state.json
    if ss_path.exists():
        try:
            cookies = json.loads(ss_path.read_text(encoding="utf-8")).get("cookies", [])
            sess = okta_login.session_from_cookies(cookies)
            access_token = membertools.mint_from_okta_session(sess)["access_token"]
            how = "minted off storage_state.json Okta session"
        except Exception as exc:  # noqa: BLE001
            print(f"    storage_state mint failed: {str(exc)[:160]}")
    # 2) renew off a stored 45-day Member Tools refresh token (delegated_grants.enc)
    if not access_token:
        try:
            from lcr_client import token_store
            for su, g in token_store._read_all().items():
                rt = (g.get("membertools") or {}).get("refresh_token")
                if rt:
                    access_token = membertools.refresh(rt)["access_token"]
                    how = f"refreshed stored Member Tools token (stake {su})"
                    break
        except Exception as exc:  # noqa: BLE001
            print(f"    stored-refresh-token path failed: {str(exc)[:160]}")
    # 3) last resort: fresh password login (fails when MFA is enabled)
    if not access_token and login_id and pw:
        try:
            sess = okta_login.new_session()
            okta_login._authenticate_okta(sess, login_id, pw)
            access_token = membertools.mint_from_okta_session(sess)["access_token"]
            how = "fresh password login"
        except Exception as exc:  # noqa: BLE001
            print(f"    fresh login failed (MFA?): {str(exc)[:160]}")
    if not access_token:
        print("[!] Could not obtain a Member Tools token by any method."); return 3
    print(f"[+] Member Tools token acquired ({how}).")

    # ---- Member Tools: /api/v5/sync (the core deliverable) ----
    print("[*] POST /api/v5/sync ...")
    sync = membertools.fetch_sync(access_token)
    sch = Schema(); sch.walk(sync)
    save("membertools_sync", sync, sch, summary)

    summary.append("")
    summary.append("=== /api/v5/sync TOP-LEVEL ===")
    if isinstance(sync, dict):
        for k in sorted(sync):
            v = sync[k]
            kind = (f"array[{len(v)}]" if isinstance(v, list)
                    else f"object[{len(v)} keys]" if isinstance(v, dict) else type(v).__name__)
            summary.append(f"  {k}: {kind}")
        # field fill-rates for each top-level person/array list
        for k, v in sync.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                summary.append(f"\n--- {k}: per-field fill (n={len(v)}) ---")
                for key, rate in field_fill(v).items():
                    summary.append(f"    {key}: {rate}")

    # ---- /api/v5/sync/files (defined in membertools.py but unused) ----
    print("[*] Probing /api/v5/sync/files ...")
    import requests
    files_info = {}
    for method in ("POST", "GET"):
        try:
            r = requests.request(
                method, membertools.SYNC_FILES_URL,
                headers={"Authorization": f"Bearer {access_token}",
                         "Accept": "application/json", "Content-Type": "application/json",
                         "User-Agent": membertools.USER_AGENT},
                data=json.dumps(membertools.SYNC_BODY) if method == "POST" else None, timeout=60)
            files_info[method] = {"status": r.status_code, "ctype": r.headers.get("content-type", "")}
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                body = r.json()
                fsch = Schema(); fsch.walk(body)
                save("membertools_sync_files", body, fsch, summary)
                break
        except Exception as exc:  # noqa: BLE001
            files_info[method] = {"error": str(exc)[:120]}
    summary.append(f"\n=== /api/v5/sync/files probe ===\n  {files_info}")

    # ---- A few LCR endpoints (schema only; LCR side already catalogued) ----
    print("[*] Sampling LCR endpoints off the existing storage_state.json ...")
    try:
        from lcr_client import LcrClient
        lcr = LcrClient()  # reads tools/output/storage_state.json (fresh ~1h ago)
        for name, fn in (("lcr_auth_me", lambda: lcr.whoami().raw),
                         ("lcr_user_context", lambda: lcr.user_context().raw),
                         ("lcr_dashboard_data", lcr.dashboard_data)):
            try:
                data = fn()
                s2 = Schema(); s2.walk(data); save(name, data, s2, summary)
            except Exception as exc:  # noqa: BLE001
                summary.append(f"[{name}] skipped: {str(exc)[:120]}")
    except Exception as exc:  # noqa: BLE001
        summary.append(f"[lcr endpoints] skipped: {str(exc)[:160]}")

    text = "\n".join(summary)
    (OUT / "profile_summary.txt").write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"\n[+] Done. Artifacts in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
