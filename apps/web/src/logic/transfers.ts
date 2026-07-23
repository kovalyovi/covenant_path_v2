// The mission transfer schedule (per-stake; table `transfer_dates`). Missionaries rotate on a ~6-week
// cycle. The Baptisms banner shows the NEXT upcoming transfer + a countdown; ward baptism goals
// (logic/wardGoals.ts) are keyed per transfer cycle. Pure so it unit-tests and can mirror to native.

import { parseMemberDate, dayOnly, daysBetween } from './dates';

export interface TransferDate {
  id?: string;
  transfer_id: string;
  transfer_date: string; // ISO YYYY-MM-DD
}

export interface NextTransfer {
  transfer_id: string;
  date: Date;
  daysUntil: number;
}

/** The soonest transfer on/after `today` (inclusive), or null if none is scheduled ahead. Skips
 *  unparseable dates and sorts defensively (the query orders, but a caller may pass an unsorted list). */
export function nextTransfer(dates: TransferDate[], today: Date): NextTransfer | null {
  const t0 = dayOnly(today);
  let best: NextTransfer | null = null;
  for (const row of dates) {
    const parsed = parseMemberDate(row.transfer_date);
    if (!parsed) continue;
    const d = dayOnly(parsed);
    if (d.getTime() < t0.getTime()) continue; // already past
    if (best === null || d.getTime() < best.date.getTime()) {
      best = { transfer_id: row.transfer_id, date: d, daysUntil: daysBetween(t0, d) };
    }
  }
  return best;
}

/** The window a transfer cycle covers, for bucketing baptisms toward that cycle's ward goal: from the
 *  PREVIOUS transfer date up to this transfer's date. A baptism counts toward cycle T when
 *  `start < baptismDate <= end` (a baptism ON a transfer day belongs to the cycle ENDING that day). The
 *  earliest cycle has `start = null` (open-ended before the first transfer). Null if `transferId` is
 *  unknown. */
export function transferWindow(
  dates: TransferDate[],
  transferId: string,
): { start: Date | null; end: Date } | null {
  const parsed = dates
    .map((r) => ({ id: r.transfer_id, d: parseMemberDate(r.transfer_date) }))
    .filter((r): r is { id: string; d: Date } => r.d != null)
    .map((r) => ({ id: r.id, d: dayOnly(r.d) }))
    .sort((a, b) => a.d.getTime() - b.d.getTime());
  const i = parsed.findIndex((r) => r.id === transferId);
  if (i < 0) return null;
  return { start: i > 0 ? parsed[i - 1].d : null, end: parsed[i].d };
}

/** True when `date` falls inside a transfer cycle's window (start < date <= end; start null = open). */
export function inTransferWindow(date: Date, window: { start: Date | null; end: Date }): boolean {
  const d = dayOnly(date).getTime();
  if (d > dayOnly(window.end).getTime()) return false;
  if (window.start && d <= dayOnly(window.start).getTime()) return false;
  return true;
}
