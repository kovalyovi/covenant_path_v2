# Architecture Decision Log

Running log of significant decisions — context, options, the choice, and the
pros/cons/drawbacks/wins — so future work (and future LLM sessions) preserve intent.
Newest first.

---

## ADR-005 — Client apps: one Flutter codebase reading the backend (2026-05-27)

**Context.** Goal: backend separated from clients; iOS/macOS/Android/Web apps (one Flutter
codebase) read data scoped by stake/login/permissions. Question raised: "why not Flutter for
web and everything?"

**Findings.** (1) A peer's app (github rickybloomfield/Mission-KPIs) is native Swift/iOS with
our exact structure (LCRClient/OktaAuthSession/NextDataParser), talking to LCR directly on
device — single-user, no backend. (2) Flutter for all platforms IS one codebase; the only
constraint is that a **web build can't call LCR directly (browser CORS)** — native can.

**Decision.** Clients read the **backend (Supabase)**, never LCR — so CORS is a non-issue and
Flutter web works like every other platform. LCR scraping stays only in the backend (daily
sync). Live on-device scraping is an optional native-only future add-on.

**Client auth.** The project uses **asymmetric (ECC P-256) JWT signing keys**, so we CANNOT mint
custom JWTs (no private key) and the legacy HS256 secret is being retired — the planned
"auth-bridge mints a JWT with LCR identity" is dead. Instead: **Supabase Auth (email OTP / Google)**
and **RLS matches the verified email claim** (`auth.jwt()->>'email'`) to a role. Roles are
provisioned with email from LCR member data (0004 migration; roles.py). No shared secret, no
Edge Function bridge, no client LCR creds.
**Pros.** Standard, all-platform, nothing secret on the client, survives the key migration.
**Cons.** Login email must match the email LCR has on file (else no scope) — acceptable; admin
override possible later. **Verified:** a login with the Stake President's email → all 112 members.

