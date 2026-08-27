// Golden Hour milestones — the single source of truth the dashboard, person detail, completion
// stats, and Needs view all read. Ported 1:1 from apps/viewer/lib/golden_hour.dart (and verified
// against the Flutter `golden_hour_test`). Eligibility (age / sex / tenure) decides whether a
// milestone is even *asked*; completion is whether the member has done it.

import type { Member } from '../lib/member';
import { detailsOf } from '../lib/member';
import { parseMemberDate, yearOf } from './dates';

export interface Milestone {
  /** Full name (detail + accessibility). */
  label: string;
  /** Chip label (1-2 chars). */
  abbr: string;
  /** Category icon name (lucide-ish key our Icon component maps). */
  icon: string;
  /** Category identity color (Needs pills + section-card icon). */
  color: string;
  complete: (m: Member) => boolean;
  /** Who this milestone can apply to. */
  eligible: (m: Member) => boolean;
  /** The member field this milestone reads — so an N/A value can be detected and EXCLUDED from the
   *  "missing/incomplete" lists (N/A ≠ not-done). Optional: a milestone derived from logic rather than
   *  a single column (none today) can omit it. */
  field?: string;
  /** One-sentence explanation of what this integration step means — the SINGLE source the detail
   *  view's Golden Hour tooltip reads (hover + click/tap). LDS context. */
  description: string;
}

const everyone = (_m: Member) => true;

/** A milestone value that means "doesn't apply to this person" (priesthood for a woman, patriarchal
 *  blessing for a young child, …). N/A is NOT the same as not-done: an N/A field must never make a
 *  member show up as ineligible/missing. The backend writes the literal "N/A"; some display helpers
 *  also derive it client-side (endowmentDisplay / templeExperienceDisplay). */
export function isNA(v: unknown): boolean {
  return String(v ?? '').trim().toUpperCase() === 'N/A';
}

/** Whether a member is EXPECTED to complete this milestone: eligible AND the underlying field isn't
 *  N/A. This is the gate the "needs / missing / incomplete" surfaces use so an N/A field is excluded
 *  entirely (N/A ≠ not-done). Falls back to plain eligibility when a milestone has no single field. */
export function expected(ms: Milestone, m: Member): boolean {
  if (!ms.eligible(m)) return false;
  if (ms.field != null && isNA(m[ms.field])) return false;
  // family-name / first-temple-visit derive N/A client-side for ineligible-by-age people; honor it.
  if (ms.field === 'family_name_prepared' || ms.field === 'first_temple_visit') {
    return !isNA(templeExperienceDisplay(m, ms.field));
  }
  if (ms.field === 'living_ordinance') return !isNA(endowmentDisplay(m));
  return true;
}

/** A member is "missing" a milestone when they're EXPECTED to have it but haven't completed it. The
 *  single helper every needs/incomplete/completion surface shares (so N/A is excluded uniformly). */
export function isMissing(ms: Milestone, m: Member): boolean {
  return expected(ms, m) && !ms.complete(m);
}

function dateOf(v: unknown): Date | null {
  return parseMemberDate(v);
}

/** "Turns at least [age] by the end of this calendar year" (by-year rule). Unknown birth → false. */
function turnsAtLeast(m: Member, age: number): boolean {
  const by = yearOf(m['birth_date']);
  return by != null && new Date().getFullYear() - by >= age;
}

/** member ≥ 1 year: baptized ≥ 365 days ago, or membership_duration says "N years" with N ≥ 1. */
function memberOneYearPlus(m: Member): boolean {
  const b = dateOf(m['baptism_date']);
  if (b != null) {
    return Math.floor((Date.now() - b.getTime()) / 86_400_000) >= 365;
  }
  const ym = /(\d+)\s*year/.exec(String(m['membership_duration'] ?? '').toLowerCase());
  return ym != null && Number(ym[1]) >= 1;
}

