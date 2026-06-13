# Native iOS — PARITY_STATUS

Maps every numbered item in `native/PARITY.md` (A–F, 1–29) to **Done / Partial / Stub** with a
one-line note. Reference: the React web app (`apps/web/src/`) — the original Flutter app the bracketed
`*.dart` names point to was deleted 2026-06-13. Logic is ported exactly; only the
UI placement adapts to native idioms (TabView / NavigationStack / Form / .sheet / SF Symbols /
Swift Charts).

## A. Entry / auth
1. **AuthGate** — **Done.** `RootView` → `SessionStore.phase` switch; listens to `auth.authStateChanges`; signed-in path goes through the biometric gate. (`RootView.swift`, `SessionStore.swift`)
2. **Config-error screen** — **Done.** `ConfigErrorView` when SUPABASE_URL/ANON_KEY missing (`AppConfig.isConfigured`).
3. **Login — 3 modes** — **Done (passkey Partial, see below).** Segmented Church/Email when broker configured, else Email only. Church: username/password → MFA factor list → code → verify (broker `/auth/password`,`/auth/mfa/select`,`/auth/mfa/verify` → Supabase `verifyOTP`), consent note shown. Email: OTP send/verify with the broker-relay fallback toggle (`/auth/email/start`,`/verify`). Disclaimer + footer + transient status + error lines. (`LoginView.swift`, `BrokerService.swift`)
   - **Passkey — Partial.** Full native `ASAuthorization` WebAuthn flow is implemented (`PasskeyService.swift`, broker `/webauthn/*` begin+complete, base64url marshaling), but `available` is gated behind a `PASSKEY_RP_ID` build value because platform passkeys need an associated-domains entitlement that can't be provisioned in the unsigned CI build. When unset, the login/Settings button is shown **disabled with a clear "use email code on this device" note** (the documented one partial item).
4. **Biometric app-lock** — **Done (opt-in).** `BiometricGateView` + `BiometricService` (LocalAuthentication, persisted pref, Settings toggle). **2026-06-13: OFF by default — Face ID is not required to open the app** (user directive); the gate computes its state synchronously so the default never renders a lock screen.
5. **Dark mode** — **Done.** `ThemeController` (system/light/dark, persisted) → `.preferredColorScheme`; cycle toggle in Settings.

## B. Dashboard shell
6. **Title = stake name + switcher** — **Done.** `DashboardView.stakeTitle` (Menu when >1 stake; choice persisted in `AppPrefs`).
7. **Freshness chip + Sync now** — **Done.** Toolbar chip (amber/red staleness via `Freshness`) → alert with exact local time + "Sync now" (provider). Refresh action re-pulls. (`Freshness.swift`)
8. **Overflow menu** — **Done.** Sync settings · Generate report · Invite a power user · Admin·Ops (admins only) · Settings.
9. **Syncing + stale banners** — **Done.** `SyncingBanner` (1s elapsed timer) + `StaleBanner` (revoked → re-enroll; stale → provider "Re-authorize" / other leaders "Authorize on my account", mirrors web). The action opens the in-app re-auth sheet (`ReauthSheet`: enroll=true MFA-aware Church sign-in over the dashboard, adopts the re-minted session, reloads enrollment status + toasts — never the login screen; sign-out fallback only without a broker).
10. **5 tabs, accent colors, single-stake scoped query** — **Done.** `DashboardTab` accents; `MembersRepository.members(stakeID:)` `.eq("stake_id")` ordered unit→name.
11. **Skeleton loading + empty states** — **Done.** `MemberListSkeleton`/`CardSkeleton`/`SyncSettingsSkeleton`; `EmptyStateView` resolves the enrollment-status copy (no-role "Authorize stake sync" / revoked + stale "Re-authorize" / active / default) — all authorize actions open `ReauthSheet` (web-parity copy).

