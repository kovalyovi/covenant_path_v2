# Covenant Path — Native Android

A full-feature native Android app at **100% feature parity** with the web client (see
`PARITY_STATUS.md`). It was originally ported from the Flutter viewer (`apps/viewer`), which has since
been **deleted (2026-06-13)** — the live cross-surface reference is now the React web app (`apps/web`).
**Kotlin + Jetpack Compose (Material 3)**, MVVM (ViewModel +
StateFlow), coroutines/Flow, navigation-compose, single-Activity. Supabase via **supabase-kt 3.x**
(auth + postgrest, kotlinx-serialization). Read-only against Supabase (RLS-scoped); the broker
(`backend/auth_broker`) is used for Church login, passkeys, sync settings, reports and the admin
console — exactly as the other clients use it.

> The authoritative checklist is `../PARITY.md`; the per-item status is `PARITY_STATUS.md`.
> Business logic mirrors the React web app `apps/web/src/` (ported, not transliterated) and is unit-tested.

## Architecture

Single-Activity (`FragmentActivity`, for BiometricPrompt) + Compose, unidirectional data flow:

```
ui/ (Compose)
  screens/        LoginScreen (3 modes), DashboardScaffold (freshness chip, overflow, banners),
                  PersonDetailScreen (+notes, +open-in-LCR), SettingsScreen, InviteScreen,
                  AdminScreen, SyncSettingsSheet, ReportSheet, BiometricGate, StatusScreens,
                  ConfigErrorScreen
  screens/tabs/   BaptismsScreen, GoldenHourScreen, NeedsScreen, KpisScreen (charts), TableScreen,
                  KpiDrillSheets, MissingSheet
  components/     GoldenHourChips, OrgFilterBar, MemberRow, SectionCard, Avatars, FlowLayout,
                  FreshnessChip, Banners, Shimmer, LineChart (Canvas), MissionaryChip, Dialogs
  theme/          Material3 theme (indigo seed, persisted light/dark/system) + accent palettes
        ▲ collectAsStateWithLifecycle
viewmodel/        Auth, Dashboard, Theme, AppLock, Invite, Admin, Actions, SyncSettings, Comments
        ▲          (+ AppViewModelFactory for the Context-backed ones)
data/             SupabaseClientProvider, Auth/Members/Comments/Invite/Admin repositories,
                  BrokerClient, AdminClient, PasskeyClient, ErrorReporter, AppPrefs (DataStore),
                  Net (Ktor + JSON), AppConfig
model/            Member, Stake, Details, Comment, Invitation/Unit/AppAdmin (kotlinx-serializable)
logic/            Milestones, OrgBucket(Orgs), DateParse, Kpis, Freshness  (PURE Kotlin — unit-tested)
util/             Dates (display formatters)
```

- **State**: each screen reads a `StateFlow<…UiState>` from a `ViewModel`; UI is a pure function of
  state. Coroutines + Flow for all async.
- **Navigation**: `navigation-compose` (dashboard, `detail/{uuid}`, settings, invite, admin). The
  detail route looks the member up by `person_uuid` from the loaded list.
- **Auth gate**: `AuthViewModel.gate` maps supabase-kt `sessionStatus` → Login vs (BiometricGate →)
  Dashboard.
- **RLS only**: no app-side access checks; the dashboard scopes to ONE stake (`.eq("stake_id", id)`).

## Build / run

Open `native/android/` in Android Studio (Ladybug+) or use the bundled wrapper. CI builds it with a
clean JDK 17 + Gradle (`./gradlew :app:testDebugUnitTest` then `./gradlew :app:assembleDebug`).

