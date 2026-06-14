# Implementation Notes — files & purpose

Root package: `org.membercovenantpath.viewer`. One module: `:app`. Feature parity with the web client
(see `PARITY_STATUS.md`). The `.dart` filenames below are the **original Flutter sources** this app was
ported from; that Flutter app (`apps/viewer`) was **deleted 2026-06-13** — the live equivalents now
live in the React web app (`apps/web/src/`: logic in `src/logic/`, clients in `src/lib/`, screens in
`src/pages/`).

## Gradle / config
| File | Purpose |
|---|---|
| `settings.gradle.kts` | Module + repos (google + mavenCentral). |
| `build.gradle.kts` (root) | Plugins `apply false`. |
| `app/build.gradle.kts` | Android + Compose + serialization; `SUPABASE_URL`/`SUPABASE_ANON_KEY`/`BROKER_URL` → `BuildConfig`; biometric/credentials/datastore/fragment/material deps. |
| `gradle/libs.versions.toml` | Version catalog (Kotlin 2.1, Compose BOM, supabase-kt 3.1.1 BOM, Ktor 3, nav, Coil, biometric, credentials, datastore, fragment, material). |
| `gradle.properties` | AndroidX/Compose flags; empty `SUPABASE_*`/`BROKER_URL` placeholders; configuration-cache off for CI. |
| `app/proguard-rules.pro` | Keep kotlinx-serialization serializers for `model/`. |
| `app/src/main/AndroidManifest.xml` | INTERNET + USE_BIOMETRIC; `<queries>` for external links/tel/mailto; single `MainActivity`. |

## logic/ — pure Kotlin (unit-tested)
| File | Purpose |
|---|---|
| `DateParse.kt` | Member-date parsing + tenure math (ported from `dashboard_common`/`golden_hour`). |
| `Milestones.kt` | The 6 Golden-Hour milestones + eligibility/completion + `avgCompletion`. |
| `OrgBucket.kt` | Org ownership (WML/EQ/RS) info, colors, `responsibleOrg`/`responsibilityNote`. |
| `Kpis.kt` | **KPI series/bucketing math ported 1:1** from `dashboard_common.dart`/`kpis_view.dart` (`metricData`, `bucketKey`, `windowBuckets`, ALL granularity switch, `attendedDates`/`firstLessonDate`, `lessonsWithMember`, `unitCompletion`, `membersWithMemberLessons`, period range/compare labels). |
| `Freshness.kt` | `ago`/`staleColor`/`exactLocal` (ported from `dashboard_common`). |

## model/ — kotlinx-serializable
| File | Purpose |
|---|---|
| `Member.kt` | A `members` row (the Flutter `_columns`); `status(field)`. |
| `Stake.kt` | `Stake` (+ sync_state/started) + `Missionary`. |
| `Details.kt` / `DetailsParse.kt` | Typed `members.details` subtree + lenient decode (Supabase-free Json so logic stays testable). |
| `Comment.kt` | `member_comments` read + insert shapes. |
| `Invitation.kt` | `Invitation`, `Unit`, `AppAdmin` (power-user + admin views). |

## data/ — repositories + clients
| File | Purpose |
|---|---|
| `AppConfig.kt` | BuildConfig accessors (`supabaseConfigured`, `brokerAvailable`, urls). |
| `SupabaseClientProvider.kt` | Single `SupabaseClient` (Auth + Postgrest, lenient kotlinx serializer). |
| `AuthRepository.kt` | Email-OTP + broker-OTP adoption (`verifyBrokerOtp`, `adoptRefreshToken`), `sessionStatus`, `accessToken`, `signOut`. |
| `MembersRepository.kt` | `loadStakes`/`loadMembers(stakeId)`/`missionariesByUnit`, `isAdmin` (rpc). |
| `CommentsRepository.kt` | `member_comments` read/insert. |
| `InviteRepository.kt` | invitations/units + `invite_power_user`/`revoke_power_user` rpc. |
| `AdminRepository.kt` | `app_admins` list + `revoke_admin` rpc. |
| `Net.kt` | Shared Ktor `HttpClient` (OkHttp) + manual JSON + `JsonObject` accessors. |
| `BrokerClient.kt` | Church-login broker (password/MFA, email relay, enrollment, sync-now, revoke, schedule, Google Drive, contact, report) — ported from `broker_client.dart`. |
| `AdminClient.kt` | Broker `/admin/*` + `/feedback` — ported from `admin_client.dart`. |
| `PasskeyClient.kt` | WebAuthn via Credential Manager against `/webauthn/*` — native analog of `passkey_client.dart`. |
| `ErrorReporter.kt` | Uncaught-error telemetry → broker `/log` (no PII). |
| `AppPrefs.kt` | DataStore prefs: theme, app-lock, current stake, passkey-suggested. |

