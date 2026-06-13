# Android — PARITY_STATUS

Maps every numbered item in `../PARITY.md` (sections A–F) to **Done / Partial / Stub** for the
native **Android** app. Reference: the React web app (`apps/web/src/`) — the bracketed `*.dart` names
in PARITY.md are the original (now-deleted, 2026-06-13) Flutter sources. Build contract: standard
Gradle, `./gradlew :app:assembleDebug` (+ `:app:testDebugUnitTest`).

| # | Item | Status | Note |
|---|------|--------|------|
| 1 | AuthGate (session → biometric → dashboard) | **Done** | `AuthViewModel.gate` off supabase-kt `sessionStatus`; `App.kt` routes Login / BiometricGate+Dashboard. |
| 2 | Config-error screen | **Done** | `ConfigErrorScreen` when `AppConfig.supabaseConfigured` is false. |
| 3 | Login — 3 modes (Church+MFA, Email code, Passkey) | **Done** | `LoginScreen` + `AuthViewModel`: password→choose factor→verify (broker `/auth/password,/mfa/select,/mfa/verify` → `verifyEmailOtp`); email send/verify with broker-relay backup (`/auth/email/*` → `adoptRefreshToken`); passkey via Credential Manager (`PasskeyClient` → `/webauthn/*`). Disclaimer + footer + "waking up" status + error line. |
| 4 | Biometric app-lock | **Done** | `AppBiometric` (androidx.biometric BiometricPrompt) + `BiometricGate`; toggle in Settings persisted via DataStore (`AppLockViewModel`/`AppPrefs`). |
| 5 | Dark mode (light/dark/system, persisted) | **Done** | `ThemeViewModel`+`AppPrefs` (DataStore), `CovenantPathTheme(choice)`, cycle in Settings. Dynamic color off to keep brand/accents constant. |
| 6 | Title = stake name + stake switcher | **Done** | `DashboardScaffold` `StakeTitle` (dropdown when >1 stake); choice persisted (`AppPrefs.currentStakeId`). |
| 7 | Freshness chip + Sync-now dialog | **Done** | `FreshnessChip` (amber >2d / red >2w via `Freshness.staleColor`); dialog with exact local time + "Sync now" (provider). |
| 8 | Overflow menu | **Done** | Sync settings, Generate report, Invite a power user, Admin·Ops (admins only), Settings. |
| 9 | Syncing banner (elapsed) + stale-credential banner | **Done** | `SyncingBanner` (1s timer), `StaleCredentialBanner` (revoked → re-enroll; stale → provider "Re-authorize" / other leaders "Authorize on my account", mirrors web). The action opens the in-app `ReauthDialog` (enroll=true MFA-aware Church sign-in over the dashboard, adopts the re-minted session, reloads enrollment status + toasts — never the login screen; sign-out fallback only without a broker). |
| 10 | 5 tabs each accent color; single-stake query | **Done** | `DashboardTab` accents; `MembersRepository` `.eq(stake_id)` + exact `_columns`. |
| 11 | Skeleton loading + per-enrollment empty states | **Done** | `MemberListSkeleton`/`CardSkeleton`; `EnrollmentEmptyState` (no-role "Authorize stake sync" / revoked + stale "Re-authorize" / active / generic) — all authorize actions open `ReauthDialog` (web-parity copy). |
| 12 | Baptisms (overdue→scheduled, combined/per-unit, missionary strip) | **Done** | `BaptismsScreen` with Date/Unit toggle; per-unit cards show `MissionaryStrip` → `MissionaryChip` (tap → call/email). |
| 13 | Golden Hour (segmented, completion card, org filter, window, layout/sort, drill) | **Done** | `GoldenHourScreen` (pre-existing) — New/Taught, completion %, WML/EQ/RS filter, Week/Month/Year/All, missing-drill sheet. |
| 14 | Needs (category chips, missing list, per-unit chips, org filter, sort) | **Done** | `NeedsScreen` (pre-existing). |
| 15 | KPIs (charts, period+range+compare, overview grid, GH-by-unit, drills) | **Done** | `KpisScreen` + hand-drawn `LineChart` (Canvas, no chart-lib); series math `Kpis.kt` ported 1:1 from `dashboard_common.dart`/`kpis_view.dart`; `KpiDrillSheet`/`GoldenHourBreakdownSheet`/`LessonsDrillSheet`. |
| 16 | Table (sortable, color-coded, full scroll) | **Done** | `TableScreen` (pre-existing): 3-state sort, color cells, horizontal scroll. **Per-column value-filter dialogs: Partial** (sort done; the value-picker popup is not ported — see below). |
| 17 | Person detail header + open in LCR | **Done** | `PersonDetailScreen` header + LCR deep-link action. |
| 18 | Golden Hour milestone chips (labeled, next step) | **Done** | `GoldenHourChips(labeled=true, highlightNext=true)`. |
| 19 | Detail sections from `details` | **Done** | Sacrament dots, Friends, Priesthood, Calling (alert), Ministering assignment, Ministers' names, Temple, Principles-taught dots, Self-Reliance, Flags + flat fallback + "names temporarily unavailable". |
| 20 | Notes/comments (read+add) | **Done** | `CommentsViewModel`/`CommentsRepository` on `member_comments` (RLS); author + local timestamp. |
| 21 | Sync settings sheet (status, sync-now, revoke, schedule, Google Drive) | **Done** | `SyncSettingsSheet` + `SyncSettingsViewModel`: enrollment status, "Sync my stake now", revoke, schedule (ET hour + pause/resume `/auth/schedule`), Google Drive (connect/disconnect/sheet link/last refreshed/needs-reconnect `/auth/google/*`). |
| 22 | Generate report (+ email) | **Done** | `ReportSheet` from broker `GET /report`; "Email to me" → `POST /report/email`. |
| 23 | Invite power users | **Done** | `InviteScreen`/`InviteViewModel`: list grouped by email, invite (rpc `invite_power_user`), revoke (rpc `revoke_power_user`), unit-scope picker. |
| 24 | Settings screen | **Done** | `SettingsScreen`: Appearance (theme cycle), Security (add passkey + app-lock), Support, About & privacy, Account (email + sign out). |
| 25 | Contact support + Send feedback + passkey upsell | **Done** | `ContactDialog`→`/contact`, `FeedbackDialog`→`/feedback` (GitHub issue); one-time post-login passkey upsell snackbar. |
| 26 | Admin · Ops console | **Done** | `AdminScreen`/`AdminViewModel`: health/freshness/maintenance/links (`/admin/summary`), diagnostics (`/admin/diagnostics`), enrolled stakes (state chip incl. "Stale · needs re-auth" + last-error line + the authorization-cadence line "authorized <ago> · self-renewing | manual re-auth needed when session expires · N re-auths/30d" from `self_renewing`/`reauths_30d`; confirm-gated per-stake Sync now / Revoke / Wipe data / Remove, mirrors web), GitHub Actions runs (+re-run) & changelog (`/admin/actions`), admins (invite `/admin/invite` + revoke rpc). Each panel loads independently. |
| 27 | Error reporting → broker /log | **Done** | `ErrorReporter` (type + truncated message + surface, no PII); installed as the uncaught-exception handler in `MainActivity`. Sentry: not added (NICE-TO-HAVE only). |
| 28 | No secrets in code; BuildConfig | **Done** | `SUPABASE_URL`/`SUPABASE_ANON_KEY`/`BROKER_URL` BuildConfig fields, empty defaults; nothing committed. |
| 29 | Selectable text | **Done** | Native `Text` is copyable via long-press; text fields select normally. (No app-wide SelectionContainer wrapper, matching native idiom.) |

