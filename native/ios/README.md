# Covenant Path — Native iOS (SwiftUI)

A native iOS rebuild of the Flutter `apps/viewer`, at **100% feature parity** (see
`PARITY_STATUS.md`). Read-only dashboard for stake/ward leaders tracking new-member ("Golden Hour")
integration. The app **only reads Supabase**, scoped by the signed-in user's role (Row-Level
Security does all gating); it talks to the **auth broker** for Church login / sync ops / reports /
admin, and never touches the church system directly.

Swift + SwiftUI, iOS 17+, the Observation framework (`@Observable`), async/await, `NavigationStack` /
`TabView` / `.sheet` / `Form`, **Swift Charts** (KPIs), `AuthenticationServices` (passkeys),
`LocalAuthentication` (app lock). Supabase via **supabase-swift** (SPM).

> Authored without a Swift compiler in this environment — written to be meticulous and build under
> the CI `xcodebuild` (see **Compile caveats**). The CI workflow `build-native-ios.yml` runs
> `xcodegen generate` then `xcodebuild` on a macOS runner.

## Architecture

The code is organized as `CovenantPathKit` (Models / Logic / Services / ViewModels / Views). It is
consumed two ways:

- **App build (XcodeGen → xcodebuild):** the `CovenantPath` app target compiles **all of
  `Sources/CovenantPathKit/**` + the `App/` `@main` shell directly** and links **supabase-swift**
  (the remote SPM package). The Xcode project is generated from `project.yml` — no `.xcodeproj` is
  committed. (Because the sources are in the app target's own module, `App/CovenantPathApp.swift` has
  no `import CovenantPathKit`.)
- **Logic tests (`swift test`):** the root `Package.swift` builds the same `Sources/` as a
  `CovenantPathKit` library + `Tests/` on macOS, so the pure logic is unit-testable on the command
  line. The xcodeproj does **not** reference this package (keeping the build free of any root-local-
  package resolution quirks).

```
native/ios/
  project.yml                    XcodeGen spec → app target `CovenantPath` + local package dep
  Package.swift                  SwiftPM manifest (CovenantPathKit library + supabase-swift)
  App/
    CovenantPathApp.swift        @main App → RootView()
    Info.plist                   SUPABASE_URL/ANON_KEY/BROKER_URL/PASSKEY_RP_ID from build settings
    Config.xcconfig.example      copy to Config.xcconfig (gitignored) to inject real values locally
  Sources/CovenantPathKit/
    Models/      Member, MemberDetails (jsonb), Stake/Missionary, Comment, Misc (units/invites/admins)
    Logic/       PURE, unit-tested: DateParsing, Milestones, OrgBucket, Recency/Initials,
                 Kpis (series/bucketing), Freshness (ago/staleness), Disclaimer
    Services/    AppConfig, SupabaseService, AuthService, MembersRepository, SupabaseGateway,
                 BrokerService (broker+admin+/log), AppServices (graph), AppPrefs/ThemeController,
                 BiometricService, PasskeyService, ErrorReporter
    ViewModels/  @Observable: SessionStore (3-mode auth), DashboardStore (shell+data), AdminStore
    Views/       RootView, LoginView, BiometricGateView, DashboardView, Tabs/, Detail/, Sheets/,
                 SettingsView, InviteView, AdminView, Shared/
  Tests/CovenantPathKitTests/    XCTest: logic + Codable + KPI/freshness math
```

State management is the modern **Observation framework** (`@Observable`, `@State`, `@Environment`),
not `ObservableObject`/`@Published`. The pure `Logic/` layer is `Sendable` and UI-free (colors are
`UInt32` hex + SF Symbol names mapped to SwiftUI in the views), so it builds + tests on macOS.

## Build / run

### CI (the build contract)

```sh
cd native/ios
brew install xcodegen
xcodegen generate
xcodebuild -scheme CovenantPath -destination 'generic/platform=iOS' \
  -skipPackagePluginValidation CODE_SIGNING_ALLOWED=NO build
swift test            # pure-logic tests on macOS (UIKit views excluded by canImport guards)
```

`xcodegen generate` reads `project.yml` and produces `CovenantPath.xcodeproj` (gitignored): one
`CovenantPath` app target compiling `Sources/CovenantPathKit/**` + `App/**` and linking the
`Supabase` + `Auth` products of supabase-swift. The app builds **unsigned** for a generic iOS
device; with an empty config it shows the "Configuration needed" screen (fine for a compile check).