**Status.** `apps/viewer/` Flutter scaffold (login + RLS-scoped dashboard) committed; not run here
(no Flutter SDK) — user runs `flutter create . && flutter run`. Onboarding app (#2) and email
digests (#4) still ahead.

---

## ADR-003 — Getting the daily GitHub Actions sync green (2026-05-27)

**Context.** First live CI runs of `scripts/daily_sync.py` failed three times; each
failure taught us something. Documented so we don't relearn it.

**Failure 1 — one flaky unit crashed the whole run.** `progress-record` for unit 458821
(Seabrook Branch, Spanish) returned HTTP 500 and the exception aborted the entire stake
report. **Fix:** `report.py` now retries per-unit calls and *skips* a unit that keeps
failing (records `failed_units`), so the run completes with the other units. NOTE: 458821
500s **persistently right now (even locally)** — it's an LCR-side issue with that unit,
not transient; the skip is the correct behavior until LCR recovers.

**Failure 2 — missing dependency.** `ModuleNotFoundError: psycopg2`. It was pip-installed
locally but never added to `requirements.txt`, so CI couldn't import the backend. **Fix:**
added `psycopg2-binary`. Lesson: anything imported must be in requirements, not just local.

**Failure 2b — Sheets is destructive on partial scrapes.** Sheets sync is a full A3:Z
replace, so a skipped unit would *delete its rows*. (Run 2's Sheets push, before the
psycopg2 crash, did drop Seabrook's 12 rows.) **Fix:** `sheets_sync` now takes
`preserve_units` — existing rows for units that failed to scrape are kept as-is. Supabase
upserts are already non-destructive (stale rows persist), so the two stores degrade safely.

**Failure 3 — Supabase direct endpoint is IPv6-only.** `psycopg2.OperationalError: Network
is unreachable` on an IPv6 address. Supabase's **direct** host `db.<ref>.supabase.co:5432`
(and the *dedicated* pooler) are **IPv6-only**; **GitHub Actions runners are IPv4-only**.
**Fix:** use the **shared pooler** `aws-1-us-east-1.pooler.supabase.com:5432`, user
`postgres.<ref>` — **IPv4 and free on every tier** (the $4/mo "dedicated IPv4" add-on is
NOT needed). Region derived from the DB IP via AWS `ip-ranges.json` (us-east-1); the project
is on the `aws-1-` pooler generation (`aws-0-` returns "Tenant or user not found"). Local
dev can still use the direct/IPv6 URL; **CI must use the pooler**.

**Outcome (verified live).** Green run: headless Okta login from CI ✓, scrape (101 members,
Seabrook skipped gracefully) ✓, Sheets updated (preserving skipped unit) ✓, Supabase upsert
over IPv4 pooler ✓ — `stakes.last_synced_at` + `members.updated_at` stamped from the CI run.
**Wins:** resilient to flaky units + partial scrapes, no paid add-ons, fully headless daily.
**Drawback:** a persistently-failing unit (458821) won't refresh until LCR fixes it; its data
stays as last-known-good in both stores (not lost).

---

## ADR-002 — Cutting LCR call volume for the daily multi-stake job (2026-05-26)

**Context.** The report's dominant cost is per-member: 1 `progress_details` call + 3
member-profile server actions (record/recommend/ministering) ≈ 4 calls/member, ~470
calls for a 112-member stake. Running daily across many stakes multiplies that.

**Options considered.**
1. **Bulk unit-level reports** — reverse-engineer the Temple Recommend Status /
   Ministering / Patriarchal Blessing report pages to fetch one list per unit instead
   of 3 calls per member.
2. **Incremental cache** — cache each member's profile fields by personUuid with a
   freshness window; reuse on repeat runs.
3. **Concurrency** — fetch in parallel (cuts wall-clock, not call count).

**Investigation of option 1 (documented so we don't re-walk it).** The report pages
(`/temple/recommend/recommend-status`, `/ministering?type=EQ|RS`, `/report/patriarchal-blessing`)
are Pages-Router Next.js pages. Their `__NEXT_DATA__` embeds only filter options;
`reportData` is **null** on load — the member rows are fetched by a **runtime API call
that only fires after the user selects a unit** in the page's picker. A plain page load
(captured via `tools/capture_network.py`) shows only auth/infra calls, no report API.
So a clean pure-HTTP replay needs interactive unit-picker automation to discover the
endpoint + params. **Deferred** as future work (the next step is an interactive Playwright
capture: select a unit, capture the resulting `/api|/services` call).

**Decision.** Ship **option 2 (incremental cache)** now as the primary lever; defer
option 1; leave option 3 as a future runtime optimization.

**Why option 2 wins for THIS use case.** The job runs *daily*; covenant-path facts
(baptism, ordinations, recommends) change slowly. With a 7-day freshness window, steady
state re-fetches only ~1/7 of members → **~75% fewer member-level calls** (the 3 profile
actions; `details` still refreshes each run). Bulk reports only help *full* refreshes;
the cache helps *every* day-2+ run, which is the real cost driver across many stakes.

**Pros.** Big call reduction on repeat runs; simple; safe (pure function of uuid);
unit-tested; degrades gracefully (cache miss = normal fetch); `prune()` drops members
who left the stake.
**Cons / drawbacks.** A cached field can be up to `max_age_days` stale (mitigation:
`--cache-max-age-days 0` forces full refresh; window is configurable). The local JSON
cache doesn't persist on ephemeral CI runners — in the cloud, **Supabase `members.updated_at`
plays the same role** (skip members synced within the window); the local cache is the
dev/local equivalent and a drop-in the daily job swaps for the DB check.
**Wins delivered.** `covenant_path/profile_cache.py` + `report.py --no-cache /
--cache-max-age-days`; verified live (cold miss→fetch→put, warm hit = 0 API calls);
throttle delay now only applies on real API calls (cache hits don't sleep).

**Follow-up.** Bulk reports (option 1) tracked for later; concurrency (option 3) optional.

---

## ADR-001 — Backend & access control: Supabase + Postgres RLS (2026-05-26)

**Context.** Goal: scrape any stake by LCR credentials; viewers see data scoped to their
calling — a **stake leader sees the whole stake**, a **ward leader sees only their ward**.

**Decision.** **Supabase (Postgres + Auth + Row-Level Security)** as the system of record;
Google Sheets remains a per-stake convenience export.

**Why.** RLS enforces the stake/ward scoping at the database layer (the only place it's
truly safe) via a `user_roles(stake_id, unit_id NULL=whole-stake)` table. Two separate
auth planes: **scrape auth** = LCR per-stake delegated session (`delegated_login`);
**view auth** = app login (Supabase Auth) + RLS. Roles can be auto-provisioned from LCR's
own leadership directory (we already reverse-engineered it), and re-verified each sync.

**Pros.** DB-enforced fine-grained access; bundled Auth + auto-generated API; Postgres
history; easy cron/edge functions; free tier.
**Cons / drawbacks.** Another dependency + secrets to manage (service_role key, DB URL);
Google Sheets *cannot* enforce ward-vs-stake within one file (sharing is per-file) — so
fine-grained access really requires the DB + an app, with Sheets as coarse export only.
**Status.** Schema + RLS + upsert client being built; applied live once Supabase creds
are in `.env`.
