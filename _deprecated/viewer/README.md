# Covenant Path — Viewer (Flutter)

One Flutter codebase → **web, iOS, macOS, Android**. It reads the **backend** (Supabase),
never LCR directly, so the same app runs everywhere (no CORS/native split). Access is
enforced by Postgres **Row-Level Security**: a stake leader sees the whole stake, a ward
leader sees only their ward — derived automatically from their LCR calling.

> Live on **Cloudflare Pages** (`app.membercovenantpath.org`). Five-tab dashboard scoped to one
> selected stake, Church-account / email-code / passkey login, member detail, Settings, and an
> admin/ops console. Deeper structure + contribution rules: **ARCHITECTURE.md** (read that first).

## How auth works (no secrets in the client)

1. User signs in via **Supabase Auth** — a **Church account** (through the auth broker, which does
   the Okta/MFA login the browser can't, and also enrolls the stake for daily sync), an **email
   one-time code**, or a **passkey**. Any path yields a Supabase session.
2. Supabase issues a JWT containing their **verified email**.
3. **RLS** matches that email (or a bound `auth_id`) to a `user_roles` row — provisioned from LCR
   callings each sync, or bound from enrollment (migration 0029) — and returns only the rows their
   calling allows.

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

## Deploy (web → Cloudflare Pages, free)

`.github/workflows/deploy-web.yml` **builds the web bundle in CI** (`flutter build web`) and
deploys it to Cloudflare Pages on a push to `main` touching `apps/viewer/**`. The build output is
not committed. Full runbook (incl. the manual fallback): `docs/DEPLOYMENT.md`.

```bash
flutter build web --release \
  --dart-define=SUPABASE_URL=... --dart-define=SUPABASE_ANON_KEY=... --dart-define=BROKER_URL=...
# → build/web (any static host serves it)
```

## Files

See **ARCHITECTURE.md** for the full file map + rules. In brief: `lib/main.dart` (init + auth
gate), `lib/login_page.dart` (Church / email-code / passkey sign-in), `lib/dashboard_page.dart`
(five tabs scoped to one selected stake), `lib/golden_hour.dart` + `lib/widgets/shimmer.dart`
(shared widgets), `lib/config.dart` (`--dart-define` config).
