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
}

const everyone = (_m: Member) => true;

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
    label: 'Friends', abbr: 'F', icon: 'handshake', color: '#D81B60',
    complete: (m) => m['friends'] === 'Yes', eligible: everyone,
  },
  {
    label: 'Calling', abbr: 'C', icon: 'badge', color: '#6A1B9A',
    complete: (m) => m['calling'] === 'Yes', eligible: (m) => turnsAtLeast(m, 12),
  },
  {
    label: 'Has ministers', abbr: 'M', icon: 'support', color: '#00838F',
    complete: (m) => m['ministering_brothers_sisters'] === 'Yes', eligible: everyone,
  },
  {
    label: 'Ministering assignment', abbr: 'MA', icon: 'volunteer', color: '#EF6C00',
    complete: (m) => m['ministering_assignment'] === 'Yes', eligible: (m) => turnsAtLeast(m, 14),
  },
  {
    label: 'Aaronic Priesthood', abbr: 'AP', icon: 'medal', color: '#1565C0',
    complete: (m) => m['aaronic_priesthood'] === 'Yes',
    eligible: (m) => male(m) && turnsAtLeast(m, 12),
  },
  {
    label: 'Melchizedek Priesthood', abbr: 'MP', icon: 'premium', color: '#2E7D32',
    complete: (m) => m['melchizedek_priesthood'] === 'Yes',
    eligible: (m) => male(m) && ageNowAtLeast(m, 18) && memberOneYearPlus(m),
  },
  // Temple Ordinances and Experiences (#first-temple-visit): genealogy + proxy baptisms, both from
  // the year someone turns 12 (limited-use recommend age — same by-year rule as calling/Aaronic).
  {
    label: 'Family name prepared', abbr: 'FN', icon: 'menu_book', color: '#6D4C41',
    complete: (m) => templeExperienceValue(m, 'family_name_prepared') === 'Yes',
    eligible: (m) => turnsAtLeast(m, 12),
  },
  {
    label: 'First temple visit', abbr: 'FT', icon: 'account_balance', color: '#00897B',
    complete: (m) => templeExperienceValue(m, 'first_temple_visit') === 'Yes',
    eligible: (m) => turnsAtLeast(m, 12),
  },
];

/** The milestones that apply to a given member (eligibility-filtered). Mirrors `milestonesFor`. */
export function milestonesFor(m: Member): Milestone[] {
  return milestones.filter((x) => x.eligible(m));
}

/** Fraction 0..1 of this member's APPLICABLE Golden Hour milestones that are complete (eligible-only).
 *  Drives the completion ring on the detail page — full + green at 1.0. (Friends + Has-ministers apply
 *  to everyone, so there's always ≥1 applicable.) */
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
export const melchizedekEligible = (m: Member): boolean =>
  male(m) && ageNowAtLeast(m, 18) && memberOneYearPlus(m);
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
    label: 'Temple Recommend', abbr: 'TR', icon: 'premium', color: '#5E35B1',
    complete: (m) => m['temple_recommend'] === 'Active',
    eligible: templeRecommendEligible,
  },
  {
    label: 'Endowment', abbr: 'EN', icon: 'premium', color: '#00695C',
    complete: (m) => m['living_ordinance'] === 'Yes',
    eligible: endowmentEligible,
  },
  {
    label: 'Patriarchal Blessing', abbr: 'PB', icon: 'menu_book', color: '#AD1457',
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
      return { label: 'Missionaries / WML', short: 'WML', icon: 'volunteer', color: '#00897B' };
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
