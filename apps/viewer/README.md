# Covenant Path — Viewer (Flutter)

One Flutter codebase → **web, iOS, macOS, Android**. It reads the **backend** (Supabase),
never LCR directly, so the same app runs everywhere (no CORS/native split). Access is
enforced by Postgres **Row-Level Security**: a stake leader sees the whole stake, a ward
leader sees only their ward — derived automatically from their LCR calling.

> Status: **scaffold** (login + RLS-scoped dashboard). Written but not yet run — see
> "Run" below. The data/auth path it relies on is verified server-side (a Supabase-Auth
> login matched the Stake President to all 112 members via RLS).

## How auth works (no secrets in the client)

1. User signs in with **Supabase Auth** (email one-time code; Google can be added).
2. Supabase issues a JWT containing their **verified email**.
3. **RLS** matches that email to a `user_roles` row (provisioned from LCR callings by the
   daily backend sync) and returns only the rows their calling allows.

There is no custom token minting and no LCR credentials in the app — the publishable
(anon) key is safe to ship because RLS does the gating.

## One-time Supabase setup

- **Auth → Email Templates → Magic Link**: include the code token so OTP works, e.g.
  add `{{ .Token }}` to the template (the app uses a 6-digit code, not a link).
- (Optional) **Auth → Providers → Google** to enable Google sign-in later.

## Run

```bash
cd apps/viewer
flutter create .            # generate platform folders (web/android/ios/macos) once
flutter pub get

# web
flutter run -d chrome \
  --dart-define=SUPABASE_URL=https://<ref>.supabase.co \
  --dart-define=SUPABASE_ANON_KEY=sb_publishable_...

# macOS / iOS / Android: swap -d chrome for -d macos / -d <device-id>
```

Sign in with the email your stake has on file (that's what RLS matches). If you see
"No members visible", the email didn't match a provisioned role.

## Deploy (web → Vercel, free)

```bash
flutter build web --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=...
# deploy build/web/ to Vercel (or any static host)
```

## Files

- `lib/main.dart` — Supabase init + auth gate (login ↔ dashboard).
- `lib/login_page.dart` — email one-time-code sign-in.
- `lib/dashboard_page.dart` — reads `members` (RLS-scoped); two views:
  **Golden Hour** (per-member integration-milestone chips — friends, calling, ministering,
  baptized, recommend, patriarchal, endowed — + per-milestone completion %), and
  **All data** (every covenant-path field = the full spreadsheet). We surface more than the
  reference iOS app (e.g. baptism date, temple recommend, patriarchal, endowment).
- `lib/config.dart` — `SUPABASE_URL` / `SUPABASE_ANON_KEY` via `--dart-define`.

## Roadmap

- Google sign-in; richer charts (covenant-path progress, attendance).
- Optional native "live refresh" mode (direct LCR scrape on iOS/macOS/Android — not
  possible on web due to browser CORS).
- Shares the backend with the (future) admin/onboarding app.
