# Viewer app — architecture & contribution rules

One Flutter codebase → **web, iOS, macOS, Android**. It reads **Supabase only** (never
LCR), so every platform behaves the same and the web build never hits CORS. Access is
enforced by Postgres RLS — the app does no filtering.

## Files

| File | Responsibility |
|---|---|
| `lib/main.dart` | Supabase init (`--dart-define` config) + `AuthGate` (login ↔ dashboard) |
| `lib/config.dart` | `SUPABASE_URL` / `SUPABASE_ANON_KEY` from `--dart-define` |
| `lib/login_page.dart` | Email one-time-code sign-in (cross-platform, no deep links) |
| `lib/dashboard_page.dart` | Reads `members`; Golden Hour view + Spreadsheet view |
| `lib/golden_hour.dart` | **Shared**: `milestones`, `GoldenHourChips`, `InitialsAvatar` |
| `lib/person_detail_page.dart` | All fields for one member |
| `lib/invite_page.dart` | Power-user invite/revoke (`invite_power_user` RPC) |

## Rules (keep all platforms consistent)

1. **Reuse shared widgets** from `golden_hour.dart`. Milestones are defined *once* there
   (`milestones` list) — the dashboard, detail page, and completion stats all read it.
   To add/change a milestone, edit only that list (and `backend/mailer._DIGEST_MILESTONES`
   if email digests should match).
2. **No LCR / no secrets in the client.** Only the Supabase URL + publishable anon key
   (safe — RLS gates everything). All data comes from `supabase.from('members')` etc.
3. **No platform-specific code** in `lib/` unless guarded; the app must build for web.
4. **After any change**: `D:/dev/flutter/bin/flutter analyze` (→ "No issues found")
   then `flutter build web`. Both must pass before commit.
5. Generated platform folders (`android/ ios/ macos/ web/ ...`) are **gitignored** —
   regenerate with `flutter create .`. Only `lib/`, `pubspec.yaml`, `*.md`, `.metadata`,
   `analysis_options.yaml` are tracked.

## Adding a new field to a view

1. Ensure it's a column on `members` (backend migration) and populated by the sync.
2. Add the column name to `_columns` in `dashboard_page.dart`.
3. Show it: add to `_SpreadsheetView._cols` and/or `PersonDetailPage._fields`.
4. If it's an integration milestone, add a `Milestone(...)` in `golden_hour.dart`.

## Adding a new screen

Create `lib/<name>_page.dart`, compose shared widgets, navigate via
`Navigator.push(MaterialPageRoute(...))`. Read data with the `supabase` client from
`main.dart` (RLS scopes it). Keep network reads in `Future`s with `FutureBuilder`.

## Run / build

```bash
flutter create .            # once: platform folders
flutter run -d chrome --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=...
flutter build web --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=...   # → build/web
```

Login uses an email code → enable `{{ .Token }}` in Supabase Auth → Email Templates.