## viewmodel/ — MVVM (StateFlow)
| File | Purpose |
|---|---|
| `AuthViewModel.kt` | `gate` + the 3-mode login flow (church/MFA, email/relay, passkey). |
| `DashboardViewModel.kt` | Stakes/members, admin check, enrollment status, syncing banner, sync-now/revoke, stake persistence, passkey upsell. |
| `ThemeViewModel.kt` / `AppLockViewModel.kt` | Persisted theme cycle / app-lock pref. |
| `InviteViewModel.kt` | Power-user list + invite/revoke. |
| `AdminViewModel.kt` | Independently-loaded admin panels + maintenance/rerun/revoke/sync/invite. |
| `ActionsViewModel.kt` | Contact, feedback, report(+email), add-passkey. |
| `SyncSettingsViewModel.kt` | Schedule + Google Drive sections. |
| `CommentsViewModel.kt` | Member notes read/add (+ factory). |
| `ViewModelFactory.kt` | `AppViewModelFactory` for the Context-backed ViewModels. |

## ui/ — Compose
| File | Purpose |
|---|---|
| `App.kt` | Theme + auth gate + biometric gate + NavHost (dashboard/detail/settings/invite/admin). |
| `MainActivity.kt` | `FragmentActivity` host; installs error reporting; `setContent { App() }`. |
| `BiometricLock.kt` | `AppBiometric` (BiometricPrompt availability + authenticate). |
| `theme/Color.kt` / `theme/Theme.kt` | Accent palettes + Material3 theme (persisted light/dark/system). |
| `screens/LoginScreen.kt` | 3-mode sign-in + disclaimer + status/error. |
| `screens/BiometricGate.kt` | Locked screen + unlock prompt. |
| `screens/DashboardScaffold.kt` | Top bar (stake switcher, freshness chip, overflow), banners, skeleton, empty states, sheets, snackbars, passkey upsell. |
| `screens/PersonDetailScreen.kt` | Header + open-in-LCR + milestone chips + rich `details` + notes. |
| `screens/SettingsScreen.kt` | Appearance/Security/Support/About/Account (self-hosted dialogs + snackbar). |
| `screens/InviteScreen.kt` | Power-user invite/revoke + unit-scope picker. |
| `screens/AdminScreen.kt` | The full Ops console (5 panels). |
| `screens/SyncSettingsSheet.kt` | Status + schedule + Google Drive. |
| `screens/ReportSheet.kt` | Report totals + most-needed + outstanding + email. |
| `screens/StatusScreens.kt` | Loading/error/empty + `EnrollmentEmptyState`. |
| `screens/ConfigErrorScreen.kt` | Blank-Supabase config screen. |
| `screens/tabs/*` | Baptisms, GoldenHour, Needs, **Kpis** (+ `KpiDrillSheets`), Table, MissingSheet. |
| `components/MilestoneChips.kt`,`OrgFilterBar.kt`,`MemberRow.kt`,`Common.kt`,`Avatars.kt` | Shared list/detail widgets. |
| `components/FreshnessChip.kt`,`Banners.kt`,`Shimmer.kt` | Freshness chip + dialog, syncing/stale banners, skeletons. |
| `components/LineChart.kt` | Hand-drawn Canvas trend line (gradient fill, dots, value labels, prev overlay, tap→bucket). |
| `components/MissionaryChip.kt` | Missionary name chip → call/email. |
| `components/MissionariesSection.kt` | `MissionaryStrip` (chip row) + `MissionariesSection` (contact-line list) — shared by Baptisms cards + the per-person "Missionaries by Unit" section + the investigator detail. |
| `components/GoldenHourRows.kt` | Per-member Golden-Hour completion rows (one row per item: ✓ done / ○ not done / ⚠ data issue; N/A omitted). Mirrors web `GoldenHourRows.tsx`. |
| `components/Dialogs.kt` | Contact/Feedback/About/Confirm dialogs + disclaimer copy. |
| `util/Dates.kt` | Display date formatters. |

## test/ — JVM unit tests
| File | Purpose |
|---|---|
| `logic/DateParseTest.kt`,`MilestonesTest.kt`,`OrgsTest.kt` | Date/milestone/org logic (existing). `MilestonesTest` also covers `goldenHourRows`/`nextSteps`/`isMissing` (done/not-done/⚠ classification + N/A omission). |
| `logic/FieldDisplayTest.kt` | The sentinel/N-A/⚠ display contract (`FieldDisplay.classify`): real value verbatim, N/A quiet, sentinel-or-empty = data issue (admin sees raw, leader doesn't). Mirrors web `fieldDisplay.ts`. |
| `logic/KpisTest.kt` | KPI windows (5 weekly / 12 monthly buckets), unique-per-bucket, event→bucket mapping, ALL year/month granularity, lessons-with-member, range labels. |
| `logic/FreshnessTest.kt` | `ago` buckets + staleness color thresholds. |
