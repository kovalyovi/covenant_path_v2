# Covenant Path — Native App Spec (shared context for the iOS + Android PoCs)

This is the single shared brief for two **proof-of-concept** native rebuilds of the existing Flutter
viewer (`apps/viewer`). Goal: compare Flutter vs. native architecture/feel. Build the CORE, idiomatic
and clean — not 100% parity. Two independent apps:
- **iOS**: Swift + SwiftUI (latest: `@Observable`/Observation, `async/await`, `NavigationStack`,
  Swift Package Manager), Supabase via **supabase-swift**.
- **Android**: Kotlin + Jetpack Compose (Material 3, ViewModel + StateFlow, coroutines/Flow),
  Supabase via **supabase-kt** (`gotrue-kt` + `postgrest-kt`).

## What the app is

A read-only dashboard for Latter-day Saint stake/ward leaders tracking how recent converts ("new
members") and people being taught ("investigators") are progressing through first-year integration
milestones ("Golden Hour"). Data is scraped from the church system into **Supabase (Postgres + RLS)**
by a Python backend; the app only ever **reads Supabase**, scoped by the signed-in user's role. The
app NEVER talks to the church system directly.

## Backend / data contract (the only thing the app reads)

Supabase project — **URL + anon key are injected at build time** (do NOT hardcode/commit secrets;
read from a config/xcconfig/BuildConfig field, defaulting empty). The anon key is safe on clients;
**Row-Level Security** does all access gating, so the app does NO filtering of its own — it just
`select`s and shows what comes back.

Auth: **Supabase Auth, email OTP** (passwordless). Flow: user enters email → `signInWithOtp(email)`
→ Supabase emails a 6-digit code → `verifyOtp(email, token, type=email)` → you hold a session. RLS
then scopes every query by the verified email. (There is also a "Church account" login via a backend
broker, and passkeys — OUT OF SCOPE for the PoC; implement email-OTP only.)

### Tables (read-only; RLS returns only rows the user may see)

`members` — one row per tracked person. Key columns the UI uses:
- `person_uuid` (text, id), `stake_id` (uuid), `unit_id` (uuid), `name` (text), `unit_name` (text)
- `kind` (text): `'new_member'` | `'investigator'` | `'returning'`
- `baptism_date` (text, e.g. "2026-02-06" or "needs-profile-api"/"blocked: ..." sentinels = treat as null)
- `baptism_goal_date` (text; planned baptism for investigators)
- `birth_date` (text), `membership_duration` (text, e.g. "Member for 8 months"), `sex` ('M'/'F')
- Yes/No status fields: `friends`, `aaronic_priesthood`, `melchizedek_priesthood`, `calling`,
  `ministering_brothers_sisters`, `ministering_assignment`, `temple_recommend`
  (Active/Expired/No), `patriarchal_blessing`, `living_ordinance`. Values: `"Yes"`/`"No"`/`"N/A"`,
  or a sentinel string (`"needs-profile-api"`, `"blocked: insufficient calling access"`) = unknown.
- `details` (jsonb) — rich subtree for the person detail page: `friends` [{name,unit,inStake}],
  `ministeringBrothers`/`ministeringSisters` [{name}], `sacrament` [{label,attended,date}],
  `lessons` [{name,principles:[{name,memberPresent,taughtLevel}]}], `callings` [str],
  `priesthoodOrdinations` [str], `templeOrdinances` [str], `tags` [str], etc. (May be partial.)
- `photo_url` (text, signed URL, may be null)

`stakes` — `id`, `name`, `unit_number`, `last_synced_at`, `missionaries` (jsonb: unit→[{name,phone,email}]).
`units` — `id`, `stake_id`, `name`, `unit_type`. `user_roles` — drives RLS; app doesn't query directly.

Select string the Flutter app uses for the dashboard (mirror it):
`person_uuid, stake_id, unit_id, name, unit_name, baptism_date, birth_date, membership_duration,
sex, friends, aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters,
ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance, details, photo_url,
kind, baptism_goal_date`. Order by `unit_name`, then `name`. Scope to one stake: `.eq('stake_id', currentStakeId)`.

## Screens (the 5 tabs + detail) — build at least Baptisms, Golden Hour, Table, and Person Detail

Bottom nav / tab bar, 5 tabs (each a distinct accent color):
1. **Baptisms** (blue) — investigators with a planned `baptism_goal_date`, as a date timeline:
   overdue ("date passed") block first, then a "Scheduled" block, grouped by date.
2. **Golden Hour** (gold) — two sub-sections (segmented control): **New Members** (baptized) and
   **Being Taught** (investigators). New Members shows a "Golden Hour completion" summary (% per
   milestone) + the member list with milestone chips; has the org-ownership filter (below) and a
   Week/Month/Year/All recency window.
3. **Needs** (deep orange) — for each milestone, the eligible members still missing it; a category
   selector + per-unit breakdown; same org filter.
4. **KPIs** (green) — stake metrics as simple charts (Month/Year/All). Lowest priority for the PoC.
5. **Table** (purple) — every field in a sortable/filterable grid, color-coded Yes(green)/No(red)/
   N/A(grey). Full-page scroll.

**Person detail** — header (photo/initials, name, unit, baptism line), the Golden Hour milestone
chips, then sections from `details`: sacrament attendance dots, Friends in the Church (names),
Priesthood, Calling, Ministering assignment, Ministering Brothers/Sisters (names), Temple, Principles
Taught, Flags. When a Yes flag has no names in `details`, show "names temporarily unavailable".

**Login** — email field → "Send code" → 6-digit code field → verify. That's it for the PoC.

## Business logic to port exactly (it's the heart of the app)

**Golden Hour milestones** (each gated to who it applies to; completion % is eligible-only):
- Friends — `friends == "Yes"` — everyone. color pink.
- Calling — `calling == "Yes"` — eligible if turns ≥12 this year. purple.
- Has ministers — `ministering_brothers_sisters == "Yes"` — everyone. cyan.
- Ministering assignment — `ministering_assignment == "Yes"` — eligible if turns ≥14. orange.
- Aaronic Priesthood — `aaronic_priesthood == "Yes"` — eligible if male && turns ≥12. blue.
- Melchizedek Priesthood — `melchizedek_priesthood == "Yes"` — eligible if male && age-now ≥18 &&
  member ≥1 year. green.
("turns N this year" = birth year → current year − birthYear ≥ N. "member ≥1yr" = baptism_date ≥365d
ago, or membership_duration says ≥1 year. Unknown birth → not eligible for age-gated ones.)

**Org ownership** (the convert-responsibility hand-off, used by the filter): based on months since
baptism — `< 12 months` → **Missionaries/WML** (teal); `≥ 12 months` → **Elders Quorum** (blue, men)
/ **Relief Society** (rose, women). No baptism date → unassigned.

**Org filter** (Golden Hour + Needs): three colored toggle chips WML/EQ/RS, ALL selected by default;
tap toggles each (multi-select, can't deselect the last); a "Clear filters" affordance restores all.
Each org has a stable color (teal/blue/rose) + icon used consistently.

Date parsing must handle: ISO `2026-02-06`, `6 Feb 2026`, `2/6/2026`, and the sentinel strings
(`N/A`, `needs-profile-api`, `blocked: ...` → null).

## PoC scope / non-goals

DO build: email-OTP login, the Supabase data layer (typed model + repository), Baptisms, Golden Hour
(with milestones + org filter), Table, Person Detail, the milestone/org/date logic. Single-stake
(use the first/only stake the user can see).
SKIP for the PoC: the Church-account broker login, passkeys, KPIs charts (a stub tab is fine),
admin/ops console, report generation, Google Drive, push, in-app schedule, comments/notes, photos
pipeline (just show photo_url if present, else initials).

## Deliverables per app

- A buildable project (SPM for iOS; Gradle/Compose for Android) under your assigned directory.
- Clean architecture: model layer, a Supabase repository, view-models/observable state, SwiftUI/
  Compose views. Idiomatic for the platform — show off best practices.
- A `README.md` with: how to build/run (incl. the `SUPABASE_URL`/`SUPABASE_ANON_KEY` build config),
  what's implemented, what's stubbed, and any compile caveats (you can't assume a compiler here).
- Do NOT hardcode any secret. Do NOT run git. Stay entirely within your assigned directory.

Reference implementation to mirror behavior: the Flutter app in `apps/viewer/lib/` — especially
`golden_hour.dart` (milestones, OrgBucket/orgInfo/responsibleOrg, date parsing), `dashboard_page.dart`
(_columns, tabs), `views/*.dart` (each tab), `person_detail_page.dart`, `broker_client.dart` +
`config.dart` (auth/config). Read them for exact logic; translate, don't transliterate.
