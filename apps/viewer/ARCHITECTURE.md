# Viewer app — architecture & contribution rules

One Flutter codebase → **web, iOS, macOS, Android**. It reads **Supabase only** (never
LCR), so every platform behaves the same and the web build never hits CORS. Access is
enforced by Postgres RLS — the app does no filtering. Church-account sign-in goes through
the **auth broker** (browsers can't call Okta directly).

## Files

| File | Responsibility |
|---|---|
| `lib/main.dart` | Supabase init (`--dart-define` config) + `AuthGate` (login ↔ dashboard) |
| `lib/config.dart` | `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `BROKER_URL` from `--dart-define` |
| `lib/login_page.dart` | Dual login: **Church account** (broker, MFA-aware) + **email code**; browser autofill (AutofillGroup) |
| `lib/broker_client.dart` | Calls the auth broker (`/auth/*`); cold-start retry/"waking up" UX |
| `lib/dashboard_page.dart` | Reads `members`; **responsive** 4-tab shell (On Date / Golden Hour / KPIs / Table) |
| `lib/golden_hour.dart` | **Shared**: `milestones`, `GoldenHourChips`, `InitialsAvatar`, `PhotoAvatar`, `SectionCard`, `MaxWidthBody`, `ScreenTier`/`tierFor` |
| `lib/person_detail_page.dart` | LCR-style member detail (cards: sacrament, friends, lessons, ministering, …) from `members.details` JSON |
| `lib/invite_page.dart` | Power-user invite/revoke (`invite_power_user` RPC) |
| `lib/admin_page.dart` | Admin/ops console (gated by `is_admin` RPC) — health, freshness, Actions, diagnostics, maintenance flows, admins |
| `lib/admin_client.dart` | Calls the broker `/admin/*` endpoints with the Supabase access token |

Generated platform folders (`android/ ios/ macos/ web/ …`) are **gitignored** — regenerate
with `flutter create .`. The one exception is `web/_headers` (force-tracked) which sets
no-cache on the service worker so deploys aren't served stale. Tracked: `lib/`, `pubspec.yaml`,
`web/_headers`, `test/`, `*.md`, `.metadata`, `analysis_options.yaml`.

## Responsive design (3 breakpoints)

`tierFor(width)` → `mobile (<600)` · `tablet (600–1100)` · `desktop (≥1100)`.
- **mobile**: bottom `NavigationBar`, single-column cards.
- **tablet/desktop**: side `NavigationRail` (extended on desktop) + multi-column card layout
  (`_Columns`, 1/2/3 cols) inside a width-capped, centered `_Page`. The browser feels like a
  real app, not a stretched phone. No full-width bottom bar on wide screens.

## The four tabs

- **On Date** — members with a baptismal date. *By unit*: a card per unit (unit = title,
  members = rows). *By date*: a flat list sorted by date with the unit shown as right-side
  metadata. Long dates via `intl`.
- **Golden Hour** — Week/Month/Year/All recency filter + completion summary; same by-unit /
  by-date layouts, each member row carries `GoldenHourChips`. Milestones = *integration only*
  (Friends, Calling, Ministering ×2, Aaronic, Melchizedek) — **baptism is intentionally not a
  milestone**.
- **KPIs** — iOS-style line-chart cards (`fl_chart`): "New Members at Sacrament" weekly trend
  computed from `members.details.sacrament`, plus stake metrics from `stakes.kpis`
  (sacrament/recommends/ministering) and an overview stat card.
- **Table** — every covenant-path field, color-coded like the master spreadsheet
  (Yes=green / No=red / N/A=grey; recommend Active=green·Expired=amber) with a styled header.

## Rules (keep all platforms consistent)

1. **Reuse shared widgets** from `golden_hour.dart`. Milestones are defined *once* there
   (`milestones`) — dashboard, detail, completion all read it. To change a milestone edit only
   that list (and `backend/mailer._DIGEST_MILESTONES` if digests should match).
2. **No LCR / no secrets in the client.** Only the Supabase URL + publishable anon key (RLS
   gates everything) + the broker URL. Data comes from `supabase.from(...)`; the broker holds
   the service-role/GitHub secrets server-side.
3. **No platform-specific code** in `lib/` unless guarded; the app must build for web.
4. **After any change**: `flutter analyze` (→ "No issues found"), `flutter test`, then
   `flutter build web`. All must pass before commit.

## Adding a new field to a view

1. Ensure it's a column on `members` (backend migration) and populated by the sync.
2. Add the column name to `_columns` in `dashboard_page.dart`.
3. Show it: add to `_SpreadsheetView._cols` and/or the detail page; structured/rich data lives
   in `members.details` (JSON) and is rendered by `person_detail_page.dart`.
4. If it's an integration milestone, add a `Milestone(...)` in `golden_hour.dart`.

## Run / build

```bash
flutter create .            # once: regenerate platform folders (keep web/_headers)
flutter run -d chrome \
  --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=... --dart-define=BROKER_URL=...

flutter build web --release  --dart-define=... # → build/web  (deploy: docs/DEPLOYMENT.md)
flutter build apk --release  --dart-define=... # → build/app/outputs/flutter-apk/app-release.apk
```

Church login goes through the broker; email-code login needs `{{ .Token }}` enabled in
Supabase Auth → Email Templates.