## C. Tabs
12. **Baptisms** — **Done.** Overdue ("date passed") then Scheduled date timeline; combined ↔ per-unit toggle; per-unit cards show the `MissionaryStrip` (name chips → tap reveals phone/email). (`BaptismsView.swift`)
13. **Golden Hour** — **Done.** New Members/Being Taught segmented; eligible-only completion (now a horizontal strip of % tiles, tap → who's missing); WML/EQ/RS glass org filter (all-on, can't deselect last, Clear filters) + responsibility note; Week/Month/Year/All; member rows with milestone chips + responsibility chip; drill sheets. **2026-06-13: `LazyVStack` rows + once-per-render filter/sort (the jank fix) + consolidated controls + glass.** (`GoldenHourView.swift`)
14. **Needs** — **Done.** Per-milestone category chips (color + outstanding count) → eligible-missing list; per-unit colored chips; same org filter; baptism-date↕ sort. (`NeedsView.swift`)
15. **KPIs** — **Done.** **Swift Charts** line cards (Investigators-at-Sacrament, New-Members-at-Sacrament, New-Friends-being-taught), current vs previous overlay, delta badges, big prior/latest stats; Month/Year/All + range pill + Compare toggle; Overview stat grid (Being taught now, Lessons w/ member present, New members tracked, Golden Hour %); Golden-Hour-by-unit ranked bars; tap a point/stat → drill sheet (by unit / by date). Bucketing/series math ported exactly in `Kpis.swift` from `dashboard_common.dart` + `kpis_view.dart`. (`KPIsView.swift`)
16. **Table** — **Done.** Horizontally-scrolling grid of every covenant-path field, color-coded Yes/No/N-A/recommend/gender; 3-state per-column sort; per-column value-picker filter (`ColumnFilterSheet`); "N members (filtered)" + clear-filters; row → detail. **2026-06-13: `LazyVStack` rows + pinned column header.** (`TableView.swift`)

## D. Person detail
17. **Header + open in LCR** — **Done.** Photo/initials, name, unit, member-since, baptism/planned line; LCR toolbar link.
18. **Milestone chips (next step)** — **Done.** `GoldenHourChips(labeled:, highlightNext:)`.
19. **Sections from `details`** — **Done.** Sacrament dots (+View all, missed count), Friends (in-stake heading / "names temporarily unavailable"), Priesthood, Calling (alert-red when none), Ministering Assignment, Ministering Brothers & Sisters (names), Temple, Principles Taught (member-present marker), Self-Reliance, Flags; flat fallback for pre-`details` rows. (`DetailSections.swift`, `PersonDetailView.swift`)
20. **Notes/comments** — **Done.** `CommentsSection` reads `member_comments` (RLS-scoped) + inserts a note (author email + timestamp). (`SupabaseGateway.swift`, `Comment.swift`)

## E. Actions, sheets, secondary screens
21. **Sync settings** — **Done.** Stake/last-synced/members/credential status·provider·enrolled·coverage; Sync my stake now; Revoke; Schedule section (ET hour + Pause/Resume, `/auth/schedule`); Google Drive section (connect/disconnect, sheet link, last refreshed, needs-reconnect, `/auth/google/*`). Provider-gated. (`SyncSettingsSheet.swift`)
22. **Generate report (+email)** — **Done.** Broker `/report` totals + most-needed steps + outstanding-by-member; "Email to me" (`/report/email`). (`ReportSheet.swift`)
23. **Invite a power user** — **Done.** List (grouped by email) + invite (rpc `invite_power_user`, optional unit scope) + revoke (rpc `revoke_power_user`). (`InviteView.swift`)
24. **Settings** — **Done.** Appearance (theme cycle); Security (Add a passkey [Recommended]; App-lock toggle); Support (Contact/Feedback); About & privacy (disclaimer); Account (signed in as <email>; Sign out). (`SettingsView.swift`)
25. **Contact support / Send feedback / passkey upsell** — **Done.** Contact (`/contact`) + Feedback (`/feedback` → GitHub issue) sheets; one-time post-login passkey-upsell toast (where supported). (`SupportSheets.swift`, `DashboardView.maybeSuggestPasskey`)
26. **Admin · Ops console** — **Done.** Independent panels: system health, data freshness, maintenance dispatch, tools/links, diagnostics (endpoint perf + failed units), enrolled stakes (per-stake state chip incl. "Stale · needs re-auth" + last-error line + the authorization-cadence line "authorized <ago> · self-renewing | manual re-auth needed when session expires · N re-auths/30d" from `self_renewing`/`reauths_30d`; confirm-gated per-stake Sync now / Revoke / Wipe data / Remove, mirrors web), GitHub Actions runs (+ re-run) + changelog, admins (list + invite + revoke). Broker-gated; each panel loads on its own. (`AdminView.swift`, `AdminStore.swift`)

