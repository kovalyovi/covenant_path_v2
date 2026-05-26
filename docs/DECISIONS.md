# Architecture Decision Log

Running log of significant decisions — context, options, the choice, and the
pros/cons/drawbacks/wins — so future work (and future LLM sessions) preserve intent.
Newest first.

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
