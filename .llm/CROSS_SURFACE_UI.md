# Cross-surface UI rule — READ BEFORE CHANGING ANY UI

> **Every user-facing change MUST be made in ALL THREE client codebases and kept in parity.
> A change that lands in only one surface is INCOMPLETE and must not be merged.**

The product ships as **three independent client codebases** that must look and behave the
same. (The old single Flutter app, `apps/viewer`, was deprecated 2026-06-08 and **deleted
2026-06-13** — there is no Flutter surface anymore. The React web app is now the reference
implementation; the two hand-written native ports mirror it feature-for-feature.)

| Surface | Path | Stack | Ships to |
|---|---|---|---|
| **React web** (reference impl) | `apps/web/` | Vite + React + TypeScript | web |
| **Native iOS** | `native/ios/` | Swift / SwiftUI (`CovenantPathKit`) | iOS |
| **Native Android** | `native/android/` | Kotlin / Jetpack Compose | Android |

So a UI change is **three edits**: `apps/web` → `native/ios` → `native/android`. All three read
Supabase + the broker the same way (CORS-free; RLS is the access gate).

## What counts as "UI-facing"

Anything a user can see or feel: copy/labels, screens, navigation, filters, empty/error
states, banners, colors/spacing, login/gate behavior, **and what data is shown or hidden**.
A backend-only change is exempt — but if it changes what the client renders (a new field, a
new filter rule, a new stat), the client change is still three edits.

## Parity map (where the same concept lives)

| Concept | React web | Native iOS | Native Android |
|---|---|---|---|
| Disclaimer / privacy copy | `src/lib/disclaimer.ts`, `src/components/Disclaimer.tsx` | `Sources/CovenantPathKit/Logic/Disclaimer.swift` | `ui/components/Dialogs.kt`, `ui/screens/LoginScreen.kt` |
| Login / auth gate | `src/pages/LoginPage.tsx`, `src/hooks/useAuth`, `src/router.tsx` | `Views/LoginView.swift`, `…/SessionStore.swift` | `ui/screens/LoginScreen.kt`, `viewmodel/AuthViewModel.kt`, `ui/App.kt` |
| No-access / empty states | `src/components/EmptyState.tsx` | `Views/EmptyStateView.swift` | `ui/screens/StatusScreens.kt` (EnrollmentEmptyState) |
| Syncing banner | `src/components/dashboard.tsx` / `src/pages/DashboardShell.tsx` | `SyncingBanner` | `ui/components/Banners.kt`, `viewmodel/DashboardViewModel.kt` |
| Milestones / Golden Hour | `src/logic/milestones.ts`, `src/pages/tabs/GoldenHourTab.tsx` | `Logic/Milestones.swift`, `Logic/OrgBucket.swift` | `logic/Milestones.kt`, `logic/OrgBucket.kt`, `ui/screens/tabs/GoldenHourScreen.kt` |
| Tables / master lists | `src/pages/tabs/TableTab.tsx` | port | `ui/screens/tabs/TableScreen.kt` |
| Baptisms / Being-taught | `src/pages/tabs/BaptismsTab.tsx` | port | `ui/screens/tabs/BaptismsScreen.kt` |
| Needs | `src/pages/tabs/NeedsTab.tsx` | port | `ui/screens/tabs/NeedsScreen.kt` |
| KPIs / stats | `src/logic/kpis.ts`, `src/pages/tabs/KpisTab.tsx` | `Logic/Kpis.swift`, `Views/Tabs/KPIsView.swift` | `logic/Kpis.kt`, `ui/screens/tabs/KpisScreen.kt` |
| Member model / Supabase select | `src/lib/member.ts` | `Models/Member.swift` | `model/Member.kt`, `data/MembersRepository.kt` |
| Bottom nav / scaffold | `src/pages/DashboardShell.tsx` | scaffold | `ui/screens/DashboardScaffold.kt` |
| Settings / About | `src/pages/SettingsPage.tsx` | `Views/SettingsView.swift` | `ui/screens/SettingsScreen.kt` |

Authoritative parity trackers — **update these when you add/change a feature**:
`native/PARITY.md`, `native/SPEC.md`, `native/ios/PARITY_STATUS.md`,
`native/android/PARITY_STATUS.md`.

## Verify each surface

- **React web** (reference): `cd apps/web` → `npm run typecheck` (0 errors) + `npm run lint`
  (ESLint + jsx-a11y, 0 errors) + `npm run test` (vitest) + `npm run build` (clean) +
  `npm run e2e` (Playwright). See `apps/web/README.md`.
- **iOS**: SwiftUI; compiles via the CI workflow (`build-native-ios.yml`).
- **Android**: APK builds via CI (`build-native-android.yml`; Supabase/broker config injected as
  **secrets, not vars**); verify on the **Pixel_10 AVD** by signing in with a Gmail OTP. See
  `native/android/README.md`.

## Workflow for any UI change

1. Implement in `apps/web` first (reference).
2. Mirror in `native/ios`, then `native/android`.
3. Update the relevant `PARITY_STATUS.md` rows.
4. Run the per-surface checks above.
5. A commit/PR that touches only one surface for a shared UI change is **incomplete**.
