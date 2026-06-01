# Cross-surface UI rule — READ BEFORE CHANGING ANY UI

> **Every user-facing change MUST be made in ALL THREE client codebases and kept in parity.
> A change that lands in only one surface is INCOMPLETE and must not be merged.**

The product ships as **three independent client codebases** that must look and behave the
same. CLAUDE.md's "one Flutter codebase" is true *within Flutter* — but there are also two
hand-written native ports that must mirror it feature-for-feature.

| Surface | Path | Stack | Ships to |
|---|---|---|---|
| **Flutter** (reference impl) | `apps/viewer/lib/` | Dart / Flutter | web · iOS · macOS · Android |
| **Native iOS** | `native/ios/` | Swift / SwiftUI (`CovenantPathKit`) | iOS |
| **Native Android** | `native/android/` | Kotlin / Jetpack Compose | Android |

So a UI change is **three edits**: `apps/viewer/lib` → `native/ios` → `native/android`.

## What counts as "UI-facing"

Anything a user can see or feel: copy/labels, screens, navigation, filters, empty/error
states, banners, colors/spacing, login/gate behavior, **and what data is shown or hidden**.
A backend-only change is exempt — but if it changes what the client renders (a new field, a
new filter rule, a new stat), the client change is still three edits.

## Parity map (where the same concept lives)

| Concept | Flutter | Native iOS | Native Android |
|---|---|---|---|
| Disclaimer / privacy copy | `lib/disclaimer.dart` | `Sources/CovenantPathKit/Logic/Disclaimer.swift` | `ui/components/Dialogs.kt`, `ui/screens/LoginScreen.kt` |
| Login / auth gate | `lib/login_page.dart`, `lib/views/dashboard_shell.dart` | `Views/LoginView.swift`, `…/SessionStore.swift` | `ui/screens/LoginScreen.kt`, `viewmodel/AuthViewModel.kt`, `ui/App.kt` |
| No-access / empty states | `lib/views/dashboard_shell.dart` | `Views/EmptyStateView.swift` | `ui/screens/StatusScreens.kt` (EnrollmentEmptyState) |
| Syncing banner | dashboard (`lib/dashboard_page.dart`) | `SyncingBanner` | `ui/components/Banners.kt`, `viewmodel/DashboardViewModel.kt` |
| Milestones / Golden Hour | `lib/golden_hour.dart` | `Logic/…` | `logic/Milestones.kt`, `logic/OrgBucket.kt`, `ui/screens/tabs/GoldenHourScreen.kt` |
| Tables / master lists | `lib/views/table_view.dart` | port | `ui/screens/tabs/TableScreen.kt` |
| Baptisms / Being-taught | `lib/views/baptisms_view.dart` | port | `ui/screens/tabs/BaptismsScreen.kt` |
| Needs | `lib/views/needs_view.dart` | port | `ui/screens/tabs/NeedsScreen.kt` |
| KPIs / stats | `lib/views/kpis_view.dart` | port | `logic/Kpis.kt`, `ui/screens/tabs/KpisScreen.kt` |
| Member model / Supabase select | `lib/dashboard_page.dart` (`_columns`) | model | `model/Member.kt`, `data/MembersRepository.kt` |
| Bottom nav / scaffold | `lib/views/dashboard_shell.dart` | scaffold | `ui/screens/DashboardScaffold.kt` |
| Settings / About | `lib/settings_page.dart` | `Views/SettingsView.swift` | `ui/screens/SettingsScreen.kt` |

Authoritative parity trackers — **update these when you add/change a feature**:
`native/PARITY.md`, `native/SPEC.md`, `native/ios/PARITY_STATUS.md`,
`native/android/PARITY_STATUS.md`.

## Verify each surface

- **Flutter**: `D:/dev/flutter/bin/flutter analyze` (must be "No issues found") + `flutter build web`.
- **iOS**: SwiftUI; compiles via the CI workflow (`.github/workflows/*ios*`).
- **Android**: APK builds via CI (Supabase/broker config injected as **secrets, not vars**);
  verify on the **Pixel_10 AVD** by signing in with a Gmail OTP. See `native/android/README.md`.

## Workflow for any UI change

1. Implement in `apps/viewer/lib` first (reference).
2. Mirror in `native/ios`, then `native/android`.
3. Update the relevant `PARITY_STATUS.md` rows.
4. Run the per-surface checks above.
5. A commit/PR that touches only one surface for a shared UI change is **incomplete**.
