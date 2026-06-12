# Local-first / on-demand architecture — PROPOSAL (for discussion, not built)

> **STATUS: PARKED for later (2026-06-11).** Documented thoroughly; not started. Pick back up from
> the "Questions for you" section — the one piece that needs a decision before any building is the
> **email-digest data source** (see "The email-digest problem" below). Nothing here is implemented;
> the current Supabase + daily-sync + Member-Tools pipeline remains live and unchanged.

**Your idea:** stop storing stake data in Supabase + running daily jobs. Instead, fetch each user's
stake data **live when they log in**, cache it **on the client** (browser + native), merge on the
client, show a pending indicator while refreshing — and make the repo private again.

**Verdict: yes, this is a strong direction** — it's now *possible* because the Member Tools bulk API
returns the whole stake in one fast call. It eliminates the fragile daily cron, the delegated-credential
machinery, and most of Supabase. Below is how it'd work, the real gotchas, and what it costs.

---

## How fast is the fetch? (you asked)
Measured live against your stake:
- **`/api/v5/sync` (the bulk call): ~3–5 s** (~7 MB) — and it carries **12 of 13 fields** (lessons,
  baptism, attendance, friends, temple recommend, ministering, callings…). Only `patriarchal_blessing`
  is missing from it.
- **The `/mlt` profile merge** (for `patriarchal_blessing`): ~76 calls ≈ **20–30 s**. This is the slow part.

**Design implication:** an on-demand login should serve the **~5 s bulk data immediately** and enrich the
one missing field (`patriarchal_blessing`) **lazily in the background** (or drop it). So: **first login
~5 s with a pending indicator; every later visit is instant from cache + a background refresh.**

---

## The architecture
```
User logs in (Church account, via the broker's Okta flow)
        │
        ▼
Broker mints THE USER'S OWN Member Tools token  ──►  POST /api/v5/sync  (~5s)
        │                                              (the user only ever gets data their
        ▼                                               own Church access allows — access
Broker adapts → returns stake JSON to the client        control is the Church's, no RLS)
        │
        ▼
Client caches it locally (IndexedDB) + Redux store; shows it INSTANTLY next time,
refreshes on each login with a "Updating… (as of <time>)" pending indicator.
Shared NOTES come from a tiny Supabase table; everything else is local.
```

### Why the broker still has to be in the loop
The browser **cannot call `membertools-api` or LCR directly** — CORS blocks it (these are the mobile
app's APIs, no cross-origin headers for our web origin). So the **broker proxies** the fetch (it already
does the Okta login + token mint). *Native* apps **can** call directly (no CORS) — so native could skip
the proxy, but using the broker for both keeps one code path.

### 🎉 The delegated-credential problem DISAPPEARS
This is the big payoff and it answers the token question: with on-demand, **each user logs in with their
own Church account and fetches their own stake** — so there are **no stored credentials, no daily cron,
no enrollment, no 45-day token wall to manage**. The whole `stake_credentials` / `token_store` /
delegated-renewal machinery goes away. (This is why I paused the delegated-DB-token work — *this* makes
it moot.)

---

## What we KEEP, SHRINK, and DROP

| Today | Under local-first |
|---|---|
| Supabase `members`/`units`/`stakes` (stake data) | **DROP** — data lives on the client |
| RLS access control | **DROP** — the Church's own access is the gate (you get what your login sees) |
| Daily GitHub-Actions sync cron | **DROP** — data is fetched on login |
| `stake_credentials` + delegated enrollment + token store | **DROP** — each user uses their own login |
| Supabase `member_comments` (shared notes) | **KEEP (tiny)** — notes are shared among a stake's leaders, so they need a server |
| `app_admins` + ops console | **KEEP (tiny)** — admin still needs a server |
| Daily **email digests** (mailer) | **DROP** unless we keep a small residual cron just for digests |
| Daily **Google Sheets** mirror | **DROP** unless kept on a residual cron |
| Broker (Render) | **KEEP** — becomes a thin live data proxy (mint + fetch + relay) |

**Net:** Supabase shrinks to ~2 small tables (shared notes + admins). The fragile daily pipeline,
delegated credentials, and RLS all go away.

### Can the repo go private again? — **Yes**
The repo went public for **free CI minutes for the daily cron**. Kill the cron → that reason's gone.
Test runs on push fit in a private repo's free Actions budget (2,000 min/month). Going private is also
**more secure** (relevant given the recent security audit). ✅

---

## What it COSTS (the honest tradeoffs)
1. **Freshness = last login.** No overnight refresh — data is as fresh as the user's last sign-in. You
   said that's fine ("updated when new login happens"). We can add a manual **"Refresh now"** button.
2. **Lose daily email digests + Sheets mirror** (they ride the cron) — unless we keep a tiny residual
   cron just for those. *Decision needed.*
3. **Notes stay server-side** (so leaders share them) — a small Supabase remains. (Or go per-user-local
   and lose cross-leader sharing.)
4. **~5 s first-load + ~7 MB transfer per refresh** — fine with caching + a pending indicator; native
   handles the 7 MB easily, web caches it in IndexedDB.
5. **The broker does a live ~5 s fetch per login** (per user) — Render free-tier cold-start applies (our
   warm-gate already mitigates it). At your scale (handful of users) this is trivial.