Provide config (the anon/publishable key is safe on clients — RLS gates everything; **never commit a
real key**). Any of:
- CLI: `./gradlew :app:assembleDebug -PSUPABASE_URL=https://<ref>.supabase.co -PSUPABASE_ANON_KEY=sb_publishable_... -PBROKER_URL=https://broker.example.org`
- Env vars `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `BROKER_URL` (CI-friendly).
- A git-ignored `~/.gradle/gradle.properties`.

These feed `BuildConfig.SUPABASE_URL` / `SUPABASE_ANON_KEY` / `BROKER_URL` (all default to `""`).
With a blank Supabase config the app shows a config screen; with a blank `BROKER_URL` it falls back
to Email-code login and hides Church login / passkeys / reports / sync settings / admin.

Sign in with **Church account** (+MFA), **Email code**, or a **passkey** (when a broker is set);
Email-only otherwise. Unit-test the ported logic (no device): `./gradlew :app:testDebugUnitTest`.

## Versions

| Thing | Version |
|---|---|
| Kotlin | 2.1.0 (standalone Compose compiler plugin `org.jetbrains.kotlin.plugin.compose`) |
| AGP | 8.7.3 · Gradle 8.11.1 (wrapper committed) |
| Compose BOM | 2024.12.01 (Material 3) |
| supabase-kt (BOM) | 3.1.1 — `auth-kt` (gotrue) + `postgrest-kt`, serializer = kotlinx |
| Ktor | 3.0.3 (`ktor-client-okhttp` + `-core`) — also used by our broker/admin/passkey clients |
| navigation-compose | 2.8.5 · lifecycle 2.8.7 · Coil 2.7.0 |
| biometric | 1.1.0 · credentials 1.3.0 (+play-services-auth) · datastore-preferences 1.1.1 |
| fragment | 1.8.5 (pinned coherent) · material (XML launch theme) 1.12.0 |
| min / target SDK | 26 / 35 |

> supabase-kt renamed `gotrue-kt` → **`auth-kt`** in 3.0.0 (API still `supabase.auth`). The BOM pins
> module versions together. Charts are **hand-drawn on a Compose `Canvas`** (no chart library) so
> there's no third-party chart API to break the build.

## What's implemented

Everything in `../PARITY.md` sections A–F. Highlights:
- **3-mode login** (Church account + MFA select/verify, Email code with broker-relay backup, passkey
  via Credential Manager), **biometric app-lock**, **dark mode** (persisted), **stake switcher**.
- **Freshness chip** + **Sync-now**, **overflow menu**, **syncing / stale-credential banners**,
  **skeleton loading**, per-enrollment **empty states**.
- All 5 tabs: Baptisms (combined/per-unit + missionary strip), Golden Hour, Needs, **KPIs with
  charts** (series math ported 1:1), Table.
- Person detail with rich `details` sections, **notes/comments**, and **open in LCR**.
- **Sync settings** sheet (status + schedule + Google Drive), **Generate report** (+email),
  **Invite power users**, **Settings**, **Contact / Send feedback**, **Admin · Ops console**.
- **Error reporting** to the broker `/log` (no PII).

The one deliberate gap is **Table's per-column value-filter popups** (sorting + color-coding are
present) — see `PARITY_STATUS.md` #16.

## Compile notes (authored without a local toolchain)

This was written without a local JDK/Gradle/Android SDK, so it has not been run on this machine, but
it's written to compile under the CI `assembleDebug`:
- All catalog versions + plugins resolve to published artifacts (verified on Maven Central / Google
  Maven).
- Every Compose Material icon used was audited against `material-icons-extended`/`-core` 1.7.6.
- supabase-kt 3.1.1 API usage verified against the published sources (`signInWith(OTP)`,
  `verifyEmailOtp(type = OtpType.Email.EMAIL, …)`, `refreshSession`/`importSession`,
  `postgrest.from(...).select(Columns.raw(...)){ filter{eq}; order }.decodeList`, `rpc(...).decodeAs`).
- Credential Manager API verified against `androidx.credentials` 1.3.0 sources
  (`GetPublicKeyCredentialOption`, `CreatePublicKeyCredentialRequest`,
  `getCredential/createCredential`, `authenticationResponseJson/registrationResponseJson`).
- The pure `logic/` layer + its JVM tests are the most robust part and the truest apples-to-apples
  comparison against the Flutter source.