/** Actual current age (full birth date when present, else by-year). */
function ageNow(m: Member): number | null {
  const d = dateOf(m['birth_date']);
  if (d != null) {
    const now = new Date();
    let age = now.getFullYear() - d.getFullYear();
    if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) {
      age--;
    }
    return age;
  }
  const by = yearOf(m['birth_date']);
  return by == null ? null : new Date().getFullYear() - by;
}

function ageNowAtLeast(m: Member, age: number): boolean {
  const a = ageNow(m);
  return a != null && a >= age;
}

function male(m: Member): boolean {
  return m['sex'] === 'M';
}

// ---- Temple Ordinances and Experiences (family name + first temple visit) ----------------------

/** The LCR commitment each flat column is derived from, matched by substring (mirrors the report's
 *  parse_temple_experiences): "Prepare a Family Name for the Temple" / "Perform Baptisms for
 *  Deceased Ancestors". */
const TEMPLE_EXPERIENCE_NEEDLES: Record<string, string> = {
  family_name_prepared: 'family name',
  first_temple_visit: 'baptisms for deceased',
};

/** Effective Yes/No for a temple-experience field. The flat column (filled by the daily sync) wins;
 *  a row not yet re-synced (sentinel/empty flat value) falls back to the `details.templeExperiences`
 *  subtree — the same LCR commitments, scraped earlier — so the milestone lights up immediately.
 *  Returns the raw flat value (sentinel/empty) when neither source knows. */
export function templeExperienceValue(m: Member, key: string): string {
  const v = String(m[key] ?? '');
  if (v === 'Yes' || v === 'No' || v === 'N/A') return v;
  const list = detailsOf(m)?.['templeExperiences'];
  if (Array.isArray(list)) {
    const needle = TEMPLE_EXPERIENCE_NEEDLES[key] ?? '';
    for (const t of list) {
      if (!t || typeof t !== 'object') continue;
      const r = t as Record<string, unknown>;
      if (String(r['name'] ?? '').toLowerCase().includes(needle)) {
        return r['done'] === true ? 'Yes' : 'No';
      }
    }
  }
  return v;
}

// Golden Hour = a new member's first-year integration milestones, each gated to who it can apply
// to (age / sex / tenure). Baptism is intentionally NOT a milestone.
export const milestones: Milestone[] = [
  {
    label: 'Friends', abbr: 'F', icon: 'handshake', color: '#D81B60', field: 'friends',
    description: 'The new member has at least one friend in the ward — someone who reaches out, sits with them, and helps them feel they belong.',
    complete: (m) => m['friends'] === 'Yes', eligible: everyone,
  },
  {
    label: 'Calling', abbr: 'C', icon: 'badge', color: '#6A1B9A', field: 'calling',
    description: 'The member has been given a responsibility (a calling) in the ward — a meaningful way to serve and stay engaged.',
    complete: (m) => m['calling'] === 'Yes', eligible: (m) => turnsAtLeast(m, 12),
  },
  {
    label: 'Ministers assigned', abbr: 'M', icon: 'support', color: '#00838F',
    field: 'ministering_brothers_sisters',
    description: 'Ministering brothers or sisters are assigned to watch over this member and visit them regularly.',
    complete: (m) => m['ministering_brothers_sisters'] === 'Yes', eligible: everyone,
  },
  {
    label: 'Ministering assignment', abbr: 'MA', icon: 'volunteer', color: '#EF6C00',
    field: 'ministering_assignment',
    description: 'The member has people of their own to minister to — serving alongside the ward as a minister themselves.',
    complete: (m) => m['ministering_assignment'] === 'Yes', eligible: (m) => turnsAtLeast(m, 14),
  },
  {
    label: 'Aaronic Priesthood', abbr: 'AP', icon: 'medal', color: '#1565C0', field: 'aaronic_priesthood',
    description: 'A worthy male member age 12+ has received the Aaronic Priesthood (ordained a deacon, teacher, or priest).',
    complete: (m) => m['aaronic_priesthood'] === 'Yes',
    eligible: (m) => male(m) && turnsAtLeast(m, 12),
  },
  {
    label: 'Melchizedek Priesthood', abbr: 'MP', icon: 'premium', color: '#2E7D32',
    field: 'melchizedek_priesthood',
    description: 'A worthy adult man (18+, a member about a year) has received the Melchizedek Priesthood (ordained an elder) — a step toward the temple.',
    complete: (m) => m['melchizedek_priesthood'] === 'Yes',
    // arrow (not a bare reference): `melchizedekEligible` is declared below this array.
    eligible: (m) => melchizedekEligible(m),
  },
  // Temple Ordinances and Experiences (#first-temple-visit): genealogy + proxy baptisms, both from
  // the year someone turns 12 (limited-use recommend age — same by-year rule as calling/Aaronic).
  {
    label: 'Family Name Prepared', abbr: 'FN', icon: 'menu_book', color: '#6D4C41',
    field: 'family_name_prepared',
    description: 'The member has found and prepared a family name through family history, ready to take to the temple.',
    complete: (m) => templeExperienceValue(m, 'family_name_prepared') === 'Yes',
    eligible: (m) => turnsAtLeast(m, 12),
  },
  {
    label: 'First Temple Visit', abbr: 'FT', icon: 'account_balance', color: '#00897B',
    field: 'first_temple_visit',
    description: 'The member has made their first temple visit to perform baptisms for deceased ancestors.',
    complete: (m) => templeExperienceValue(m, 'first_temple_visit') === 'Yes',
    eligible: (m) => turnsAtLeast(m, 12),
  },
];