---

## ⭐ The email-digest problem (the open question — thinking it through)
You still want a **daily email that checks the items** (Golden-Hour milestones, people approaching a
baptism date, lapsed attendance, etc.). But local-first creates a real tension: **a daily cron needs
data to read, and local-first keeps the data only on clients.** A cron has no logged-in user and (by
design) no stored Church credential to fetch with. So where does the digest's data come from? Three
honest options:

### Option A — Thin snapshot pushed by the client (RECOMMENDED)
When a user logs in and fetches fresh data, the client also **pushes a small "digest slice" to the
server** — *only* the milestone-relevant fields (name, unit, baptism date/goal, last-attendance,
the Golden-Hour flags), not the whole 7 MB stake, not notes. A daily cron then **reads those stored
slices and emails "here's what needs attention"** — purely from the snapshot, **with no Church access
at all.**
- ✅ **No stored Church credential** — keeps the credential machinery dead.
- ✅ Server stores only a tiny milestone slice (one small table), not the stake.
- ✅ Consistent with the whole model: the digest reflects the **last login's** data
  ("freshness = last login"). For a *standing-alert* digest ("these 5 people are within 2 weeks of
  their baptism date") that's fine — it's a reminder, not a change-feed.
- ⚠️ If nobody logs in for days, the digest reflects stale-ish data (acceptable, and we can note
  "as of <date>" in the email).
- ⚠️ It's a "what's pending now" digest, not a true "what changed since yesterday" diff (a diff
  needs a daily *fetch*, which needs a credential — see B).

### Option B — Opt-in "digest token" + residual cron (for truly-fresh daily digests)
A stake that wants a **genuinely daily, freshly-fetched** digest **opts in** by authorizing a stored
Member Tools token *specifically for notifications*. A small residual cron fetches just that stake
each morning, diffs, and emails.
- ✅ True daily freshness + real day-over-day diffs.
- ❌ Re-introduces a stored token (and the 45-day re-auth wall) — **but only for stakes that opt into
  always-on digests**, and scoped to one feature. The **operator stake already auto-mints in CI**, so
  the operator gets fresh digests for free; delegated stakes opt in if they want them.
- This cleanly **decouples** the two concerns: *viewing* is always credential-free on-demand;
  *notifications* are an opt-in that inherently needs a server that can act while you're away.

### Option C — Send at login (no cron)
Compute "what needs attention" client-side right after the on-login fetch and have the broker send the
email then.
- ✅ Simplest; no cron, no stored slice.
- ❌ Fires only when someone logs in (not "daily"), and needs **dedup** so two leaders logging in the
  same day don't both trigger it. Weakest fit for "a daily email."

**My recommendation: Option A as the default** (no credentials, fits local-first, one tiny table),
**with Option B available as opt-in** for any stake that specifically wants fresh daily diffs. That
gives you the daily email without resurrecting the credential problem for everyone — only those who
opt into always-on freshness take that on. **This is the piece to decide before building.**

---

## Migration plan (phased — full wipe is fine, as you said)
1. **Broker:** new `GET /stake` endpoint — mint the user's Member Tools token (from their login),
   `fetch_sync` → adapt (reuse `build_membertools_report`) → return JSON. Lazy `/mlt` enrich for
   patriarchal.
2. **Web:** on login call `/stake`; cache to **IndexedDB**; Redux store; instant-from-cache + a
   "Updating…" pending banner; merge shared notes from the tiny Supabase.
3. **Native (iOS/Android):** fetch on login (directly or via broker), cache in the existing local repo.
4. **Decommission:** drop the daily cron, the Supabase stake tables, `stake_credentials`, the token
   store, RLS. Keep `member_comments` + `app_admins`. **Full wipe.**
5. **Repo → private.**
6. Build the **new views** (Lessons, KPI tiles, attendance, commitments, missionaries tab) against the
   local cache — same `details` shape, so they're presentation-only.

---

## My recommendation
**Do it** — but in this order, because it changes where the views read from:
1. **First, the broker `/stake` endpoint + web local-cache + pending indicator** (prove the on-demand
   loop end-to-end on web).
2. **Then decommission** the cron/Supabase-stake/credentials + go private.
3. **Then build all the new views** (incl. the missionaries tab) against the local cache — once, not
   twice.

Building the views *now* against Supabase and *again* after the pivot would be double work — so I'd
settle the architecture first, then build the views on the new model.

## Questions for you (decide before building)
1. **Email digest data source** — Option A (thin client-pushed snapshot + cron, no credentials,
   *my rec*), Option B (opt-in stored digest token for fresh daily diffs), or C (send-at-login)? See
   "The email-digest problem" above. **This is the gating decision.**
2. **Google Sheets mirror** — keep (needs a residual cron, same question as digests) or drop?
3. **Notes** — keep shared (tiny Supabase) or make them per-user-local (no sharing)?
4. **Native** — fetch Member Tools **directly** (no CORS, simplest) or **via the broker** (one code path)?
5. **Refresh** — login-only, or also a manual "Refresh now" button + maybe a foreground auto-refresh if
   the cache is older than N hours?
6. **Views timing** — build them *after* the pivot (my rec, build once), or build now on Supabase and
   port later?
