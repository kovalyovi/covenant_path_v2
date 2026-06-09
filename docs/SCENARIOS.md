# Scenario matrix — access / sync / data-correctness

**Purpose:** a single, explicit enumeration of every access / sync / data-correctness scenario the
platform must handle, the **expected behavior**, and the **exact function that enforces it**. Each
row is exercised by an automated check.

Two complementary test surfaces prove these rows:

| Surface | File | Needs | Proves |
|---|---|---|---|
| **OFFLINE matrix** (this doc's primary driver) | [`backend/test_scenarios.py`](../backend/test_scenarios.py) + [`backend/fake_db.py`](../backend/fake_db.py) | **nothing** — no DB, no network, no secrets | the REAL Python logic (`roles`, `db`, `credentials`, `report`) against an in-memory DB + fake LCR |
| **LIVE SQL** | `test_rls.py`, `test_power_users.py`, `test_admins.py`, `test_login_audit.py`, `test_reconcile.py`, `test_field_meta.py`, `test_calling_overrides.py` | a Supabase DB (rolled back) | the SQL itself — RLS policies, SECURITY DEFINER RPCs, admin-only grants |

> Run the offline matrix with **`python -m backend.test_scenarios`** (≈0.2 s, exits non-zero on any
> failure). It generates its own `CP_TOKEN_KEY` and never touches Supabase/LCR. The LIVE tests cover
> the same access rules at the SQL boundary; where a row is *only* provable in SQL (e.g. the RLS
> `USING` clause, the enroll RPC `WHERE`), the offline suite asserts a faithful Python mirror and the
> table below names the LIVE test that proves the real thing.

**One-sentence model:** a church **calling** → provisions a **role** (`stake_leader` / `ward_leader`)
→ **RLS** returns only that role's rows; a degraded/failed fetch **never clobbers good data** (merge
by stable ID + sentinels + freshness); every grant/revoke and login is **audited, admin-only**.

---

## Axis 1 — subject role → RLS scope

| # | Subject | Expected | Enforced by | Offline check | LIVE proof |
|---|---|---|---|---|---|
| 1.1 | **stake leader** | sees **every** member in the stake (`unit_id IS NULL` role) | RLS `members_select` (0002/0004) | `scenario_role_scope_and_visibility` | `test_rls.py` |
| 1.2 | **ward leader** | sees **only their unit's** members | RLS `members_select` (`unit_id = members.unit_id`) | `scenario_role_scope_and_visibility` | `test_rls.py` |
| 1.3 | **non-leader member** | sees **nothing** (no `user_roles` row) | RLS returns zero rows | `scenario_role_scope_and_visibility` | `test_rls.py` (anon) |
| 1.4 | **non-member** (no login / no role) | sees **nothing** | RLS (`auth.uid()` null, no email match) | `scenario_role_scope_and_visibility` | `test_rls.py` (anon) |
| 1.5 | leader matched by **verified email** (no LCR identity) | scoped by `lower(email) = jwt email` | RLS email branch (0004) | `scenario_role_scope_and_visibility` | `test_power_users.py` |

## Axis 2 — access level vs the existing credential/role (same / higher / lower / none)

