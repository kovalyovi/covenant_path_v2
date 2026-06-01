# Covenant Path — Native Android (PoC)

A proof-of-concept native Android rebuild of the Flutter viewer (`apps/viewer`), to compare native
architecture/feel against Flutter. **Kotlin + Jetpack Compose + Material 3**, MVVM, Supabase via
**supabase-kt**. Read-only: the app only ever reads Supabase (RLS-scoped); it never touches the
church system.

> Shared brief: `../SPEC.md`. Business logic mirrors `apps/viewer/lib/golden_hour.dart` and the
> dashboard views exactly (ported, not transliterated).

## Architecture

Single-Activity + Compose, unidirectional data flow:

```
ui/ (Compose)
  screens/        LoginScreen, DashboardScaffold (5-tab bottom nav), PersonDetailScreen,
                  ConfigErrorScreen, StatusScreens
  screens/tabs/   BaptismsScreen, GoldenHourScreen, NeedsScreen, KpisScreen (stub), TableScreen
  components/     GoldenHourChips, OrgFilterBar, MemberRow, SectionCard, Avatars, FlowLayout …
  theme/          Material3 theme (indigo seed, dynamic color) + Tab/Org/Milestone/Status colors
        ▲ collectAsStateWithLifecycle
viewmodel/        AuthViewModel, DashboardViewModel  (ViewModel + StateFlow)
        ▲
data/             SupabaseClientProvider, AuthRepository, MembersRepository  (repository layer)
        ▲
model/            Member, Stake, Details, … (kotlinx-serializable; @SerialName == DB columns)
logic/            Milestones, OrgBucket(Orgs), DateParse  (PURE Kotlin — unit-tested)
util/             Dates (display formatters)
```

- **State**: each screen reads a `StateFlow<…UiState>` from its `ViewModel`; UI is a pure function
  of state. Coroutines + `Flow` for all async.
- **Navigation**: `androidx.navigation:navigation-compose`. The detail route takes a `person_uuid`
  and looks the member up from the dashboard's loaded list (no whole-object serialization).
- **Auth gate**: `AuthViewModel.gate` maps supabase-kt's `sessionStatus` (`Initializing` →
  Loading, `Authenticated`/`NotAuthenticated`) to route Login vs Dashboard.
- **RLS only**: no app-side access checks. The dashboard scopes to ONE stake
  (`.eq("stake_id", id)`) exactly like the Flutter `_load`.

## Build / run

You need **Android Studio (Ladybug or newer)** with the Android SDK (this PoC was authored without a
local JDK/Gradle, so it has **not been compiled** — see caveats).

1. Open `native/android/` in Android Studio (it will sync Gradle and download dependencies,
   including supabase-kt from Maven Central). Or use the bundled wrapper: `./gradlew :app:assembleDebug`.
2. Provide the Supabase config (the anon/publishable key is safe on clients — RLS does the gating;
   **never commit a real key**). Any of:
   - Gradle properties (CLI): `./gradlew :app:assembleDebug -PSUPABASE_URL=https://<ref>.supabase.co -PSUPABASE_ANON_KEY=sb_publishable_...`
   - Environment variables `SUPABASE_URL` / `SUPABASE_ANON_KEY` (CI-friendly).
   - A git-ignored `~/.gradle/gradle.properties` with the two keys.
   These feed `BuildConfig.SUPABASE_URL` / `BuildConfig.SUPABASE_ANON_KEY` (see `app/build.gradle.kts`).
   With blank config the app shows a config screen (mirrors the Flutter `_ConfigError`).
3. Run on a device/emulator (minSdk 26 / target 35). Sign in with **email OTP**: enter the email
   your stake has on file → Supabase emails a 6-digit code → enter it.

Unit-test the ported logic (no device needed): `./gradlew :app:testDebugUnitTest`.

## Versions

| Thing | Version |
|---|---|
| Kotlin | 2.1.0 (standalone Compose compiler plugin `org.jetbrains.kotlin.plugin.compose`) |
| AGP | 8.7.3 |
| Compose BOM | 2024.12.01 (Material 3) |
| supabase-kt (BOM) | 3.1.1 — modules `auth-kt` (gotrue) + `postgrest-kt`, serializer = kotlinx |
| Ktor | 3.0.3 (`ktor-client-okhttp` engine) |
| navigation-compose | 2.8.5 · lifecycle 2.8.7 · Coil 2.7.0 |
| min / target SDK | 26 / 35 |

> Note: supabase-kt renamed the `gotrue-kt` artifact to **`auth-kt`** in 3.0.0 (the API is still
> `supabase.auth`). The version catalog uses `auth-kt`; the BOM pins module versions together.

## Implemented vs stubbed

**Implemented**
- Email-OTP login (`signInWith(OTP)` → `verifyEmailOtp`) via gotrue.
- Supabase data layer: typed `Member` model + `MembersRepository` selecting the exact Flutter
  column list, scoped to one stake, ordered by unit then name; stakes + missionaries decode.
- **Baptisms** — investigators with a planned date as a timeline: overdue ("date passed") block,
  then "Scheduled", grouped by date with relative-day labels.
- **Golden Hour** — New Members (completion % per milestone, eligible-only; milestone chips with
  next-step highlight; WML/EQ/RS org filter all-on-by-default + Clear filters; Week/Month/Year/All
  window; tap a stat → who's still missing it) and Being Taught.
- **Needs** — per-milestone category selector with outstanding counts; eligible members still
  missing the step; per-unit colored breakdown; same org filter; baptism-date sort toggle.
- **Person Detail** — header (photo/initials + baptism line), milestone pills, and the rich
  `details` sections (sacrament dots, friends, priesthood, calling, ministering assignment,
  ministers' names, temple, principles-taught dots, self-reliance, flags). Flat-field fallback when
  `details` is absent. "names temporarily unavailable" note when a Yes flag has no names.
- **Table** — every field, color-coded (Yes/No/N-A, recommend, sex), 3-state sort on text columns,
  horizontal scroll.
- **Milestone / org-ownership / date-parsing logic** ported 1:1 and covered by unit tests.

**Stubbed / out of scope** (per SPEC.md)
- **KPIs** — labeled stub with summary numbers; no time-series charts (Compose has no first-party
  chart lib; Vico would be the next step).
- Table's per-column value-filter popups (sorting is implemented; filtering omitted).
- Church-account broker login, passkeys, admin/ops console, report generation, Google Drive, push,
  in-app schedule, notes/comments, the photo pipeline (we show `photo_url` if present, else initials).

## Compile caveats (be honest)

This project was **written without a local Android toolchain (no JDK/Gradle/Android Studio on the
authoring machine), so it has not been compiled or run.** It is written to be correct and idiomatic:

- supabase-kt 3.1.1 API usage (`createSupabaseClient { install(Auth); install(Postgrest);
  defaultSerializer = KotlinXSerializer(json) }`, `signInWith(OTP)`, `verifyEmailOtp(type =
  OtpType.Email.EMAIL, …)`, `postgrest.from(...).select(Columns.raw(...)) { filter { eq(...) };
  order(...) }.decodeList<Member>()`, `auth.sessionStatus`) was verified against the v3.1.1 source.
- The Gradle wrapper jar + scripts are included so Android Studio can sync immediately; if the
  wrapper jar is rejected, run `gradle wrapper --gradle-version 8.11.1` once.
- Expect to resolve the usual first-sync papercuts (an icon name in `material-icons-extended`, a
  dependency version nudge). The pure `logic/` layer + its tests are the most robust part and are
  the truest apples-to-apples comparison against `golden_hour.dart`.