## F. Cross-cutting
27. **Error reporting → /log** — **Done.** `ErrorReporter` (broker `/log`, type + truncated message + surface, no PII) + `NSSetUncaughtExceptionHandler`; explicit `report(_:where:)` for caught async errors. Sentry parity is NICE-TO-HAVE → not added (per spec). (`ErrorReporter.swift`, `BrokerService.log`)
28. **No secrets in code; build config** — **Done.** SUPABASE_URL/ANON_KEY/BROKER_URL/PASSKEY_RP_ID via Info.plist ← xcconfig/build settings, all empty defaults. (`AppConfig.swift`, `project.yml`, `Config.xcconfig.example`)
29. **Selectable text** — **Done.** iOS text is selectable by default in detail/labels; the Table/Form fields behave natively.

## Build contract
- **XcodeGen** `project.yml` defines app target **`CovenantPath`** (bundle id `org.membercovenantpath.viewer`, iOS 17) + a shared `CovenantPath` scheme. The target compiles **`Sources/CovenantPathKit/**` + `App/**` directly** and links **supabase-swift** (`Supabase` + `Auth`). Views compile **for iOS** (behind `#if canImport(UIKit)`, true on iOS). The root `Package.swift` is used only by `swift test`. CI: `xcodegen generate` → `xcodebuild -scheme CovenantPath -destination 'generic/platform=iOS' -skipPackagePluginValidation CODE_SIGNING_ALLOWED=NO build`.
- **Unit tests** (`swift test`, macOS): `LogicTests`, `DecodingTests`, `KpisTests` cover the pure logic (dates, milestones, org buckets, KPI bucketing/series, freshness). UIKit Views + `PasskeyService` are excluded on macOS by their canImport guards.

## Summary
**Done: 28 / 29.** **Partial: 1** — item 3 *Passkey* (full native ASAuthorization flow implemented but gated/disabled-with-note until a signed build provides `PASSKEY_RP_ID` + associated-domains; this is the spec's explicitly-allowed partial). No Stubs.

## Addendum (2026-06-13): Liquid-Glass + performance pass (iOS-only UI)
A focused redesign of the iOS look + scroll performance — **no shared logic changed**, so web/Android
parity is unaffected (this is platform-specific UI, intentionally iOS-only).
- **Liquid Glass** (`Shared/Glass.swift`): real iOS 26 `.glassEffect` / `GlassEffectContainer` /
  scroll-minimizing glass tab bar, double-gated by `#if compiler(>=6.2)` + `if #available(iOS 26.0, *)`
  with a frosted-material fallback — deployment target stays **17.0**, CI compiles on any Xcode. Adopted
  by every `SectionCard`, the dashboard banners/toast, the filter chips, and a tab-tinted backdrop.
- **Performance**: `MemberList` (Golden Hour + Needs) and the Table grid render in `LazyVStack` instead
  of building every row up front (the Golden-Hour jank fix); avatars load through the cached
  `CachedAvatarImage` (no re-download/re-decode/flash on recycle). Filter/sort computed once per render.
- **Face ID**: app-lock is now opt-in / OFF by default; the launch gate no longer requires or flashes it.
- **CI**: `build-native-ios.yml` selects the newest installed Xcode (iOS 26 SDK → real glass) with a
  safe fallback to the default Xcode, so the build is green whether or not a 26.x toolchain is present.
- **Review-driven follow-ups (same day, 2 independent audit agents — perf + style):** removed the
  per-card drop shadow (scroll cost); lifted the long Golden Hour lists out of their glass card (no tall
  translucent backing behind hundreds of rows); hoisted `BaptismsView.items`; capped the avatar cache
  (`totalCostLimit`); and unified the glass language on the surfaces left flat — **skeletons**,
  **person-detail header**, **Needs** category/ward chips, and the **Table** pinned header (now a frosted
  bar, not an opaque accent slab). Avoided glass-on-glass (unit-count chips stay solid inside their card).
- **Verification:** compiles via the iOS CI build; **pending a device/AVD pass** for the glass look on
  iOS 26 and the pinned Table header behavior.

## Addendum (2026-06-10): notes on list rows
- **List-row note lines** — newest leader note (+N) under each person in Golden Hour / Needs / by-date lists (`MemberRow` + `NoteLine`), the Baptisms timeline rows, and a note marker in the Table's Member cell. Data: one bulk RLS-scoped `member_comments` fetch per stake load (`SupabaseGateway.noteRows` -> `NotesIndex.build`, mirrored unit tests in `LogicTests`); posting a note on detail refreshes the index (`DashboardStore.reloadNotes`). **Pending CI build + simulator verification.**
