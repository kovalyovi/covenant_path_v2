# Covenant Path — Native iOS (SwiftUI) Proof of Concept

A native iOS rebuild of the Flutter `apps/viewer`, built to compare native vs. Flutter
architecture/feel. Read-only dashboard for stake/ward leaders tracking new-member ("Golden Hour")
integration. The app **only reads Supabase**, scoped by the signed-in user's role (Row-Level
Security does all gating); it never talks to the church system directly.

> Status: written **without a Swift compiler** (no macOS/Xcode in the authoring environment). The
> code is meticulous and idiomatic, but expect to need a few small fixups in Xcode (mainly SF Symbol
> name swaps and possibly minor SDK-signature nudges). See **Compile caveats** at the bottom.

## Architecture

Everything lives in a Swift Package, `CovenantPathKit`, so the pure business logic is unit-testable
on the command line. The iOS app target is a thin shell that renders `RootView`.

```
native/ios/
  Package.swift                  SwiftPM manifest; declares supabase-swift 2.x dependency
  App/                           the iOS app target (create in Xcode — see below)
    CovenantPathApp.swift        @main App → RootView()
    Info.plist                   maps SUPABASE_URL / SUPABASE_ANON_KEY from the xcconfig
    Config.xcconfig.example      copy to Config.xcconfig (gitignored) and fill in your project
  Sources/CovenantPathKit/
    Models/                      Codable structs: Member, MemberDetails (jsonb), Stake/Missionary
    Logic/                       PURE, unit-tested ports of golden_hour.dart:
                                   DateParsing, Milestones, OrgBucket, Recency/Initials
    Services/                    AppConfig, SupabaseService, AuthService, MembersRepository
    ViewModels/                  @Observable stores: SessionStore (auth), DashboardStore (data)
    Views/                       SwiftUI; RootView, LoginView, DashboardView (TabView), tab views,
                                   PersonDetailView, Detail/ sections, Shared/ components
  Tests/CovenantPathKitTests/    XCTest for the pure logic + Codable decoding
```

**Layering** (dependencies point downward, UI is a thin shell):

- **Models** — `Member` mirrors the dashboard select columns exactly (snake_case → camelCase via
  `CodingKeys`). `MemberDetails` is a tolerant decoder for the `details` jsonb subtree (partial rows
  and mixed-type fields must still render).
- **Logic** — UI-free and `Sendable`. `Milestones.all` is the single milestone source (same order,
  labels, abbrs, eligibility + completion predicates as `golden_hour.dart`). `Org` is the single org
  ownership source (`responsible(for:)`, `info(_:)`). Colors are expressed as `UInt32` hex + SF
  Symbol names so the logic stays platform-neutral and testable; the view layer maps hex → `Color`.
- **Services** — `SupabaseService` wraps the SDK client. `AuthService` (email-OTP) and
  `MembersRepository` (RLS-scoped reads) are protocols with Supabase-backed implementations.
- **ViewModels** — `@Observable` (Observation framework). `SessionStore` drives the login/dashboard
  switch via `auth.authStateChanges`; `DashboardStore` loads the single-stake dataset and exposes the
  derived `newMembers` / `investigators` slices.
- **Views** — SwiftUI, `NavigationStack` per tab, `TabView` for the 5 tabs. State is `@State`
  (`@Observable` stores) + `@Environment`. All I/O is `async/await`.

State management is the modern **Observation framework** (`@Observable`, `@State`, `@Environment`),
not `ObservableObject`/`@Published`.

## Open / build in Xcode

You have two options. **Option A (recommended)** uses the package + an app target you create in
Xcode — clean and avoids hand-maintaining a `.xcodeproj`.

### Option A — Swift Package + a new app target

1. **Open the package**: `File → Open…` and select `native/ios/Package.swift`. Xcode resolves the
   `supabase-swift` dependency (needs network on first open; see **Dependencies**). At this point
   `swift test` / the `CovenantPathKitTests` scheme will run the pure-logic tests.