/** The milestones that apply to a given member (eligibility- AND not-N/A-filtered, via `expected`).
 *  An N/A field (priesthood for a woman, patriarchal blessing for a young child) is EXCLUDED — it's
 *  not-applicable, not not-done — so it never inflates the denominator or shows as missing. A real
 *  "Yes" is always still counted (it's not N/A). Mirrors `milestonesFor`. */
export function milestonesFor(m: Member): Milestone[] {
  return milestones.filter((x) => expected(x, m) || x.complete(m));
}

/** Fraction 0..1 of this member's APPLICABLE Golden Hour milestones that are complete (eligible-only,
 *  N/A excluded). Drives the completion ring on the detail page — full + green at 1.0. (Friends +
 *  Has-ministers apply to everyone, so there's always ≥1 applicable.) */
export function completionOf(m: Member): number {
  const applicable = milestonesFor(m);
  if (applicable.length === 0) return 0;
  return applicable.filter((x) => x.complete(m)).length / applicable.length;
}

/** Endowment eligibility: an adult (18+) who's been a member ~1 year. Same gate as the report. */
export function endowmentEligible(m: Member): boolean {
  return ageNowAtLeast(m, 18) && memberOneYearPlus(m);
}

// Per-field eligibility for the member-detail view: which status rows / sections even APPLY to this
// person, so we hide what's irrelevant (no priesthood for women, no calling for a child) instead of
// showing a misleading "No". Mirrors the milestone gates above and the native Milestones logic so all
// three surfaces hide the same things.
export const callingEligible = (m: Member): boolean => turnsAtLeast(m, 12);
export const ministeringAssignmentEligible = (m: Member): boolean => turnsAtLeast(m, 14);
export const aaronicEligible = (m: Member): boolean => male(m) && turnsAtLeast(m, 12);
/** Melchizedek Priesthood applies to an adult man (18+) who's been a member ~a year — OR to any man
 *  the records show is ALREADY ordained. The one-year mark is guidance, not a rule: a convert can be
 *  and often is ordained an elder sooner (e.g. before a mission or a temple sealing). Gating purely
 *  on duration made a genuinely-ordained brother read "N/A" instead of "Yes" — hiding a real
 *  ordination. So: ordained -> Yes always; not ordained and under a year -> N/A (not yet expected);
 *  not ordained and over a year -> No (a real gap worth surfacing). */
export const melchizedekEligible = (m: Member): boolean =>
  male(m) && (m['melchizedek_priesthood'] === 'Yes'
    || (ageNowAtLeast(m, 18) && memberOneYearPlus(m)));