## Partial / Stub — and why
- **#16 Table per-column value-filter dialogs — Partial.** The grid is sortable (3-state) and fully
  color-coded, and shows the row count, but the per-column "pick which values to show" popup (see the
  web `apps/web/src/pages/tabs/TableTab.tsx`) is not ported. Sorting + color-coding + row→detail are present; this is the one
  deliberate gap (it was already omitted in the original PoC). Everything else in Table is Done.

Everything else in A–F is **Done**.

## Build notes (CI: assembleDebug)
- Version catalog resolves to published versions: Kotlin 2.1.0 + `org.jetbrains.kotlin.plugin.compose`,
  AGP 8.7.3, Compose BOM 2024.12.01, supabase-kt 3.1.1 (BOM; `auth-kt`+`postgrest-kt`), Ktor 3.0.3
  (`ktor-client-okhttp`+`-core`), navigation-compose 2.8.5, Coil 2.7.0, androidx.biometric 1.1.0,
  androidx.credentials 1.3.0 (+play-services-auth), datastore-preferences 1.1.1, fragment 1.8.5,
  com.google.android.material 1.12.0 (only for the XML launch-theme parent). All confirmed on Maven
  Central / Google Maven.
- Every Compose Material icon used was audited against `material-icons-extended` 1.7.6 +
  `material-icons-core` 1.7.6 (all present).
- Charts are hand-drawn on a Compose `Canvas` (no Vico/MPAndroidChart), so there is no chart-lib API
  to break the build.
- `MainActivity` is a `FragmentActivity` (BiometricPrompt requirement); `androidx.fragment` is pinned
  to 1.8.5 so it stays coherent with activity 1.9.x / lifecycle 2.8.x.
- Pure logic (`logic/Milestones`, `OrgBucket`, `DateParse`, `Kpis`, `Freshness`) is unit-tested
  (`:app:testDebugUnitTest`).

## Addendum (2026-06-10): notes on list rows
- **List-row note lines** — newest leader note (+N) under each person in Golden Hour / Needs / by-date lists (`MemberRow` + `NoteLine` via `LocalMemberNotes`), the Baptisms timeline rows, and a note marker in the Table's Member cell. Data: one bulk RLS-scoped `member_comments` fetch per stake load (`CommentsRepository.stakeNotes` -> `NotesIndex.build`, unit-tested in `NotesIndexTest`); posting a note on detail refreshes the index (`DashboardViewModel.reloadNotes`). **Pending CI assembleDebug + AVD verification.**
