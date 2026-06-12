# New views from the Member Tools data — PROPOSAL (for discussion, not yet built)

The Member Tools `/api/v5/sync` migration brings in richer covenant-path data than the app currently
shows (it's already flowing into each member's `details`). This proposes WHAT to surface and WHERE,
rated by usefulness, mindful of: (a) the existing **rich card/section** style — not flat key-value
lists (per the UI-style preference), and (b) the **three-surface rule** — every view ships to React
web + native iOS + native Android together.

Today the member detail already shows **Sacrament attendance** + **Friends in the Church** +
recommend/endowment/patriarchal sections. The KPIs tab shows baptisms-by-month + being-taught.

## Proposed additions, ranked

### ⭐ 1. Member detail — "Lessons taught" section  (HIGH — the biggest gap)
**Data:** `details.lessons` (from `teachingRecords`): each lesson (e.g. *Restoration*) with its
principles, `memberPresent`, and taught level.
**Where:** a new `LessonsSection` on `PersonDetailPage` (+ iOS/Android equivalents), styled like the
existing `SacramentSection` card.
**Why:** this is the *core* of convert progress and we don't surface it at all today. A leader can see
exactly which discussions/principles a person has been taught and whether they were present.
**Sketch:** a card "Lessons" → per lesson a row with a check/par­tial/empty pip per principle; a small
"X of Y principles taught" summary. iOS-style, not a table dump.

### ⭐ 2. KPIs tab — recommend & priesthood-gap tiles  (HIGH — actionable for leaders)
**Data:** `unitStatistics` — `endowedWithRecommend` / `endowedWithoutRecommend`,
`householdsWithoutMelchizedekPriesthoodHolder`.
**Where:** new tiles on the KPIs tab (alongside baptisms-by-month).
**Why:** these are *actionable* leadership metrics ("12 endowed members without a current recommend",
"5 households without a Melchizedek-priesthood holder") — directly drives ministering focus.
**Sketch:** two compact stat tiles with a count + a tap-through to the member list filtered to that set
(the payload gives the `…Uuids` arrays, so the drill-down list is free).

### 2. Member detail — attendance *history*, not just "weeks since"  (MEDIUM-HIGH)
**Data:** `details.sacrament` (per-person `sacramentAttendance` with dates + attended).
**Where:** enrich the existing `SacramentSection` with a small **last-12-weeks strip** (attended/missed
pips) above the current summary.
**Why:** "weeks since last attendance" is a single number; the strip shows the *pattern* (e.g.
attending then dropped off) — far more useful for outreach. Low effort (data already in `details`).

### 3. Member detail — Commitments  (MEDIUM)
**Data:** `details.commitments` (title; the raw payload also has `isKeeping`/`invitationDate`).
**Where:** a small `CommitmentsSection` card on the detail page.
**Why:** shows what a person has committed to (baptism date, Word of Wisdom, etc.) and whether kept —
covenant-path-relevant. (We'd extend the adapter to keep `isKeeping`.)

### 4. Member list/cards — "next appointment" badge  (MEDIUM, small)
**Data:** `details.nextScheduledEvent` (from `nextAppointment`).
**Where:** a tiny badge on the Being-Taught list rows / member card.
**Why:** at-a-glance "who has an upcoming appointment" — light, useful for planning.

## Deliberately NOT proposing (out of covenant-path scope — flag if you want them)
- Full **households directory**, **ministering org chart**, **missionary roster**, **calendars/finances**
  — the payload has them, but they're general ward-management features beyond convert integration. They'd
  bloat the app and dilute the focused covenant-path purpose. Skip unless you specifically want one.
- Raw dumps of any array — everything proposed is a *curated* card, matching the existing style.

## Style + cross-surface notes
- Reuse the existing `SectionCard` / detail-section pattern (web `PersonDetailPage`, iOS
  `DetailSections.swift`, Android detail screen) — rich cards, icons, summaries; no flat tables.
- Every item ships to **all three surfaces** in lockstep (web + native iOS + Android), with mirrored
  logic in `apps/web/src/logic`, `native/ios/.../Logic`, `native/android/.../logic` + unit tests.
- The data is already in `details` (web reads `member.details`), so most of this is presentation only.

## Recommended phasing
1. **Lessons section** (#1) + **recommend/priesthood KPI tiles** (#2) — the two high-value wins.
2. **Attendance history strip** (#2-detail) — small, high ratio.
3. Commitments + next-appointment badge — nice-to-haves.

## Open questions for you
- Do the **KPI tiles** (#2) match what your leaders actually want, or are there other `unitStatistics`
  you'd prioritize? (Full list available: attendance %, recommend coverage, priesthood gaps, etc.)
- For **Lessons** (#1): show ALL lessons, or just the most recent / in-progress one?
- Any of the "NOT proposing" items you actually DO want (e.g. ministering)?
