// Ward baptism goals (table `ward_goals`): a per-ward, per-transfer-cycle target. The KPIs page shows
// goal-vs-actual for the CURRENT cycle (the next upcoming transfer) and lets leaders edit it. Actual =
// baptized members whose baptism_date lands in the cycle window. Pure so it unit-tests + mirrors.

import { parseMemberDate } from './dates';
import { nextTransfer, transferWindow, inTransferWindow, type TransferDate } from './transfers';
import type { Member } from '../lib/member';

export interface WardGoal {
  id?: string;
  unit_id?: string | null;
  unit_number?: number | null;
  unit_name?: string | null;
  transfer_id: string;
  goal: number;
}

export interface GoalRow {
  unitId: string | null;
  unitName: string;
  goal: number | null; // null = no goal set for this unit this cycle
  actual: number;
}

/** The transfer cycle ward goals apply to right now: the NEXT upcoming transfer (a goal is set for the
 *  cycle ENDING on that date); if none is scheduled ahead, the most recent transfer on record (its
 *  cycle just ended). Null if the schedule is empty. Returns the cycle id + its window. */
export function currentCycle(
  transferDates: TransferDate[],
  today: Date,
): { transferId: string; window: { start: Date | null; end: Date } } | null {
  const next = nextTransfer(transferDates, today);
  let transferId = next?.transfer_id ?? null;
  if (!transferId) {
    const latest = [...transferDates]
      .filter((t) => parseMemberDate(t.transfer_date))
      .sort((a, b) => String(b.transfer_date).localeCompare(String(a.transfer_date)))[0];
    transferId = latest?.transfer_id ?? null;
  }
  if (!transferId) return null;
  const window = transferWindow(transferDates, transferId);
  return window ? { transferId, window } : null;
}

function sameUnit(g: WardGoal, u: { id: string | null; name: string }): boolean {
  if (g.unit_id && u.id) return g.unit_id === u.id;
  return (g.unit_name ?? '').trim().toLowerCase() === u.name.trim().toLowerCase();
}

/** Per-unit goal vs actual for a cycle. `actual` counts BAPTIZED members (caller pre-filters out
 *  investigators) whose baptism_date falls in the cycle window; `goal` is null when a unit has none set. */
export function goalRows(
  units: Array<{ id: string | null; name: string }>,
  baptized: Member[],
  wardGoals: WardGoal[],
  cycleId: string,
  window: { start: Date | null; end: Date },
): GoalRow[] {
  const actualByUnit = new Map<string, number>();
  for (const m of baptized) {
    const dt = parseMemberDate(m['baptism_date']);
    if (!dt || !inTransferWindow(dt, window)) continue;
    const key = String(m['unit_name'] ?? '');
    actualByUnit.set(key, (actualByUnit.get(key) ?? 0) + 1);
  }
  return units
    .map((u) => {
      const g = wardGoals.find((w) => w.transfer_id === cycleId && sameUnit(w, u));
      return { unitId: u.id, unitName: u.name, goal: g ? g.goal : null, actual: actualByUnit.get(u.name) ?? 0 };
    })
    .sort((a, b) => a.unitName.localeCompare(b.unitName));
}

/** Distinct (unit_id, unit_name) options from the members the viewer can see (RLS already scopes them,
 *  so a ward leader gets only their unit, a stake leader all). Sorted by name. */
export function unitOptions(members: Member[]): Array<{ id: string | null; name: string }> {
  const seen = new Map<string, { id: string | null; name: string }>();
  for (const m of members) {
    const name = String(m['unit_name'] ?? '').trim();
    if (!name) continue;
    const id = (m['unit_id'] as string | null | undefined) ?? null;
    const key = id ?? name;
    if (!seen.has(key)) seen.set(key, { id, name });
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}
