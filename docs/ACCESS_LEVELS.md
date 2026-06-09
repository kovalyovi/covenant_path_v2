# Access levels by calling — the model, the baseline, and how it stays current

Answers feedback #1: *"define access levels based on callings, save as hardcoded + dynamically
updated when scraping; do roles update when LCR changes; does this determine whether we need a
higher credential?"* Companion to `ACCESS_MODEL.md` (who-sees-what) and `SCENARIOS.md` (tests).

## The named level scheme (hardcoded)

`backend/access_levels.py` defines the scheme; a calling's level is how many covenant-path **data**
features it can reach in LCR (the two perspective-only leadership features are excluded, exactly
like `can_pull_all`):

| Level | Meaning |
|---|---|
| **full** | every data feature — this credential pulls the complete dataset |
| **most** | ≥ 75% of data features |
| **partial** | at least one data feature (e.g. ward-scoped callings) |
| **none** | no covenant-path data access (blocked at login by the N2 gate) |

A hardcoded **BASELINE** (`access_levels.BASELINE`) seeds the expected levels for the well-known
callings (stake presidency / clerks / exec sec → full; bishop / ward clerk / high councilor →
partial) so the platform has answers before the first scrape — and so **drift is visible**: a scrape
that downgrades a baseline calling means the Church changed that calling's permissions.

## The dynamic catalog (updated every scrape)

Every daily sync inverts the scraped LCR access matrix (feature → granting callings, ~90 features ×
~174 named roles) into per-calling rows and upserts **`calling_access_catalog`** (migration 0040):
`role_id, calling_name, features[], feature_count, level, source(baseline|scrape), updated_at`.
Admin-only RLS. If LCR changes a calling's permissions, the catalog reflects it within a day.

## Do roles update when LCR changes? — YES, two mechanisms

1. **App access (who can see data):** `provision_roles` runs on **every daily sync** — it re-reads
   the org callings and **grants new leaders / auto-revokes released ones** (audited in
   `access_audit`). A calling change in LCR propagates to app access within a day.
2. **The sync credential:** `_revoke_if_ineligible` re-verifies on **every sync** that the
   credential provider's calling **still** grants covenant-path access — a released leader's stored
   session is conservatively revoked (the stake then shows "re-authorize", and any authorized leader
   can take over).

## Does this decide whether a higher credential is needed? — YES, stored on the credential

At enroll time the broker stores the session's **`access_rank`** (`can_pull_all` → 1000, else the
granted-feature count) **and `coverage`** (complete? what's missing? who to ask) on
`stake_credentials`. Then:

- **`should_take_over`** (backend/onboarding.py): when the active credential is *incomplete* and a
  newly-signed-in leader's access would *strictly improve* it, the app offers them the takeover
  ("can_improve"). A complete credential never bothers anyone.
- **Enroll RPC (migration 0038)**: most-elevated-wins — a lower-access leader can never downgrade a
  healthy higher credential; same-principal / equal-rank / stale-credential re-enrolls DO refresh.
- The **fast login path** (perf fix) skips the live access probe only when the stake already has a
  usable credential — whenever the level question matters (enroll / takeover / no usable
  credential), the full live probe runs and its result is stored.

## Re-authorization cadence — why, and how often

**Credentials cannot self-renew** (verified 2026-06-09): the OAuth `interaction_code → refresh_token`
exchange is rejected by the Church's Okta with `invalid_client`, and the IDX flow is bound to the
`/oauth2/default` server while tokens are issued by a different auth server our headless replay can't
complete against. So `has_refresh_token` is effectively always false, and renewal relies on:

1. **Stored LCR appSession** (tier 1) — extends each time the daily sync uses it.
2. **Okta re-SSO** via the stored persistent session cookie (tier 2) — now `rememberMe=true`, so the
   Okta session lasts **weeks** instead of hours; the daily sync re-SSOs off it.

**Expected cadence:** a healthy, daily-syncing stake needs manual re-auth roughly **every few weeks**
(whenever the persistent Okta session finally expires), not every few days. A stake whose sync is
*failing* (LCR outage, released leader) goes stale immediately — surfaced via the stale banner +
alert. The ops console shows per-stake `authorized <ago> · manual re-auth · N re-auths/30d` so the
real cadence is observable. (If the Church ever provisions an offline-token client, self-renewal
drops straight in via the existing 3-tier renewal.)

## Source of truth map

| Concern | Where |
|---|---|
| Level scheme + hardcoded baseline | `backend/access_levels.py` (`level_of`, `BASELINE`) |
| Dynamic per-calling catalog | `calling_access_catalog` (migration 0040), refreshed in `backend/sync.py` |
| Live per-session rank/coverage | `lcr_client/access.py` → `backend/onboarding.py` |
| Stored per-stake credential level | `stake_credentials.access_rank` + `.coverage` |
| Higher-credential decisions | `onboarding.should_take_over` + enroll RPC (0038) |
| Daily role refresh + auto-revoke | `backend/roles.py provision_roles` (audited, 0034) |
| Credential calling re-verification | `scripts/daily_sync.py _revoke_if_ineligible` |
| Admin overrides (no deploy) | `calling_access_overrides` (0035, ops console) |