/** Priesthood section applies to males old enough for the Aaronic priesthood (12+). */
export const priesthoodEligible = (m: Member): boolean => male(m) && turnsAtLeast(m, 12);
/** Temple recommend (incl. limited-use) and a patriarchal blessing both start around age 12. */
export const templeRecommendEligible = (m: Member): boolean => turnsAtLeast(m, 12);
export const patriarchalEligible = (m: Member): boolean => turnsAtLeast(m, 12);
/** Family name + first temple visit (proxy baptisms) start at the limited-use recommend age (12). */
export const templeExperienceEligible = (m: Member): boolean => turnsAtLeast(m, 12);

/** Needs-view categories: the 6 Golden Hour milestones PLUS the longer-horizon covenants we also track
 *  (temple recommend, endowment, patriarchal blessing) — so leaders see everyone eligible-but-missing
 *  each one. The core `milestones` set stays the integration-only completion basis; this is the
 *  superset just for the Needs categories. */
export const needsCategories: Milestone[] = [
  ...milestones,
  {
    label: 'Temple Recommend', abbr: 'TR', icon: 'premium', color: '#5E35B1', field: 'temple_recommend',
    description: 'The member holds a current temple recommend (limited-use or full), allowing them to enter the temple.',
    complete: (m) => m['temple_recommend'] === 'Active',
    eligible: templeRecommendEligible,
  },
  {
    label: 'Endowment', abbr: 'EN', icon: 'premium', color: '#00695C', field: 'living_ordinance',
    description: 'The member has received their own temple endowment — a key covenant ordinance for adults.',
    complete: (m) => m['living_ordinance'] === 'Yes',
    eligible: endowmentEligible,
  },
  // Patriarchal blessing uses the SAME age gate as temple recommend (members turning ≥12 this
  // calendar year — the limited-use recommend age). N/A (a young child) is excluded via `expected`.
  {
    label: 'Patriarchal Blessing', abbr: 'PB', icon: 'menu_book', color: '#AD1457',
    field: 'patriarchal_blessing',
    description: 'The member has received a patriarchal blessing — personal guidance and a declaration of lineage from a stake patriarch. '
      + 'Note: this is the one field not available from the daily sync — it refreshes when a leader re-authorizes (about every 45 days).',
    complete: (m) => m['patriarchal_blessing'] === 'Yes',
    eligible: patriarchalEligible,
  },
];

/** Display value for endowment (living_ordinance): N/A for INELIGIBLE members — they can't be endowed
 *  yet, so a raw "No" is misleading. Gates client-side so it's correct before the next sync re-scrapes
 *  (the report applies the same gate server-side). A real "Yes" is always kept. */
export function endowmentDisplay(m: Member): string {
  const v = String(m['living_ordinance'] ?? '');
  if (v === 'Yes') return 'Yes';
  return endowmentEligible(m) ? v : 'N/A';
}

/** Display value for family-name / first-temple-visit: same N/A-for-ineligible gate as endowment
 *  (an under-12 can't do proxy baptisms yet, so a raw "No" misleads); a real "Yes" is always kept. */
export function templeExperienceDisplay(m: Member, key: string): string {
  const v = templeExperienceValue(m, key);
  if (v === 'Yes') return 'Yes';
  return templeExperienceEligible(m) ? v : 'N/A';
}

// ---- Convert responsibility (the stake's hand-off policy, #23) ---------------------------------

export type OrgBucket = 'wml' | 'eq' | 'rs';
export const ORG_BUCKETS: OrgBucket[] = ['wml', 'eq', 'rs'];

export interface OrgInfo {
  label: string;
  short: string;
  icon: string;
  color: string;
}

