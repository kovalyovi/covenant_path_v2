# Implementation Notes — file-by-file

Every file in `native/ios/` and what it does. Logic files are pure ports of `apps/viewer/lib/
golden_hour.dart` (and the dashboard view files); UI files mirror the Flutter widgets.

## Manifest & app target

| File | Purpose |
|---|---|
| `Package.swift` | SwiftPM manifest. One library `CovenantPathKit` (the whole app) + a test target. Declares the `supabase-swift` 2.x dependency. Platforms iOS 17 / macOS 14 (macOS lets the pure-logic tests run without a simulator). |
| `App/CovenantPathApp.swift` | `@main` App for the iOS target — a thin shell that renders `RootView()` from the package. |
| `App/Info.plist` | App Info.plist; maps `SUPABASE_URL` / `SUPABASE_ANON_KEY` from the xcconfig (`$(...)`) into the bundle for `AppConfig` to read. |
| `App/Config.xcconfig.example` | Template for the (gitignored) `Config.xcconfig` holding the Supabase URL + anon key. Documents the xcconfig `//`-escaping gotcha for the URL. |
| `.gitignore` | Ignores `Config.xcconfig` and SwiftPM/Xcode build artifacts. |

## Models (`Sources/CovenantPathKit/Models/`)

| File | Purpose |
|---|---|
| `Member.swift` | `Codable` struct for a `members` row. `CodingKeys` map the snake_case columns from the dashboard select string to camelCase. Status fields stay `String?` (`"Yes"`/`"No"`/`"N/A"`/sentinels) and are interpreted by the logic exactly like Flutter (`== "Yes"`). Derived helpers: `isInvestigator`, `isMale`, `displayName`. |
| `MemberDetails.swift` | Tolerant `Codable` for the `details` jsonb subtree (Friend, SacramentEntry, Lesson/Principle, Toggle, plus string arrays). Custom decoders accept mixed types (`taughtLevel` as number or string), ministering names as `["A"]` or `[{name}]`, and partial rows — so detail always renders. `Principle.isTaught` mirrors `_taught`. |
| `Stake.swift` | `Codable` for a `stakes` row (`id`, `name`, `unit_number`, `last_synced_at`, `missionaries` map). Tolerant of int-or-string `unit_number` and a null/odd `missionaries`. `Missionary` = name/phone/email. |

## Logic (`Sources/CovenantPathKit/Logic/`) — pure, `Sendable`, unit-tested

| File | Purpose |
|---|---|
| `DateParsing.swift` | `MemberDate.parse` — ISO `2026-02-06`, `6 Feb 2026`, `M/D/YYYY`/`M/D/YY`, and the sentinels (`N/A`, `needs-profile-api`, `blocked:…`, empty → nil). `yearOf` = first 4-digit run (the by-year rule). Port of `parseMemberDate` / `_dateOf` / `_yearOf`. |
| `Milestones.swift` | The heart: `Milestone` + `Milestones.all` (6 milestones, same order/labels/abbrs/colors). Eligibility predicates `turnsAtLeast`, `memberOneYearPlus`, `ageNow`/`ageNowAtLeast`, `isMale`. Completion math `completion`/`missing`/`averageCompletion` (eligible-only), `applicable(to:)`, `nextStepIndex`. Colors as `UInt32` hex + SF Symbol names. |
| `OrgBucket.swift` | `OrgBucket` (wml/eq/rs) + `Org.responsible(for:)` (`<12mo` WML; `≥12mo` EQ men / RS women, via `days/30.44` floored), `Org.info`, `responsibilityNote`, `responsibleParty`. Plus `Elapsed.monthsDaysAgo` (the month/day-borrow tenure string). Ports of `responsibleOrg`/`orgInfo`/`responsibleParty`/`monthsDaysAgo`. |
| `Recency.swift` | `Recency` (week/month/year/all) with the ≤7/≤31/≤366 day windows + `contains(_:)` (port of `_within`). `Initials.of` (port of `initialsOf`). |

## Services (`Sources/CovenantPathKit/Services/`)

| File | Purpose |
|---|---|
| `AppConfig.swift` | Reads `SUPABASE_URL`/`SUPABASE_ANON_KEY` from `Bundle.main.infoDictionary` (defaults empty). `isConfigured` gates the app. Test-injectable. |
| `SupabaseService.swift` | Lazily builds the `SupabaseClient` from `AppConfig`. `make(config:)` returns nil when unconfigured. |
| `AuthService.swift` | `AuthService` protocol + `SupabaseAuthService` — email OTP (`signInWithOTP`/`verifyOTP type:.email`), `currentSession`, `signOut`, and an `authStateChanges` AsyncStream re-exposed as `(event, session)` tuples. |
| `MembersRepository.swift` | `MembersRepository` protocol + Supabase impl. `members(stakeID:)` selects the exact dashboard columns scoped by `stake_id`, ordered by unit then name. `stakes()` returns RLS-visible stakes freshest-first. |

