# Implementation Notes — file-by-file

Every file in `native/ios/` and what it does. Logic files are pure ports of `apps/viewer/lib/
golden_hour.dart` + `views/dashboard_common.dart` + `views/kpis_view.dart`; Service files port
`broker_client.dart` / `admin_client.dart` / `passkey_client.dart` / `error_reporter.dart`; UI files
mirror the Flutter widgets. See `PARITY_STATUS.md` for the item-by-item parity map.

## Manifest, project & app target

| File | Purpose |
|---|---|
| `project.yml` | **XcodeGen spec** (source of truth — no committed `.xcodeproj`). Defines the iOS app target `CovenantPath` (bundle id `org.membercovenantpath.viewer`, iOS 17): **sources = `Sources/CovenantPathKit/**` + `App/**` compiled directly**; **dependency = remote supabase-swift** (`Supabase` + `Auth` products). Declares the shared `CovenantPath` scheme + the 4 build-config keys (empty defaults). CI: `xcodegen generate` → `xcodebuild`. |
| `Package.swift` | SwiftPM manifest used ONLY by `swift test` (the xcodeproj doesn't reference it): library `CovenantPathKit` over the same `Sources/` + a test target. Declares `supabase-swift` 2.x (`Supabase` + `Auth`). Platforms iOS 17 / macOS 14 (macOS lets the pure-logic tests run without a simulator). |
| `App/CovenantPathApp.swift` | `@main` App — the thin shell rendering `RootView()`. No `import CovenantPathKit` (sources are compiled into this same target's module). |
| `App/Info.plist` | Maps `SUPABASE_URL`/`SUPABASE_ANON_KEY`/`BROKER_URL`/`PASSKEY_RP_ID` from build settings (`$(...)`) into the bundle for `AppConfig`. (When XcodeGen generates the project, `project.yml`'s `info.properties` is authoritative and overwrites this.) |
| `App/Config.xcconfig.example` | Template for the (gitignored) `Config.xcconfig` holding the four build-config values. Documents the xcconfig `//`-escaping gotcha for URLs. |
| `.gitignore` | Ignores `Config.xcconfig`, the generated `*.xcodeproj/`, and SwiftPM/Xcode build artifacts. |

## Models (`Sources/CovenantPathKit/Models/`)

| File | Purpose |
|---|---|
| `Member.swift` | `Codable` struct for a `members` row. `CodingKeys` map the snake_case columns from the dashboard select string to camelCase. Status fields stay `String?` (`"Yes"`/`"No"`/`"N/A"`/sentinels) and are interpreted by the logic exactly like Flutter (`== "Yes"`). Derived helpers: `isInvestigator`, `isMale`, `displayName`. |
| `MemberDetails.swift` | Tolerant `Codable` for the `details` jsonb subtree (Friend, SacramentEntry, Lesson/Principle, Toggle, plus string arrays). Custom decoders accept mixed types (`taughtLevel` as number or string), ministering names as `["A"]` or `[{name}]`, and partial rows — so detail always renders. `Principle.isTaught` mirrors `_taught`. |
| `Stake.swift` | `Codable` for a `stakes` row (`id`, `name`, `unit_number`, `last_synced_at`, `sync_state`, `sync_started_at`, `missionaries` map). Tolerant of int-or-string `unit_number`. `isSyncing` mirrors `_applyCurrentStake`'s running-<30min check. `Missionary` = name/phone/email. |
| `Comment.swift` | `MemberComment` (read: author/body/created_at) + `NewComment` (insert payload) for the `member_comments` notes section. |
| `Misc.swift` | `UnitRow` (invite scope picker), `Invitation` (power-user list), `AppAdmin` (admin console) — the secondary Supabase entities. |

## Logic (`Sources/CovenantPathKit/Logic/`) — pure, `Sendable`, unit-tested

| File | Purpose |
|---|---|
| `DateParsing.swift` | `MemberDate.parse` — ISO `2026-02-06`, `6 Feb 2026`, `M/D/YYYY`/`M/D/YY`, and the sentinels (`N/A`, `needs-profile-api`, `blocked:…`, empty → nil). `yearOf` = first 4-digit run (the by-year rule). Port of `parseMemberDate` / `_dateOf` / `_yearOf`. |
| `Milestones.swift` | The heart: `Milestone` + `Milestones.all` (6 milestones, same order/labels/abbrs/colors). Eligibility predicates `turnsAtLeast`, `memberOneYearPlus`, `ageNow`/`ageNowAtLeast`, `isMale`. Completion math `completion`/`missing`/`averageCompletion` (eligible-only), `applicable(to:)`, `nextStepIndex`. Colors as `UInt32` hex + SF Symbol names. |
| `OrgBucket.swift` | `OrgBucket` (wml/eq/rs) + `Org.responsible(for:)` (`<12mo` WML; `≥12mo` EQ men / RS women, via `days/30.44` floored), `Org.info`, `responsibilityNote`, `responsibleParty`. Plus `Elapsed.monthsDaysAgo` (the month/day-borrow tenure string). Ports of `responsibleOrg`/`orgInfo`/`responsibleParty`/`monthsDaysAgo`. |
| `Recency.swift` | `Recency` (week/month/year/all) with the ≤7/≤31/≤366 day windows + `contains(_:)` (port of `_within`). `Initials.of` (port of `initialsOf`). |
| `Kpis.swift` | The KPI series/bucketing math, ported **exactly** from `dashboard_common.dart` + `kpis_view.dart`: `KpiPeriod` (month=5 weeks / year=12 months / all=month-or-year), `bucketKey`/`windowBuckets`/`metricData` (unique-people-per-bucket + events, current vs prev overlay, `allByYear`), the date extractors `attendedDates`/`firstLessonDate`, `lessonsWithMember`, `membersWithMemberLessons`, `unitCompletion`. Monday-anchored `weekStart` matches Dart's weekday math. |
| `Freshness.swift` | `Freshness.ago`/`exact`/`staleness` (ports of `_ago`/`_staleColor` + `_LastUpdated._exact`) — relative + exact timestamps and the amber/red staleness tiers. |
| `Disclaimer.swift` | The `short`/`long`/`privacy` disclaimer strings (verbatim port of `disclaimer.dart`). |

## Services (`Sources/CovenantPathKit/Services/`)

| File | Purpose |
|---|---|
| `AppConfig.swift` | Reads `SUPABASE_URL`/`SUPABASE_ANON_KEY`/`BROKER_URL`/`PASSKEY_RP_ID` from `Bundle.main.infoDictionary` (defaults empty). `isConfigured`/`hasBroker` gate features. Test-injectable. |
| `SupabaseService.swift` | Lazily builds the `SupabaseClient` from `AppConfig`. `make(config:)` returns nil when unconfigured. |
| `AuthService.swift` | `AuthService` protocol + `SupabaseAuthService`. Email OTP (`signInWithOTP`/`verifyOTP type:.email`), `currentSession`, `currentEmail`, `accessToken()`, `signOut`, `authStateChanges` (tuples); plus broker-login support: `consume(email:otp:)` (verifyOTP) + `setSession(accessToken:refreshToken:)` (relay path). |
| `MembersRepository.swift` | `MembersRepository` + Supabase impl. `members(stakeID:)` selects the exact dashboard columns scoped by `stake_id`, ordered unit→name. `stakes()` selects (incl. `sync_state`/`sync_started_at`/`missionaries`) freshest-first. |
| `SupabaseGateway.swift` | Misc RLS-scoped Supabase ops: `isAdmin` (rpc), member notes (read/insert), units, invitations, `invitePowerUser`/`revokePowerUser` (rpc), `appAdmins`, `revokeAdmin` (rpc). |
| `BrokerService.swift` | Faithful port of `broker_client.dart` + `admin_client.dart` via `URLSession` (Foundation only → stays cross-platform). Cold-start retry; Church login (`password`/`mfa`), email relay, enrollment status, sync-now, schedule, Google Drive, contact, report(+email), feedback, all `/admin/*`, and `/log` telemetry. Authed calls carry the Supabase token via an injected provider. |
| `AppServices.swift` | The configured service graph (Supabase wrappers + gateway + broker, token wired to the live session). `make(config:)` → nil when unconfigured. `passkeyRPID` from the bundle. Injected into views via `@Environment(\.appServices)`. |
| `AppPrefs.swift` | UserDefaults-backed prefs (theme, biometric lock, remembered stake, passkey-upsell flag) + `ThemeController` (`@Observable` system/light/dark with `cycle`, persisted). |
| `BiometricService.swift` | LocalAuthentication app-lock (port of `BiometricLock`): `available`/`enabled`/`setEnabled`/`authenticate`. On-by-default on native; persisted. |
| `PasskeyService.swift` | Native WebAuthn via `ASAuthorization` against the broker `/webauthn/*` (login + register), base64url marshaling. `available` gated behind `PASSKEY_RP_ID` (the documented Partial — needs an associated-domains entitlement). |
| `ErrorReporter.swift` | Global error telemetry → broker `/log` (port of `error_reporter.dart`): `NSSetUncaughtExceptionHandler` + explicit `report(_:where:)`. No PII. |

## ViewModels (`Sources/CovenantPathKit/ViewModels/`) — `@Observable`

| File | Purpose |
|---|---|
| `SessionStore.swift` | Auth state machine (`loading`/`signedOut`/`signedIn`) + the **three login flows** (port of `login_page.dart`): Church (`churchSignIn`/`selectFactor`/`verifyMfa`), Email (`sendCode`/`verify` with `useRelay`), Passkey (`passkeySignIn`). `mode`, MFA + relay state, busy/error/status bookkeeping, `consume` (broker OTP → session). |
| `DashboardStore.swift` | Loads the single-stake dataset + shell state: stakes (freshest), members, `isAdmin`, `enrollStatus`, syncing/`syncStartedAt` (+ optimistic Sync-now), `staleCredential`, `missionariesByUnit`, `selectStake`/`refresh`/`syncNow`. Mirrors `_bootstrap`/`_loadStakes`/`_applyCurrentStake`/`_load`/`_checkAdmin`. |
| `AdminStore.swift` | Loads the Admin/Ops panels independently (summary / diagnostics / actions / enrolled-stakes / admins) + the guarded actions (dispatch / rerun / sync-stake / revoke-stake / invite-admin / revoke-admin). Mirrors `_AdminPageState`. |

## Views (`Sources/CovenantPathKit/Views/`) — SwiftUI, wrapped in `#if canImport(UIKit)`

| File | Purpose |
|---|---|
| `RootView.swift` | Entry point: config check → `AppServices` graph + `ErrorReporter.install` → `SessionStore.phase` switch (loading / `LoginView` / biometric-gated `DashboardView`); applies the persisted theme. Injects `session`/`theme`/`services` into the environment. `ConfigErrorView` for missing config. |
| `LoginView.swift` | The 3-mode login (port of `login_page.dart`): Church/Email segmented; Church 3-step (user/pass → factor pick → code); Email send/verify + relay fallback; passkey button (or disabled-with-note); disclaimer + footer + status/error lines. |
| `BiometricGateView.swift` | Wraps the dashboard; Face ID gate when the lock is on + available (port of `BiometricGate`), fail-open on availability. |
| `DashboardView.swift` | The 5-tab `TabView`; per-tab `NavigationStack` + member-detail destination; toolbar (stake switcher · freshness chip→Sync-now alert · Refresh · overflow menu); `SyncingBanner`/`StaleBanner`; skeleton + `EmptyStateView`; the sheet router (sync/report/invite/admin/settings); a one-time passkey-upsell toast. |
| `PersonDetailView.swift` | Detail page: header card, milestone chips, rich `details` body or flat fallback, LCR link, `RecordedYesNote`, and `CommentsSection` (read/add notes via `member_comments`). |
| `Detail/DetailSections.swift` | The detail sub-sections: Sacrament dots (+View all), Friends, ListText (priesthood/calling/ministering), Names (ministers), Temple, Principles (+member-present dots), Toggles (self-reliance), Flags. |
| `Tabs/BaptismsView.swift` | Prospective-baptism timeline: combined ↔ per-unit toggle; overdue then Scheduled date rail; per-unit cards show `MissionaryStrip` (name chips → tap reveals phone/email). `SectionHeader`, `EmptyHint` live here. |
| `Tabs/GoldenHourView.swift` | New Members / Being Taught segmented; org filter; recency window + range pill; `CompletionCard` (% per milestone, tap → `MilestoneDrillSheet`); member list. `MemberList`/`RangePill` shared helpers. |
| `Tabs/NeedsView.swift` | Category selector (`CategoryChip`) + counts, org filter, per-unit `UnitCountChip` breakdown, eligible-missing list sorted by baptism date then unit. `BigHeader` lives here. |
| `Tabs/KPIsView.swift` | **Full KPIs** (port of `kpis_view.dart`): Swift Charts line cards (`MetricChartCard`) with current-vs-previous overlay + delta badges, Month/Year/All + range pill + Compare, Overview stat grid, Golden-Hour-by-unit ranked bars, and the drill sheets (`KpiDrillSheet`/`GoldenHourBreakdownSheet`/`LessonsDrillSheet`). |
| `Tabs/TableView.swift` | Horizontally-scrolling grid of every covenant-path field, color-coded; 3-state per-column sort; per-column value-picker filter (`ColumnFilterSheet`); "N members (filtered)" + clear-filters; row → detail. |
| `SettingsView.swift` | Grouped Settings (port of `settings_page.dart`): Appearance (theme cycle), Security (Add passkey + App-lock), Support (Contact/Feedback as nested sheets), About & privacy, Account (email + Sign out). |
| `InviteView.swift` | Power users (port of `invite_page.dart`): list (grouped by email) + invite (rpc, optional unit scope) + revoke (rpc). |
| `AdminView.swift` | Admin · Ops console (port of `admin_page.dart`): independent panels — health, freshness, maintenance dispatch, tools/links, diagnostics, enrolled stakes (sync/revoke), GitHub runs (+rerun) + changelog, admins (invite/revoke). |
| `Sheets/SyncSettingsSheet.swift` | Sync settings (port of `_SyncSettingsSheet`): status + Sync-now + Revoke + `ScheduleSection` (ET hour + pause) + `GoogleDriveSection` (connect/disconnect, sheet link, reconnect). `InfoRow` label/value row. |
| `Sheets/ReportSheet.swift` | Generate report (port of `_ReportSheet`): totals + most-needed steps + outstanding-by-member; Email-to-me. |
| `Sheets/SupportSheets.swift` | `ContactSupportSheet` (`/contact`) + `FeedbackSheet` (`/feedback` → issue). |
| `Shared/Theme.swift` | `Color(hex:)`, `StatusColor`, `DashboardTab` (per-tab accent + symbol), `SectionCard`, `CountBadge`, `AppColors`, `StatusTag`/`StatusPill`, and the `Freshness.Staleness` → color mapping. |
| `Shared/GoldenHourChips.swift` | The milestone chip row (compact circles or labeled pills; next-step highlight). Port of `GoldenHourChips`. |
| `Shared/OrgFilterBar.swift` | The WML/EQ/RS multi-select filter (all-on, can't deselect last, Clear filters) + `SubtleNote`. The `toggle(_:in:)` guard is unit-tested. |
| `Shared/MemberRow.swift` | List row: avatar + name (+age), date line, responsible-org chip, optional milestone chips, unit metadata. Port of `_MemberRow`. |
| `Shared/Avatars.swift` | `InitialsAvatar` + `PhotoAvatar` (AsyncImage with initials fallback). |
| `Shared/FlowLayout.swift` | A wrapping `Layout` (Flutter `Wrap` equivalent) used by chip rows. |
| `Shared/SkeletonView.swift` | `MemberListSkeleton` + `SyncSettingsSkeleton` + `CardSkeleton` + a shimmer modifier for the loading states. |

## Tests (`Tests/CovenantPathKitTests/`)

| File | Purpose |
|---|---|
| `LogicTests.swift` | Date parsing, eligibility (turns-≥N, member-≥1yr, Melchizedek gate), eligible-only completion, org buckets + the 12-month boundary, the org-filter last-selection guard (`Org.toggleFilter`), recency windows, initials, `monthsDaysAgo`. |
| `DecodingTests.swift` | Member snake_case mapping, tolerant `details` decode (numeric `taughtLevel`, string vs object ministering names, partial subtree), Stake + missionaries, investigator kind. |
| `KpisTests.swift` | KPI math: `attendedDates`/`firstLessonDate` extractors, `lessonsWithMember`, month=5-week / year=12-month bucketing, unique-people-per-bucket, empty `all`, `unitCompletion` ranking, and `Freshness.ago`/`staleness`. |