/** Label + short tag + icon + color for each org bucket. Mirrors `orgInfo`. */
export function orgInfo(b: OrgBucket): OrgInfo {
  switch (b) {
    case 'wml':
      return { label: 'Missionaries & ward mission leader', short: 'WML', icon: 'volunteer', color: '#00897B' };
    case 'eq':
      return { label: 'Elders Quorum', short: 'EQ', icon: 'groups', color: '#1565C0' };
    case 'rs':
      return { label: 'Relief Society', short: 'RS', icon: 'diversity', color: '#AD1457' };
  }
}

/** Which org currently owns this convert's integration, or null when there's no baptism date. */
export function responsibleOrg(m: Member): OrgBucket | null {
  const b = dateOf(m['baptism_date']);
  if (b == null) return null;
  const months = Math.floor((Date.now() - b.getTime()) / 86_400_000 / 30.44);
  if (months < 12) return 'wml';
  return male(m) ? 'eq' : 'rs';
}

/** One-line explanation of when converts are this org's responsibility. Mirrors the Dart note. */
export function orgResponsibilityNote(b: OrgBucket): string {
  switch (b) {
    case 'wml':
      return 'First year after baptism: the full-time missionaries and the ward mission leader watch over each new member’s progress.';
    case 'eq':
      return 'After the first year: the elders quorum presidency watches over each brother’s continued integration.';
    case 'rs':
      return 'After the first year: the Relief Society presidency watches over each sister’s continued integration.';
  }
}

export interface ResponsibleParty {
  label: string;
  icon: string;
  color: string;
}

/** Responsibility chip data for a member (Unassigned when no baptism date). Mirrors `responsibleParty`. */
export function responsibleParty(m: Member): ResponsibleParty {
  const org = responsibleOrg(m);
  if (org == null) return { label: 'Unassigned', icon: 'help', color: '#9E9E9E' };
  const i = orgInfo(org);
  return { label: i.label, icon: i.icon, color: i.color };
}

/** Display age (e.g. "35 yrs") from birth_date, or null when unknown/negative. Mirrors `ageOf`. */
export function ageOf(m: Member): string | null {
  const a = ageNow(m);
  return a == null || a < 0 ? null : `${a} yrs`;
}

/** Numeric age in years (for the table column's display + numeric sort), or null when unknown. */
export function ageYears(m: Member): number | null {
  const a = ageNow(m);
  return a == null || a < 0 ? null : a;
}