2. **Add an app target**: `File → New → Project… → iOS → App` (Interface: SwiftUI, Language: Swift,
   minimum deployment iOS 17). Save it (e.g. inside `native/ios/` as `CovenantPathApp`).
   - Delete the generated `ContentView.swift` and the generated `…App.swift`.
   - Add `App/CovenantPathApp.swift` to the target (it's the `@main` entry → `RootView()`).
3. **Link the package**: select the project → the app target → `General → Frameworks, Libraries, and
   Embedded Content → +` → `Add Other… → Add Package Dependency… → Add Local…` → choose this
   `native/ios` folder → add the **`CovenantPathKit`** library product to the app target.
   (supabase-swift comes transitively through `CovenantPathKit`.)
4. **Configuration** (see next section) — point the target at `Config.xcconfig` and use the provided
   `Info.plist` (or copy its two `SUPABASE_*` keys into the target's generated Info settings).
5. Select an iOS 17+ simulator and **Run**.

### Option B — hand-written project

Not provided. A `.xcodeproj`/`.pbxproj` is fragile to author by hand without a compiler; Option A is
the safer, cleaner deliverable. (The package alone already builds the entire app module.)

## Configuration (SUPABASE_URL / SUPABASE_ANON_KEY)

Secrets are **never hardcoded**. The two values are read at runtime by `AppConfig` from the app
bundle's Info.plist keys `SUPABASE_URL` / `SUPABASE_ANON_KEY`, which are populated at build time from
an **xcconfig** (kept out of source control).

1. Copy `App/Config.xcconfig.example` → `App/Config.xcconfig` (already gitignored).
2. Fill in your values:
   - `SUPABASE_URL` — note xcconfig treats `//` as a comment, so write the scheme escaped:
     `SUPABASE_URL = https:/$()/YOUR-REF.supabase.co`
   - `SUPABASE_ANON_KEY = sb_publishable_…` (the anon/publishable key is **safe** on clients — RLS
     gates everything — but we still keep it untracked).
3. In Xcode: `Project → Info → Configurations`, set Debug and Release for the app target to use
   `Config.xcconfig`.
4. Ensure the target's Info.plist contains the two `SUPABASE_*` keys mapped to `$(SUPABASE_URL)` /
   `$(SUPABASE_ANON_KEY)` (the bundled `App/Info.plist` already does — point the target at it via
   `Build Settings → Packaging → Info.plist File`, or copy the two keys into the generated plist).

If the config is empty/missing, the app shows a friendly "Configuration needed" screen instead of
crashing (mirrors the Flutter `_ConfigError`).

## Dependencies

- **supabase-swift** `from: "2.20.0"` (the official SDK; 2.x major line). Declared in `Package.swift`.
  `import Supabase` re-exports the `Auth` and `PostgREST` sub-modules we use (`@_exported import`),
  so we get `SupabaseClient`, `Session`, `AuthChangeEvent`, `EmailOTPType`, and the Postgrest query
  builders from the one import.
- I could not run `swift build`/`swift test` here (no Swift toolchain), so `Package.resolved` is not
  committed — Xcode will resolve it on first open. If the pinned minor is unavailable, bump it.

## What's implemented vs. stubbed

**Implemented (faithful ports):**

- **Email-OTP login** — send code (`signInWithOTP(email:)`) → verify (`verifyOTP(email:token:type:
  .email)`). Two-step UI with busy/error handling.
- **Data layer** — typed `Member` model + `MembersRepository` selecting the exact dashboard column
  list, scoped to one stake (`.eq("stake_id", …).order("unit_name").order("name")`). Stakes loaded
  freshest-first; multi-stake users get an in-app switcher.
- **Milestone / org / date logic** — ported **exactly** from `golden_hour.dart`: the 6 milestones
  with their eligibility gates (by-year "turns ≥N", age-now ≥N, member-≥1yr, male) and eligible-only
  completion math; `OrgBucket` ownership (`<12mo` WML / `≥12mo` EQ·RS via `days/30.44` floored); date
  parsing for ISO / `6 Feb 2026` / `M/D/YYYY` / sentinels; `monthsDaysAgo`, initials.
- **Baptisms** — investigators by planned `baptism_goal_date` as a date timeline: overdue ("date
  passed") block first, then "Scheduled", grouped by date with a month/day rail.
- **Golden Hour** — segmented New Members / Being Taught; New Members has the org filter (WML/EQ/RS,
  all-on by default, can't deselect the last, Clear filters), the Week/Month/Year/All recency window
  with a range pill, the per-milestone completion summary (% eligible-only, tap → "still need" sheet),
  and the member list with milestone chips (next-step highlighted).
- **Needs** — per-milestone category selector with outstanding counts, the same org filter, the
  per-unit colored breakdown, and the eligible-missing list sorted by baptism date then unit.
- **Person Detail** — header (photo/initials, name, unit, baptism line), labeled milestone chips,
  then sections from `details`: sacrament dots (recent 6 + "View all"), Friends (names), Priesthood,
  Calling, Ministering Assignment, Ministering Brothers/Sisters (names), Temple, Principles Taught
  (taught/member-present dots), Self-Reliance toggles, Flags — with the **"names temporarily
  unavailable"** fallback when a Yes flag has no names, and the flat-field fallback when `details` is
  null. "Open in LCR" toolbar link.
- **Table** — a sortable list (the spec allows "a basic sortable list") of baptized members with the
  covenant-path fields as color-coded Yes(green)/No(red)/N/A(grey)/recommend cells, plus a sort menu.
- **Shared components** — `GoldenHourChips`, `OrgFilterBar`, `MemberRow`, avatars, `SectionCard`,
  `FlowLayout` (wrapping chips), loading skeleton with shimmer.
- **Unit tests** — date parsing, eligibility, org buckets, completion math, the org-filter
  last-selection guard, recency windows, initials, and Codable column mapping / tolerant `details`
  decoding.

**Stubbed / out of scope (per the spec's PoC non-goals):**

- **KPIs** — a labeled stub: real at-a-glance counts + per-unit completion bars, but **not** the
  Flutter time-series line charts (Month/Year/All) with drill-downs. Clearly labeled in-app.
- **Church-account broker login, passkeys, email-relay backup** — not implemented (email-OTP only).
- **Admin/ops console, report generation, Google Drive, sync settings, push, in-app schedule,
  comments/notes** — not implemented.
- **Photos pipeline** — we just render `photo_url` via `AsyncImage` if present, else initials.

## Compile caveats (honest)

This was written **without a compiler**, so:

- **SF Symbols**: a few symbol names were chosen to echo the Flutter Material icons (e.g.
  `hands.sparkles`, `person.text.rectangle`, `rosette`, `medal`, `timeline.selection`). If any name
  isn't available on your iOS 17 SDK, Xcode renders a blank/placeholder — swap it for a valid symbol
  (they're isolated in `MilestoneStyle`/`OrgInfo`/`DashboardTab` + the detail sections).
- **SDK signatures**: verified against the current `supabase-swift` main (`signInWithOTP`,
  `verifyOTP(…type: .email)`, `authStateChanges` as `AsyncStream<(event:session:)>`,
  `from().select().eq(_,value:).order().execute().value`, default decoder does **not** snake-case so
  the explicit `CodingKeys` are correct). If you pin a different 2.x minor with a renamed symbol,
  adjust `AuthService`/`MembersRepository`.
- **Platform guards**: the SwiftUI `Views/` are wrapped in `#if canImport(UIKit)` so the package's
  pure logic + Codable tests build/run on macOS via `swift test`, while the full UI compiles for iOS.
- **Store re-creation**: `DashboardStore` is created in `ConfiguredRoot.body`; SwiftUI keeps the
  first `@State` instance (stable view identity), so the extra allocation is harmless. If you prefer,
  hoist the stores into a single owner.

Run the logic tests (on a Mac) with the `CovenantPathKitTests` scheme, or `swift test` from
`native/ios/`.