## ViewModels (`Sources/CovenantPathKit/ViewModels/`) — `@Observable`

| File | Purpose |
|---|---|
| `SessionStore.swift` | Auth state machine (`loading`/`signedOut`/`signedIn`). Listens to `authStateChanges`; `sendCode`/`verify`/`signOut` with busy+error bookkeeping (mirrors `login_page._run`). `codeSent` drives the two-step UI. |
| `DashboardStore.swift` | Loads the single-stake dataset (stakes → pick freshest → members). Exposes `members`, derived `newMembers`/`investigators`, `missionariesByUnit`, the current stake metadata, `selectStake`, `refresh`. Mirrors `_bootstrap`/`_loadStakes`/`_load`. |

## Views (`Sources/CovenantPathKit/Views/`) — SwiftUI, wrapped in `#if canImport(UIKit)`

| File | Purpose |
|---|---|
| `RootView.swift` | Entry point: config check → service graph → `SessionStore.phase` switch (loading / `LoginView` / `DashboardView`). `ConfigErrorView` for missing config. |
| `LoginView.swift` | Email-OTP two-step screen (email → code), focus + busy handling. |
| `DashboardView.swift` | The 5-tab `TabView`, each tab a `NavigationStack` with the member-detail destination, a shared toolbar (stake switcher · freshness · sign out), and loading/empty/error states. `FreshnessFormatter` = "Updated 2h ago". |
| `PersonDetailView.swift` | The detail page: header card, labeled milestone chips, rich `details` body or flat fallback, LCR link. `RecordedYesNote` = the "names temporarily unavailable" fallback. |
| `Detail/DetailSections.swift` | The detail sub-sections: Sacrament dots (+View all), Friends, ListText (priesthood/calling/ministering), Names (ministers), Temple, Principles (+member-present dots), Toggles (self-reliance), Flags. |
| `Tabs/BaptismsView.swift` | Prospective-baptism date timeline: overdue then Scheduled, grouped by date with a month/day rail. `SectionHeader`, `EmptyHint` live here. |
| `Tabs/GoldenHourView.swift` | New Members / Being Taught segmented; org filter; recency window + range pill; `CompletionCard` (% per milestone, tap → `MilestoneDrillSheet`); member list. `MemberList` shared list helper. |
| `Tabs/NeedsView.swift` | Category selector (`CategoryChip`) + counts, org filter, per-unit `UnitCountChip` breakdown, eligible-missing list sorted by baptism date then unit. `BigHeader` lives here. |
| `Tabs/KPIsView.swift` | Stub: at-a-glance counts + per-unit completion bars; charts intentionally omitted (labeled). |
| `Tabs/TableView.swift` | Sortable list of baptized members with color-coded Yes/No/N-A/recommend cells + a sort menu (mirrors the sheet columns + cell colors). |
| `Shared/Theme.swift` | `Color(hex:)`, `StatusColor`, `DashboardTab` (per-tab accent + symbol), `SectionCard`, `CountBadge`. |
| `Shared/GoldenHourChips.swift` | The milestone chip row (compact circles or labeled pills; next-step highlight). Port of `GoldenHourChips`. |
| `Shared/OrgFilterBar.swift` | The WML/EQ/RS multi-select filter (all-on, can't deselect last, Clear filters) + `SubtleNote`. The `toggle(_:in:)` guard is unit-tested. |
| `Shared/MemberRow.swift` | List row: avatar + name (+age), date line, responsible-org chip, optional milestone chips, unit metadata. Port of `_MemberRow`. |
| `Shared/Avatars.swift` | `InitialsAvatar` + `PhotoAvatar` (AsyncImage with initials fallback). |
| `Shared/FlowLayout.swift` | A wrapping `Layout` (Flutter `Wrap` equivalent) used by chip rows. |
| `Shared/SkeletonView.swift` | `MemberListSkeleton` + a shimmer modifier for the loading state. |

## Tests (`Tests/CovenantPathKitTests/`)

| File | Purpose |
|---|---|
| `LogicTests.swift` | Date parsing, eligibility (turns-≥N, member-≥1yr, Melchizedek gate), eligible-only completion, org buckets + the 12-month boundary, the org-filter last-selection guard, recency windows, initials, `monthsDaysAgo`. |
| `DecodingTests.swift` | Member snake_case mapping, tolerant `details` decode (numeric `taughtLevel`, string vs object ministering names, partial subtree), Stake + missionaries, investigator kind. |
