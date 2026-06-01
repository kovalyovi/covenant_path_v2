# Implementation Notes — files & purpose

Root package: `org.membercovenantpath.viewer`. One module: `:app`.

## Gradle / config
| File | Purpose |
|---|---|
| `settings.gradle.kts` | Module + repos (google + mavenCentral). |
| `build.gradle.kts` (root) | Declares plugins `apply false`. |
| `app/build.gradle.kts` | Android + Compose + serialization; reads `SUPABASE_URL`/`SUPABASE_ANON_KEY` from gradle props/env into `BuildConfig`. |
| `gradle/libs.versions.toml` | Version catalog (Kotlin 2.1, Compose BOM, supabase-kt 3.1.1 BOM, Ktor, nav, Coil). |
| `gradle.properties` | AndroidX/Compose flags; empty `SUPABASE_*` placeholders (never commit a key). |
| `app/proguard-rules.pro` | Keep kotlinx-serialization serializers for `model/`. |
| `app/src/main/AndroidManifest.xml` | INTERNET permission; single `MainActivity`. |
| `app/src/main/res/values/{strings,themes}.xml` | App name + a Material3 launch theme. |
| `gradle/wrapper/*`, `gradlew`, `gradlew.bat` | Gradle 8.11.1 wrapper (jar copied from the repo's Flutter android wrapper). |

## logic/ — pure Kotlin, ported 1:1 from `golden_hour.dart` (unit-tested)
| File | Purpose |
|---|---|
| `DateParse.kt` | `parseMemberDate` (ISO / `6 Feb 2026` / `2/6/2026` / sentinels→null), `yearOf`, `ageNow`, `memberOneYearPlus`, `monthsSince`, `monthsDaysAgo`. |
| `Milestones.kt` | The 6 milestones (label/abbr/icon/color + eligible/complete predicates), `forMember`, `avgCompletion`. |
| `OrgBucket.kt` | `OrgBucket` enum + `Orgs` (info/colors, `responsibleOrg`, `responsibleParty`, `responsibilityNote`). |

## model/ — kotlinx-serializable; `@SerialName` == DB columns
| File | Purpose |
|---|---|
| `Member.kt` | One `members` row (the Flutter `_columns` set); `status(field)` accessor. |
| `Stake.kt` | `Stake` + `Missionary`. |
| `Details.kt` | Typed `members.details` subtree (friends, ministers, sacrament, lessons, toggles, tags…). |
| `DetailsParse.kt` | `Member.parsedDetails()` — lenient decode of the `details` JsonObject. |

## data/ — repository layer
| File | Purpose |
|---|---|
| `SupabaseClientProvider.kt` | Single `SupabaseClient` from `BuildConfig`; installs Auth + Postgrest; lenient kotlinx serializer; `isConfigured`. |
| `AuthRepository.kt` | Email-OTP: `sendEmailCode` (`signInWith(OTP)`), `verifyEmailCode` (`verifyEmailOtp`), `sessionStatus`, `signOut`. |
| `MembersRepository.kt` | `loadStakes`, `loadMembers(stakeId)` (exact column list, `.eq(stake_id)`, order unit→name), `missionariesByUnit`. |

## viewmodel/ — MVVM (StateFlow)
| File | Purpose |
|---|---|
| `AuthViewModel.kt` | `gate` (Loading/SignedOut/SignedIn from `sessionStatus`) + `LoginUiState` (email→code steps). |
| `DashboardViewModel.kt` | Bootstraps stakes → scopes to first stake → loads members; `switchStake`, `refresh`; `DashboardUiState`. |

## ui/ — Compose
| File | Purpose |
|---|---|
| `App.kt` | Theme + auth gate + NavHost (dashboard, `detail/{uuid}`). |
| `MainActivity.kt` | Single-Activity host; `setContent { App() }`; edge-to-edge. |
| `theme/Color.kt` | Tab/Org/Milestone/Status/unit palettes (match the Flutter hex values). |
| `theme/Theme.kt` | Material3 theme (indigo seed, dynamic color on Android 12+, dark mode). |
| `screens/LoginScreen.kt` | Email + 6-digit code form. |
| `screens/DashboardScaffold.kt` | TopAppBar (stake switcher), 5-tab `NavigationBar` (per-tab accent), body switch. |
| `screens/PersonDetailScreen.kt` | Header + milestone pills + rich `details` sections + flat fallback. |
| `screens/StatusScreens.kt` | Loading / error / empty-members / empty-panel. |
| `screens/ConfigErrorScreen.kt` | Shown when `SUPABASE_*` are blank. |
| `screens/tabs/BaptismsScreen.kt` | Date timeline (overdue → scheduled), per-date rail rows. |
| `screens/tabs/GoldenHourScreen.kt` | Segmented New/Taught; completion card; org filter; window; list. |
| `screens/tabs/MissingSheet.kt` | Bottom sheet of eligible members still missing a milestone. |
| `screens/tabs/NeedsScreen.kt` | Category chips + missing list + per-unit chips + org filter + sort. |
| `screens/tabs/TableScreen.kt` | Sortable, color-coded field grid. |
| `screens/tabs/KpisScreen.kt` | Stub (summary numbers; charts not implemented). |
| `components/MilestoneChips.kt` | `GoldenHourChips` (circle / labeled pills, next-step ring). |
| `components/OrgFilterBar.kt` | WML/EQ/RS toggle chips + Clear filters. |
| `components/MemberRow.kt` | Member list row (photo, age, date, responsibility chip, chips). |
| `components/Common.kt` | `SectionCard`, `CountBadge`, `BigHeader`, `AccentBar`, `FlowLayout`, `MutedText`. |
| `components/Avatars.kt` | `InitialsAvatar`, `PhotoAvatar` (Coil), `initialsOf`. |
| `util/Dates.kt` | Display date formatters (matching the Flutter intl patterns). |

## test/ — JVM unit tests (no device)
| File | Purpose |
|---|---|
| `logic/DateParseTest.kt` | Date formats, sentinels, age, member-1yr, `monthsDaysAgo`. |
| `logic/MilestonesTest.kt` | Eligibility (age/sex/tenure gates), completion, eligible-only averages. |
| `logic/OrgsTest.kt` | Unassigned / first-year-WML / after-year EQ-RS / 12-month boundary. |
