// Part-member families (migration 0067, Turley proposal Aug 2026): a household where one or more
// are members and one or more are not — an unbaptized spouse or an unbaptized child age 9+.
// Pure logic (unit-tests, mirrors in the native ports): status pipeline, age bands, per-unit
// rollup for the stake presidency (TOTALS ONLY, no names), and the On Date validation.

import type { Member } from '../lib/member';
import { normalizeName } from './manualMembers';

export type PartMemberStatus = 'identified' | 'love' | 'share' | 'on_date' | 'baptized' | 'do_not_contact';
export type PartMemberSource = 'lcr_list_a' | 'lcr_list_b' | 'lcr_report' | 'manual';
export type NonmemberRole = 'spouse' | 'child';
/** List B evidence grade (Ricky's verified model): a confirmed unbaptized spouse in the home,
 *  or a spouse the couple-form household name names who isn't on the roster — a candidate to
 *  confirm with ward leadership, never a confirmation. List A rows have no basis. */
export type PartMemberBasis = 'unbaptized_spouse_in_home' | 'spouse_not_on_record';

export interface PartMemberFamily {
  id: string;
  stake_id?: string | null;
  unit_id?: string | null;
  unit_name?: string | null;
  household_uuid?: string | null;
  household_name?: string | null;
  member_person_uuid?: string | null;
  member_name?: string | null;
  nonmember_name: string;
  nonmember_role: NonmemberRole;
  /** ISO birth date when known — confidential: the UI shows an age BAND, never the date. */
  nonmember_birth_date?: string | null;
  /** ADULT / YOUTH / CHILD from the directory (List A is not children-only — Ricky's capture
   *  had 20 of 64 rows as adults). */
  age_group?: string | null;
  basis?: PartMemberBasis | null;
  named_spouse?: string | null;
  source: PartMemberSource;
  status: PartMemberStatus;
  status_updated_at?: string | null;
  assigned_companionship?: string | null;
  do_not_contact_reason?: string | null;
  notes?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  merged_into_uuid?: string | null;
}

/** The Love → Share → On Date → Baptized pipeline. Do Not Contact is NOT a stage — it is a flag
 *  that supersedes the pipeline (stored as a status so a DNC family can never be worked by mistake). */
export const PMF_PIPELINE: PartMemberStatus[] = ['identified', 'love', 'share', 'on_date', 'baptized'];

export const PMF_STATUS_LABELS: Record<PartMemberStatus, string> = {
  identified: 'Identified',
  love: 'Love',
  share: 'Share',
  on_date: 'On Date',
  baptized: 'Baptized',
  do_not_contact: 'Do Not Contact',
};

export const PMF_SOURCE_LABELS: Record<PartMemberSource, string> = {
  lcr_list_a: 'LCR · unbaptized 9+',
  lcr_list_b: 'LCR · unbaptized spouses',
  lcr_report: 'LCR · spouses report',
  manual: 'Added by a leader',
};

export function isDoNotContact(f: PartMemberFamily): boolean {
  return f.status === 'do_not_contact';
}

/** Age band for display — the birth date itself is confidential and never rendered. */
export function ageBand(birthDate: string | null | undefined, now = new Date()): string {
  if (!birthDate) return 'Age unknown';
  const d = new Date(String(birthDate).slice(0, 10));
  if (Number.isNaN(d.getTime())) return 'Age unknown';
  let age = now.getFullYear() - d.getFullYear();
  const beforeBirthday = now.getMonth() < d.getMonth()
    || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate());
  if (beforeBirthday) age -= 1;
  if (age < 9) return 'Under 9';
  if (age <= 11) return '9–11';
  if (age <= 13) return '12–13';
  if (age <= 17) return '14–17';
  return '18+';
}

/** A family still waiting for first contact: identified and never moved forward. */
export function needsAttention(f: PartMemberFamily): boolean {
  return f.status === 'identified';
}

export interface UnitRollup {
  unitName: string;
  identified: number;
  loveFamilies: number;
  loveIndividuals: number;
  shareFamilies: number;
  shareIndividuals: number;
  onDate: number;
  /** Baptized in the last 31 days — stamped by status_updated_at when a leader marks a family
   *  Baptized (the table stores no separate baptism date; this is the honest proxy, labelled so). */
  baptizedLastMonth: number;
  doNotContact: number;
}

/** Monthly rollup for the stake presidency: one row per unit, TOTALS ONLY — no names, no birth
 *  dates. Fam/Indiv counts count families / non-member individuals in each stage. */
export function rollupByUnit(families: PartMemberFamily[], now = new Date()): UnitRollup[] {
  const byUnit = new Map<string, UnitRollup>();
  const monthAgo = now.getTime() - 31 * 24 * 60 * 60 * 1000;
  for (const f of families) {
    const name = (f.unit_name ?? '').trim() || 'Unknown unit';
    const row = byUnit.get(name) ?? {
      unitName: name, identified: 0, loveFamilies: 0, loveIndividuals: 0,
      shareFamilies: 0, shareIndividuals: 0, onDate: 0, baptizedLastMonth: 0, doNotContact: 0,
    };
    byUnit.set(name, row);
    switch (f.status) {
      case 'identified': row.identified += 1; break;
      case 'love': row.loveFamilies += 1; row.loveIndividuals += 1; break;
      case 'share': row.shareFamilies += 1; row.shareIndividuals += 1; break;
      case 'on_date': row.onDate += 1; break;
      case 'baptized': {
        const stamped = f.status_updated_at ? new Date(f.status_updated_at).getTime() : NaN;
        if (!Number.isNaN(stamped) && stamped >= monthAgo) row.baptizedLastMonth += 1;
        break;
      }
      case 'do_not_contact': row.doNotContact += 1; break;
    }
  }
  return [...byUnit.values()].sort((a, b) => a.unitName.localeCompare(b.unitName));
}

/** On Date is only honest when the non-member is actually being taught: an investigator in the
 *  SAME unit (matched by name — the non-member has no person_uuid until baptized) with a planned
 *  baptism (baptism_goal_date). Returns the match, or null with the reason the stage can't be set. */
export function findOnDateInvestigator(
  f: PartMemberFamily, members: Member[],
): { member: Member | null; reason: string | null } {
  const want = normalizeName(f.nonmember_name);
  const inUnit = members.filter((m) => {
    const unit = String(m['unit_name'] ?? '').trim().toLowerCase();
    const famUnit = (f.unit_name ?? '').trim().toLowerCase();
    return !famUnit || unit === famUnit;
  });
  const match = inUnit.find((m) => normalizeName(String(m['name'] ?? '')) === want);
  if (!match) return { member: null, reason: 'no-investigator' };
  if (!match['baptism_goal_date']) return { member: match, reason: 'no-goal-date' };
  return { member: match, reason: null };
}

export function groupFamiliesByUnit(families: PartMemberFamily[]): Array<{ unitName: string; families: PartMemberFamily[] }> {
  const map = new Map<string, PartMemberFamily[]>();
  for (const f of families) {
    const name = (f.unit_name ?? '').trim() || 'Unknown unit';
    (map.get(name) ?? map.set(name, []).get(name)!).push(f);
  }
  return [...map.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([unitName, list]) => ({
      unitName,
      families: [...list].sort((a, b) =>
        String(a.household_name ?? a.nonmember_name).localeCompare(String(b.household_name ?? b.nonmember_name))),
    }));
}