/** Initials for an avatar fallback. Mirrors `initialsOf`. */
export function initialsOf(name: string): string {
  const parts = name.replace(/,/g, '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0 || parts[0].length === 0) return '?';
  const s = parts.length === 1
    ? [...parts[0]][0]
    : `${[...parts[0]][0]}${[...parts[parts.length - 1]][0]}`;
  return s.toUpperCase();
}

// ---- Golden Hour completion ROWS (item 4: one row per item, ✓ done / ○ not done / ⚠ data issue) ----
// The user-chosen layout: render each APPLICABLE milestone as one row with a status icon. The three
// rules, enforced here so the row builder is the single source the view renders:
//   • OMIT N/A entirely — N/A means NOT ELIGIBLE (a child's patriarchal blessing, a woman's
//     priesthood), so the row is dropped, never shown.
//   • ⚠ for a DATA ISSUE — the underlying field is the needs-profile-api sentinel OR null/empty (we
//     should have it but don't). Distinct from both done and not-done.
//   • otherwise ✓ done / ○ not done.

export type GhRowStatus = 'done' | 'not-done' | 'issue';

export interface GhRow {
  milestone: Milestone;
  status: GhRowStatus;
}

/** Whether a milestone's underlying field value is a DATA ISSUE for this member: the field is present
 *  on the milestone, the member is EXPECTED to have it (eligible + not N/A), it isn't complete, and
 *  the raw value is a sentinel OR null/empty. (A real "No" is NOT an issue — it's an honest not-done.)
 *  Milestones with no single `field` can never be a data issue (derived purely from logic). */
function isFieldDataIssue(ms: Milestone, m: Member): boolean {
  if (ms.field == null) return false;
  if (ms.complete(m)) return false;
  const raw = m[ms.field];
  const s = String(raw ?? '').trim();
  // A genuine recorded "No"/"Expired"/etc. is an honest not-done, never a data issue.
  if (s !== '' && !isSentinelLike(s)) return false;
  return true;
}

/** Sentinel recognizer kept local so milestones.ts has no import cycle with fieldDisplay (which
 *  imports isNA from here). Mirrors lib/member.isSentinel. */
function isSentinelLike(s: string): boolean {
  return s === 'needs-profile-api' || s.startsWith('blocked');
}

/** Build the Golden Hour completion ROWS for one member from a milestone list (defaults to the
 *  integration `milestones`; pass `needsCategories` to also include temple recommend / endowment /
 *  patriarchal blessing). N/A milestones are OMITTED (not eligible). Each surviving row is classified
 *  done / not-done / issue. The order follows the milestone list. */
export function goldenHourRows(m: Member, list: Milestone[] = milestones): GhRow[] {
  const rows: GhRow[] = [];
  for (const ms of list) {
    // Drop anything that doesn't APPLY: not eligible, or an N/A (not-eligible) field value. A real
    // "Yes" is still kept (expected() already lets a completed milestone through).
    if (!expected(ms, m) && !ms.complete(m)) continue;
    if (ms.complete(m)) {
      rows.push({ milestone: ms, status: 'done' });
    } else if (isFieldDataIssue(ms, m)) {
      rows.push({ milestone: ms, status: 'issue' });
    } else {
      rows.push({ milestone: ms, status: 'not-done' });
    }
  }
  return rows;
}

/** The milestones this member still NEEDS to do — the not-yet-complete, applicable steps (their
 *  "next steps"). Used by the friend/investigator detail view. Excludes N/A and completed; includes
 *  data-issue rows (a leader should still see the step is outstanding). Defaults to integration set. */
export function nextSteps(m: Member, list: Milestone[] = milestones): Milestone[] {
  return goldenHourRows(m, list).filter((r) => r.status !== 'done').map((r) => r.milestone);
}

/** Average Golden Hour completion across rows (eligible-only per member). Mirrors `_avgCompletion`. */
export function avgCompletion(rows: Member[]): number {
  if (rows.length === 0) return 0;
  let sum = 0;
  for (const m of rows) {
    const applicable = milestonesFor(m);
    if (applicable.length === 0) continue;
    sum += applicable.filter((x) => x.complete(m)).length / applicable.length;
  }
  return sum / rows.length;
}

export interface UnitGoldenHour {
  unit: string;
  people: number; // members in the unit
  fullyComplete: number; // members with EVERY applicable milestone complete
  itemsDone: number; // total complete applicable milestones across the unit
  itemsTotal: number; // total applicable milestones across the unit
}

/** Per-unit Golden Hour rollup for the #8d indicators: the share of PEOPLE who are fully complete (a
 *  SECTIONED ring — one arc per person, filled when they're done) and the share of ITEMS complete
 *  overall (a FILLED ring). Eligible-only per member (N/A excluded) — a member with no applicable
 *  milestones counts as fully complete (nothing outstanding). Ranked by people desc. Pure → mirrored. */
export function unitGoldenHour(rows: Member[]): UnitGoldenHour[] {
  const by = new Map<string, Member[]>();
  for (const m of rows) {
    const u = String(m['unit_name'] ?? '—');
    if (!by.has(u)) by.set(u, []);
    by.get(u)!.push(m);
  }
  const out: UnitGoldenHour[] = [];
  for (const [unit, members] of by) {
    let fully = 0;
    let done = 0;
    let total = 0;
    for (const m of members) {
      const applicable = milestonesFor(m);
      const c = applicable.filter((x) => x.complete(m)).length;
      done += c;
      total += applicable.length;
      if (applicable.length === 0 || c === applicable.length) fully += 1;
    }
    out.push({ unit, people: members.length, fullyComplete: fully, itemsDone: done, itemsTotal: total });
  }
  out.sort((a, b) => b.people - a.people);
  return out;
}