Applies to the **enroll RPC** (which leader's delegated session backs a stake) — "most-elevated wins"
with same-principal-refresh and stale-takeover. SQL is migration **0038**; the offline suite asserts
the decision table the broker relies on.

| # | Incoming vs stored | Expected | Enforced by | Offline check |
|---|---|---|---|---|
| 2.1 | **none** stored | insert | `enroll_stake_credential` (0038) | `scenario_enroll_most_elevated_wins` |
| 2.2 | **same** principal (refresh) | replace (you can always renew your own session) | 0038 `principal_email` clause | `scenario_enroll_most_elevated_wins` |
| 2.3 | **higher** access, different leader | replace | 0038 `access_rank >` clause | `scenario_enroll_most_elevated_wins` |
| 2.4 | **equal** access, different leader | replace (fresher session wins) | 0038 `access_rank >=` clause | `scenario_enroll_most_elevated_wins` |
| 2.5 | **lower** access, different leader, stored **healthy** | **keep** stored (no clobber) | 0038 WHERE all-false | `scenario_enroll_most_elevated_wins` |
| 2.6 | **lower** access, but stored is **failing/stale** | replace (takeover of a dead credential) | 0038 `last_failed_at is not null` | `scenario_enroll_most_elevated_wins` |
| 2.7 | **lower** access, but stored is **incomplete** coverage | replace | 0038 `coverage->>'complete' = false` | `scenario_enroll_most_elevated_wins` |

## Axis 3 — admin vs non-admin

| # | Actor | Expected | Enforced by | Offline check | LIVE proof |
|---|---|---|---|---|---|
| 3.1 | **admin** | can read the audit/log surfaces + ops console | `is_admin()` (0008) + RLS `using (is_admin())` | `scenario_audit_is_admin_only_and_complete`, `scenario_admin_view_revoke_add_access` | `test_admins.py`, `test_login_audit.py` |
| 3.2 | **non-admin** | **cannot** read any audit/login table | RLS `using (is_admin())` → 0 rows | `scenario_audit_is_admin_only_and_complete` | `test_login_audit.py` |
| 3.3 | **admin invite/revoke** another admin | admin-gated, escalation-safe, can't revoke self | `invite_admin`/`revoke_admin` (0008) | — (RPC) | `test_admins.py` |
| 3.4 | admin **add / revoke access** (power user / ward grant) | clones only scopes the caller holds; revoke scoped | `invite_power_user`/`revoke_power_user` (0005) | `scenario_admin_view_revoke_add_access` | `test_power_users.py` |
| 3.5 | admin **add calling→access override** | admin-gated, admin-only visible | `add_calling_override` (#3c) + `roles._load_overrides` | `scenario_admin_added_calling_override` | `test_calling_overrides.py` |

## Axis 4 — data-fetch outcomes (failure vs success; per-field empty / removed / added / modified)

The core invariant: **reconcile updates BY stable ID and never lets a partial/failed fetch clobber
good data.**

| # | Outcome | Expected | Enforced by | Offline check |
|---|---|---|---|---|
| 4.1 | **success** — member NAME/UNIT modified (same `person_uuid`) | updated **in place**, no duplicate row | `db.upsert_members` (conflict on `person_uuid`) | `scenario_upsert_merge_by_id_modified_added_removed` |
| 4.2 | **added** member | inserted | `db.upsert_members` | `scenario_upsert_merge_by_id_modified_added_removed` |
| 4.3 | **absent** from this run | upsert never deletes; reconcile (gated) handles departures | `db.upsert_members` / `db.reconcile_members` | `scenario_upsert_merge_by_id_modified_added_removed`, `scenario_reconcile_departed_safe_and_gated` |
| 4.4 | **removed** — departed member, unit scraped **cleanly** | hard-deleted | `db.reconcile_members` | `scenario_reconcile_departed_safe_and_gated` |
| 4.5 | **removed** — member of a unit that **FAILED** this run | **preserved** (not in keep-set) | `db.reconcile_members` (keep-set gate) | `scenario_reconcile_departed_safe_and_gated` |
| 4.6 | **empty** report / empty keep-set | **no-op** (a bad run never wipes a roster) | `db.reconcile_members` / `db.prune_units` gates | `scenario_reconcile_departed_safe_and_gated`, `scenario_prune_units_gated_orphans_members` |
| 4.7 | **per-field empty/partial** — profile-gated field returns a sentinel | merge **preserves last-good** (no clobber with sentinel) | `db._merge_expr` / `upsert_members` | `scenario_sentinel_preserves_last_good` |
| 4.8 | **genuine empty** (`friends_count = 0`, confirmed) | accepted (distinct from "unknown" `None`) | `db._merge_expr` (`friends_count` coalesce) | `scenario_sentinel_preserves_last_good` |
| 4.9 | **freshness** — fetched stamps `f`; sentinel keeps prior `f`, bumps `t` | staleness grows; value never blanked | `db._field_meta` | `scenario_field_freshness_tracking` |
| 4.10 | **freshness rollup** — fresh / warn(>3d) / error(>7d) / never | per-field staleness visible to admin | `db.field_staleness_summary` | `scenario_field_freshness_tracking` |
| 4.11 | **unit left the stake** — prune | unit removed; members orphan to `unit_id NULL`; ward roles cascade | `db.prune_units` | `scenario_prune_units_gated_orphans_members` |
| 4.12 | **fetch failure** — bare progress record (no profile) | profile fields → `NEEDS_PROFILE` (not a false "No"); → `BLOCKED` after mark | `report._assemble` + `_mark_profile_blocked` | `scenario_report_no_profile_emits_sentinels` |
| 4.13 | **modified field** — profile UNIONs with org-aggregate | profile "Yes" upgrades; profile "No" **never downgrades** a real "Yes" (calling + ministering) | `report._apply_profile` | `scenario_report_profile_union_never_downgrades` |
| 4.14 | **silent stale-action** — a whole cohort uniformly "No" | neutralized → sentinel (preserve last-good, show stale); a single real "Yes" prevents it; small cohort (<20) never | `report._neutralize_uniform_stale` | `scenario_report_neutralize_uniform_stale` |
| 4.15 | **timeout/500 per unit** end-to-end | failed unit skipped (not fatal); other units survive; degraded fields preserved on re-upsert | `report.build_stake_report` + `db.upsert_members` | `scenario_report_degraded_fetch_end_to_end` |

## Axis 5 — access changes (remove / add / modify)

| # | Change | Expected | Enforced by | Offline check |
|---|---|---|---|---|
| 5a.1 | **calling changed** — leader **released** | revoked on next provision (calling-derived row deleted) + **audited** | `roles.provision_roles` revoke clause + `_audit_access` | `scenario_calling_changed_revoke_and_add` |
| 5a.2 | **calling changed** — **new** callee | gains role on next provision + **audited** | `roles.provision_roles` upsert + `_audit_access` | `scenario_calling_changed_revoke_and_add` |
| 5a.3 | **non-data calling** (e.g. Primary Pianist) | granted **nothing** | `roles._can_see` (matrix gate) | `scenario_provision_grants_by_calling` |
| 5a.4 | always-allowed stewardship calling, matrix incomplete | granted anyway (stake-prefixed names only) | `roles._calling_always_allowed` + `_STAKE_PREFIXES` filter | `scenario_always_allowed_calling_safety_net` |
| 5a.5 | leadership fetch **empty/failed** | revoke **gated** off — prior leaders preserved (never "everyone released") | `roles.provision_roles` `stake_ok`/`ward_ok` gate | `scenario_revoke_gated_on_directory_fetch` |
| 5a.6 | **manual / power-user (invitation)** grant | **survives** a provision run (NULL `lcr_person_uuid`, not rebuilt) | `roles.provision_roles` revoke filter (`lcr_person_uuid is not null`) | `scenario_email_and_invitation_rows_preserved` |
| 5b.1 | **credential expired/stale** — sync fails | failing state stamped (`last_failed_at`, `last_error`) | `credentials.mark_failed` | `scenario_credential_staleness_alert_edge` |
| 5b.2 | **alert edge** — one alert per failure streak | `claim_stale_notification` True only the **first** failure after a success | `credentials.claim_stale_notification` | `scenario_credential_staleness_alert_edge` |
| 5b.3 | **recovery** — sync succeeds | clears failing + notified so the next failure re-alerts | `credentials.mark_succeeded` | `scenario_credential_staleness_alert_edge` |
| 5b.4 | credential at rest | session blob is **envelope-encrypted**, never plaintext; round-trips | `credentials.save_credential` / `get_credential` | `scenario_credential_save_roundtrip_encrypted` |

## Axis 6 — logging & visibility (every issue admin-visible + protected)

| # | Concern | Expected | Enforced by | Offline check | LIVE proof |
|---|---|---|---|---|---|
| 6.1 | every grant/revoke recorded | `access_audit` row per change, with calling + scope + source | `roles._audit_access` (0034) | `scenario_audit_is_admin_only_and_complete` | — |
| 6.2 | audit is **admin-only** | non-admin / anon read **nothing** | RLS `using (is_admin())` (0034) | `scenario_audit_is_admin_only_and_complete` | `test_login_audit.py` |
| 6.3 | **under-visibility** — allowed login resolves to no scope | detectable (`role_scope = 'none'` → empty app) | `login_audit.role_scope` (0034) + RLS scope | `scenario_under_and_over_visibility_signals` | `test_login_audit.py` |
| 6.4 | **over-visibility** — viewer sees a stake they shouldn't | impossible (RLS scopes by stake) — asserted absent | RLS `members_select` (stake match) | `scenario_under_and_over_visibility_signals` | `test_rls.py` |
| 6.5 | admin can **view / revoke / add** access from the console | enumerate roles; add/revoke a grant changes what the target sees | `user_roles` + RLS; power-user RPCs | `scenario_admin_view_revoke_add_access` | `test_power_users.py` |
| 6.6 | login emails / callings are PII | live **only** in admin-only tables, never in Axiom | `observability.py` PII drop + RLS | — | `test_login_audit.py` |

---

## Coverage summary

- **22 scenarios / 124 checks**, all green offline (`python -m backend.test_scenarios`).
- All six matrix axes covered for the **stable** subsystems: RLS scope, calling-based provisioning
  (grant/revoke/gating/overrides/always-allowed), data reconciliation (merge-by-id, sentinel
  preservation, freshness, prune, departed-reconcile), report assembly correctness
  (no-profile/union/neutralize/degraded-end-to-end), credential staleness/expiry/takeover, and
  audit completeness + admin-only protection.
- The suite drives the **real imported code**; only the DB rows + LCR payloads are in-memory
  (`backend/fake_db.py`). Where the authoritative behavior is pure SQL (RLS `USING`, the enroll RPC
  `WHERE`, RPC bodies), the offline suite asserts a faithful mirror and the LIVE test named above
  proves the SQL itself.

## Real bugs found

**None.** Every initial red check traced to test-scaffolding (live-reference snapshots, the
`field_meta` clock, an over-broad fake) or to a scenario mis-modeling the real rule — corrected to
match the actual code, not the other way around. Two behaviors worth recording as *confirmed
correct* (they surprised the first draft):

1. **`provision_roles` only considers stake positions whose calling NAME starts with a stake prefix**
   (`Stake/District/Mission/Area`) before the always-allowed safety net applies. So "High Council"
   (not stake-prefixed) is **not** picked up as a stake position via `org_callings`; a stake-prefixed
   always-allowed calling (e.g. "Stake Executive Secretary") is. This is by design (the always-allowed
   list is a safety net layered *on top of* the stake-prefix filter), documented here so it isn't
   later mistaken for a gap.
2. **Calling is a definitive "No" only when `org_callings` is fetchable-but-empty; a fetch *failure*
   leaves it a sentinel.** `build_stake_report` sets `calling = "No"` when `calling_uuids` is an empty
   set, but `None` (fetch failed) leaves `NEEDS_PROFILE`/`BLOCKED` so the merge-upsert preserves
   last-good. Correct, and the distinction matters for the "degraded fetch must not clobber" invariant.

---

## New features — landed, with their coverage

These were the in-flight features; they shipped (commits `5ae7de8`, `b83a809`, `9a79d9c`, `6afa1af`,
`4364c34`). Coverage status:

- [x] **Per-stake sync trigger** — `enroll._kickoff_initial_sync` now dispatches `daily-sync.yml` with
      `stake=<unit>` (the prepare job's `--only` scopes the matrix to that one stake), so an enroll
      syncs ONLY that stake — no cross-stake bleed (the "one leader's enroll re-synced everyone" bug).
      The per-stake schedule already lived in `list_stake_units` + `_due_today` (covered by the live
      sync). Dispatch is mocked in `test_broker` (`daily-sync.yml` is dispatchable).
- [x] **Unenroll tiers** — `revoke` (credential only, roles stay) · `wipe_stake_members` (delete
      members, keep stake+roles+cred) · `remove_stake` (credential+members+roles+diagnostics+stake row).
      The two new tiers are SECURITY DEFINER RPCs (migration `0039`), exercised by the live SQL path;
      `revoke` + the most-elevated-wins re-enroll are covered offline by `scenario_enroll_most_elevated_wins`.
- [x] **Stale / takeover** — **covered offline**: `scenario_credential_staleness_alert_edge` proves
      `mark_failed`/`claim_stale_notification` fire ONE alert per failure streak and `mark_succeeded`
      clears it (no spam); `scenario_enroll_most_elevated_wins` proves the 0038 takeover (same-principal
      refresh + stale → any authorized leader can take over). The client banner just derives from
      `credential.state === 'stale'` + `is_provider` (broker `enrollment_status`); the empty/banner
      copy is in `EmptyState.tsx` / `dashboard.tsx`.
- [x] **(parity)** stale banner + per-stake ops ported to native (commit `72582df`); the re-auth
      modal + cadence line port is in flight — see `native/PARITY.md`.

## Later additions (2026-06-09 evening) — behavior + where enforced

- **Degraded-run reconcile guard** (`backend/sync.py` + `db.count_reconcile_candidates`): when ANY
  unit failed the run, >3 would-be member deletions are DEFERRED (a `reconcile_deferred` diagnostic
  is written) — LCR 500s can thin even the "successful" units' rosters, and 10 same-day "departures"
  during an outage are degraded data, not moves (live case 2026-06-09). Healthy runs unchanged.
- **Login-eval time budget** (`app.py _login_eval`): a NON-consent login waits ≤4s for the access
  eval (fast path answers inline; a full first-eval continues in a background thread, audit still
  written). Consent (enroll=true) stays synchronous. Client picks up offers from
  `/auth/enrollment-status`. Result: plain sign-ins complete in seconds.
- **Okta-stage failure audit** (`app.py _audit_okta_failure`): wrong password / failed MFA now write
  `login_audit` rows (`okta_failed` / `mfa_failed`) — previously a member stuck AT the login screen
  left zero server-side trace.
- **Per-stake dispatch — all three trigger paths**: on-enroll kickoff, admin ops, AND the provider's
  `/auth/sync-now` each pass `stake=<unit>`; a trigger can never fan out the whole matrix.
- **Cadence visibility** (migration 0041): `has_refresh_token` recorded at enroll (self-renewing vs
  manual-re-auth credentials) + `reauths_30d` from `login_audit` enrolled events, shown per stake in
  the ops console.