### Local Xcode

`xcodegen generate`, then open `CovenantPath.xcodeproj` and Run on an iOS 17+ simulator. (Or open
`Package.swift` to run `swift test` on the pure logic.)

## Configuration (no secrets in code)

Four build-time values, read at runtime by `AppConfig` from the bundle's Info.plist keys
(populated from build settings / the xcconfig), all defaulting **empty**:

| Key | Purpose |
|---|---|
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | the data layer (anon key is safe on clients — RLS gates everything) |
| `BROKER_URL` | the auth broker (empty → only Email-code login; broker features hide) |
| `PASSKEY_RP_ID` | native passkey relying-party id (empty → passkey button disabled with a note) |

To inject real values locally: copy `App/Config.xcconfig.example` → `App/Config.xcconfig`
(gitignored), fill it in, and either add `configFiles: { Debug/Release: App/Config.xcconfig }` to the
`CovenantPath` target in `project.yml` (CI keeps it out so a missing file never fails the build) or
pass them as build settings to `xcodebuild`. xcconfig treats `//` as a comment, so escape URL
schemes: `SUPABASE_URL = https:/$()/your-ref.supabase.co`.

## What's implemented

**Everything in `PARITY.md` (1–29) — see `PARITY_STATUS.md` for the item-by-item map.** Highlights:

- **3-mode login** — Church account (username/password → MFA factor pick → code, via the broker) ·
  Email code (Supabase OTP, with a broker-relay fallback) · Passkey (native ASAuthorization WebAuthn
  against the broker — see the one **Partial** below). Disclaimer + cold-start status + error lines.
- **Biometric app-lock** (LocalAuthentication), **dark mode** (persisted, Settings toggle).
- **Dashboard shell** — stake switcher, freshness chip (→ Sync now), Refresh, overflow menu, syncing
  + stale-credential banners, skeletons, enrollment-aware empty states.
- **5 tabs** — Baptisms (overdue/scheduled timeline + per-unit + missionary strip), Golden Hour
  (completion card + org filter + recency window + drills), Needs (category chips + per-unit + org
  filter), **KPIs (Swift Charts** line cards with compare overlay + Overview grid + by-unit bars +
  drills), Table (sortable + per-column value filter, color-coded).
- **Person detail** — header + LCR link, milestone chips, all `details` sections, and **notes**
  (read/add via `member_comments`).
- **Sheets / screens** — Sync settings (status + schedule + Google Drive), Generate report (+email),
  Invite power users (rpc), Settings, Contact / Feedback, **Admin · Ops console** (broker `/admin/*`).
- **Error reporting** to broker `/log` (type + truncated message + surface; no PII).

## Compile caveats (honest)

Authored without a compiler, so:

- **Passkey is the one documented Partial.** The full native `ASAuthorization` WebAuthn flow is
  implemented (`PasskeyService`), but `available` is gated behind `PASSKEY_RP_ID` because platform
  passkeys need an **associated-domains entitlement** that an unsigned CI build can't provide. Unset
  → the button shows disabled with a "use email code on this device" note. Set + entitlement → it
  runs end-to-end.
- **Swift Charts** (`KPIsView`) uses `Chart`/`LineMark`/`AreaMark`/`PointMark`, `chartOverlay`
  tap-to-drill (`proxy.value(atX:)` + `plotAreaFrame`), and `AxisMarks`. Verified against the iOS 17
  API; `plotAreaFrame` is deprecated-but-present on iOS 17 (warning, not error).
- **SF Symbols** were chosen to exist on the iOS 17 SDK; symbol names are strings so a wrong one only
  renders blank at runtime (never a build error). Uncertain ones were swapped for safe equivalents.
- **supabase-swift API** verified against 2.x: `signInWithOTP`, `verifyOTP(…type: .email)`,
  `setSession(accessToken:refreshToken:)`, `auth.session`, `authStateChanges`,
  `from().select().eq(_,value:).order().execute().value`, `rpc(_:)` / `rpc(_:params:)`, `insert`.
- **macOS `swift test`** compiles the package minus the UIKit-gated Views + `PasskeyService` (their
  `canImport` guards), so the pure logic tests run without a simulator.
