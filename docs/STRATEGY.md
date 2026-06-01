# Strategy — graphs, style system, native, backends (#67)

A lay-of-the-land for the four "strategy" questions, with current state, options, and a
recommended direction for each. Nothing here is committed as a decision yet — feedback first,
then the chosen paths graduate into ADRs in `docs/DECISIONS.md`.

> TL;DR recommendation: **keep fl_chart** (swap only if a specific chart type blocks us), **invest
> in a light in-house design-token + component layer** (the real pain is `dashboard_page.dart` at
> 2,270 lines, not the theme), **ship native via the existing Flutter codebase** (iOS first, PWA as
> the no-friction default), and **make the backend swappable through config we already mostly have**
> — no migration now, just remove hard-coding so a free-tier squeeze is a config change, not a rewrite.

---

## 1. Graph library

**Current.** `fl_chart ^0.69` — used in exactly one place (`dashboard_page.dart`, the KPI
line/bar charts with the period toggle + drilldowns). It works, it's free, MIT, no native deps
(web-safe). The KPI rework (#52/#61/#71) is built on it.

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **Stay on fl_chart** | already integrated, free, web-clean, flexible enough for line/bar/period compare | lower-level (you draw axes/tooltips yourself); no built-in pan/zoom | **Recommended default** |
| Syncfusion Flutter Charts | rich (zoom, trackball, many types), polished | free *Community* license has revenue/eligibility terms — worth a license review before adopting | only if we need a chart fl_chart can't do |
| Graphic (grammar-of-graphics) | declarative, elegant for complex viz | smaller ecosystem, steeper learning curve, more churn | not now |

**Recommendation.** Keep fl_chart. It's isolated to one file, so a future swap is cheap. Revisit
only if a concrete need appears (interactive zoom on long time series, heatmaps, funnel charts).
Low-risk near-term win: extract the chart widgets out of `dashboard_page.dart` into
`lib/widgets/kpi_charts.dart` so the chart lib stays swappable behind our own widget API.

---

## 2. Style system

**Current.** Material 3 with `colorSchemeSeed: Colors.indigo` (one line in `main.dart`). Shared
widgets live in `golden_hour.dart` (`GoldenHourChips`, `InitialsAvatar`, `milestones`) and a
`ScreenTier` mobile/tablet/desktop responsive helper. App-wide `SelectionArea`. The disclaimer
widgets are centralized. **The real issue isn't theming — it's that `dashboard_page.dart` is 2,270
lines** (every view, card, sheet, and helper in one file), and styling is inlined per-widget
(repeated `TextStyle`, colors, paddings, pill/tag chrome).

**Options**
- **A — In-house design tokens + component extraction (recommended).** A small `lib/theme/`:
  `tokens.dart` (spacing, radii, semantic colors: success/warn/info, status pill styles) +
  `app_theme.dart` (the `ThemeData`, light/dark). Then extract reused chrome (`_Card`, `_Pill`,
  `_tag`, `_Row`, status chips, section headers) into `lib/widgets/`. This is what new views already
  want to compose (CLAUDE.md's "shared widgets" rule) — we just haven't paid down the inlining.
- **B — Adopt a component kit** (e.g. shadcn-style ports, `forui`, `flutter_animate` for motion).
  Faster polish, but adds a dependency to track and a look that may fight LCR/iOS familiarity (the
  user explicitly wants rich LCR/iOS-style layouts — see `feedback_ui_style`).
- **C — Leave as-is.** Cheapest now, but the god-file keeps growing and every new view re-inlines
  styles → drift.

**Recommendation.** **A.** Highest leverage is **splitting `dashboard_page.dart`** (views →
`lib/views/`, shared chrome → `lib/widgets/`, tokens → `lib/theme/`) and routing all color/spacing
through tokens. Add **dark mode** for free once the theme is centralized. Defer a third-party kit.

---

## 3. Native (iOS / Android)

**Current.** One Flutter codebase already targets web + iOS + macOS + Android (CLAUDE.md's core
premise). Deployed surface today = **web/PWA** on Cloudflare Pages. The Android `apk` build was
intentionally paused; the generated platform folders (`android/ios/macos/windows/web/`) are
gitignored — CI builds the web bundle with `flutter build web` (`deploy-web.yml`), so nothing
generated is committed (only `web/_headers` is force-tracked). `local_auth` biometrics already in.
The app is CORS-free (reads Supabase only), so native has no extra backend work.

| Path | Effort | Distribution | Notes |
|---|---|---|---|
| **PWA (today)** | none | "Add to Home Screen" | works now; no store; weak push; iOS PWA limits |
| **iOS native** | medium | TestFlight → App Store | needs Apple Developer ($99/yr), signing, `ios/` scaffold, app review. Biometric/passkey shine here |
| **Android native** | medium | APK sideload now / Play later | `apk` already scoped (paused); Play needs $25 one-time + `.aab` |
| **macOS/Windows** | low | direct download | nice-to-have; low demand |

**Recommendation.** **PWA stays the zero-friction default.** For native, do **iOS first** (the
reference app is iOS; leaders are iPhone-heavy; biometric/passkey login is best there) once the
design-token work (section 2) lands so the native build looks first-class. Keep platform folders
**generated, not committed** (regenerate via `flutter create .`; pin AGP/Kotlin/Gradle per
DEPLOYMENT.md to avoid the known AGP-9 break). Sequence: design system → iOS TestFlight beta →
Android `.aab` → stores. **Passkey/WebAuthn** (open roadmap item) is worth pairing with the iOS push.

---

## 4. Backends (free-tier resilience)

**Current stack & free-tier exposure**

| Service | Role | Free-tier limit / risk | Swap difficulty |
|---|---|---|---|
| **Supabase** | Postgres + Auth + RLS (system of record, ADR-001) | 500 MB DB, 2 projects, **pauses after ~1 wk inactivity** (daily sync keeps it warm) | **High** — RLS + Auth + REST are deeply used |
| **Render** | auth broker (FastAPI) | sleeps after 15 min idle (mitigated: retry + keep-warm) | **Low** — any container host (Fly/Railway) |
| **Cloudflare Pages** | viewer hosting | generous; 500 builds/mo | **Low** — any static host |
| **GitHub Actions** | daily sync + deploys | 2,000 min/mo private (public = free) | **Low** — any cron/CI |
| **Resend** | email | 3,000/mo, 100/day | **Low** — mailer is provider-agnostic (SMTP fallback already) |
| **Google Sheets** | coarse export | free | **Low** — optional already |

**Reality check.** Only **Supabase** is a hard dependency (RLS is the access model — ADR-001/0002).
Everything else is already swappable or has a documented fallback. The user's ask ("configure their
backends if we get close to losing free tiers") is mostly about **removing hard-coding**, not
migrating now.

**Options**
- **A — Config-ize what's already swappable (recommended, mostly done).** Broker URL, app URL,
  spreadsheet id, email transport, GitHub repo are env/`--dart-define` already. Gap: a single
  documented "providers" matrix + a `docs/RUNBOOK_FAILOVER.md` (how to repoint each piece). Cheap.
- **B — Reduce the Supabase lock-in surface.** Keep RLS but ensure the schema + migrations are
  portable Postgres (they are — plain SQL), and the app talks to Supabase only through a thin data
  layer so a move to self-hosted Postgres + PostgREST/Supabase-OSS is a config change. Medium.
- **C — Self-host everything** (Supabase OSS / a VPS). Removes tier risk entirely but adds ops
  burden + cost. Only if we actually outgrow free tiers.

**Recommendation.** **A now, B opportunistically.** Write the failover runbook + a one-screen
"providers" table; keep migrations vendor-neutral SQL (already true); introduce a thin
`lib/data/` layer only when we touch those call sites anyway. Defer C until a real limit bites
(the daily sync already prevents the Supabase idle-pause, the main near-term risk).

---

## Suggested sequence (if these are greenlit)

1. **Design tokens + split `dashboard_page.dart`** (section 2A) — unblocks polish, dark mode, and a
   credible native build. Highest leverage.
2. **Extract chart widgets** behind our own API (section 1) — keeps fl_chart swappable.
3. **iOS TestFlight beta** (section 3) — needs an Apple Developer account from the owner.
4. **Failover runbook + providers table** (section 4A) — low effort, high peace-of-mind.
5. Revisit native Android stores + passkey/WebAuthn after iOS beta feedback.

Owner inputs that would unblock work: Apple Developer account (for iOS), and a yes/no on dark mode
+ whether to keep the strict LCR/iOS visual language (affects whether we adopt any component kit).
