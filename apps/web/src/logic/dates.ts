// Date parsing + formatting ported from apps/viewer/lib (dashboard_common.dart, golden_hour.dart).
// LCR sends dates in several string shapes; this is the part most likely to silently misbehave,
// so it mirrors the Dart logic (and the Flutter `dashboard_dates_test`) exactly.

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

const FULL_MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const WEEKDAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Parse an ISO `YYYY-MM-DD` string into a *local* midnight Date (matches Dart's DateTime.parse
 * for date-only strings, which yields local time — important so day math is timezone-stable). */
function parseIsoDateLocal(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$/.exec(s);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  return new Date(y, mo - 1, d);
}

/**
 * Parse a member date across LCR's formats: ISO (`2026-02-06`), `6 Feb 2026` / `06 Feb 2026`,
 * and `MM/dd/yy(yy)`. Returns null for blanks and the `N/A` / `needs-profile-api` sentinels.
 * Mirrors `parseMemberDate` in dashboard_common.dart.
 */
export function parseMemberDate(v: unknown): Date | null {
  if (v == null) return null;
  const s = String(v).trim();
  if (s === '' || s === 'N/A' || s === 'needs-profile-api') return null;

  const iso = parseIsoDateLocal(s);
  if (iso) return iso;

  // "6 Feb 2026" / "06 February 2026"
  const m = /^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$/.exec(s);
  if (m) {
    const mo = MONTHS.findIndex((x) => x.toLowerCase() === m[2].toLowerCase().slice(0, 3));
    if (mo >= 0) return new Date(Number(m[3]), mo, Number(m[1]));
  }

  // "MM/dd/yy" or "MM/dd/yyyy"
  const m2 = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(s);
  if (m2) {
    let y = Number(m2[3]);
    if (y < 100) y += 2000;
    return new Date(y, Number(m2[1]) - 1, Number(m2[2]));
  }
  return null;
}

/** First 4-digit year found in a value (used for by-year age), or null. */
export function yearOf(v: unknown): number | null {
  const m = /(\d{4})/.exec(v == null ? '' : String(v));
  return m ? Number(m[1]) : null;
}

/** Date-only (drop time). */
export function dayOnly(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Monday-start week for a date. */
export function weekStart(d: Date): Date {
  const day = dayOnly(d);
  const weekday = day.getDay(); // 0=Sun..6=Sat
  const isoWeekday = weekday === 0 ? 7 : weekday; // 1=Mon..7=Sun
  day.setDate(day.getDate() - (isoWeekday - 1));
  return day;
}

/** Whole days from a → b (b - a), using calendar days (DST-safe). */
export function daysBetween(a: Date, b: Date): number {
  const ms = dayOnly(b).getTime() - dayOnly(a).getTime();
  return Math.round(ms / 86_400_000);
}

/** Full human-readable date e.g. "Friday, February 6, 2026". Empty for null. Mirrors `fmtLong`. */
export function fmtLong(d: Date | null): string {
  if (d == null) return '';
  return `${WEEKDAYS[d.getDay()]}, ${FULL_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

/** "MMMM d, y" e.g. "February 6, 2026". */
export function fmtMonthDayYear(d: Date): string {
  return `${FULL_MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

/** "MMM" e.g. "Feb". */
export function fmtMonShort(d: Date): string {
  return MONTHS[d.getMonth()];
}

/** "EEE" e.g. "Fri". */
export function fmtWeekdayShort(d: Date): string {
  return WEEKDAYS_SHORT[d.getDay()];
}

/** "M/d" e.g. "2/6". */
export function fmtMonthDay(d: Date): string {
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** "MMM y" e.g. "Feb 2026". */
export function fmtMonYear(d: Date): string {
  return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "MMMM y" e.g. "February 2026". */
export function fmtFullMonYear(d: Date): string {
  return `${FULL_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "MMM d, y · h:mm a" — exact local timestamp for freshness dialogs. */
export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  let h = d.getHours();
  const ampm = h < 12 ? 'AM' : 'PM';
  h = h % 12 === 0 ? 12 : h % 12;
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()} · ${h}:${mm} ${ampm}`;
}

/**
 * Today's instant for an ET (America/New_York) wall-clock hour. The daily-sync schedule is stored
 * as an ET hour (`stake_settings.sync_hour_et` — the cron gate runs in ET); clients DISPLAY it in
 * the viewer's local time. DST-safe: derived from the live ET offset, no hardcoded -5/-4.
 */
export function etHourToday(hourET: number): Date {
  const now = new Date();
  // ET wall clock "now", reparsed as if local — only the field DIFFERENCE to the target is used.
  const etWall = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const ms =
    ((hourET - etWall.getHours()) * 60 - etWall.getMinutes()) * 60_000 - etWall.getSeconds() * 1_000;
  return new Date(now.getTime() + ms);
}

/** An ET schedule hour as the viewer's local wall-clock time, e.g. ET 7 → "5:00 AM" in MT. */
export function fmtEtHourLocal(hourET: number): string {
  const d = etHourToday(hourET);
  let h = d.getHours();
  const ampm = h < 12 ? 'AM' : 'PM';
  h = h % 12 === 0 ? 12 : h % 12;
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${h}:${mm} ${ampm}`;
}

/**
 * Compact elapsed time since a past date, e.g. "2 months 3 days" (or "3 days"). Empty for a
 * future/unknown date. Mirrors `monthsDaysAgo` in golden_hour.dart (incl. the day-borrow logic).
 */
export function monthsDaysAgo(d: Date | null): string {
  if (d == null) return '';
  const now = new Date();
  if (d.getTime() > now.getTime()) return '';
  let months = (now.getFullYear() - d.getFullYear()) * 12 + now.getMonth() - d.getMonth();
  let days: number;
  if (now.getDate() >= d.getDate()) {
    days = now.getDate() - d.getDate();
  } else {
    months -= 1;
    // day 0 of the current month = last day of the previous month
    const daysInPrevMonth = new Date(now.getFullYear(), now.getMonth(), 0).getDate();
    days = daysInPrevMonth - d.getDate() + now.getDate();
  }
  if (months < 0) return '';
  const parts: string[] = [];
  if (months > 0) parts.push(`${months} month${months === 1 ? '' : 's'}`);
  if (days > 0 || months === 0) parts.push(`${days} day${days === 1 ? '' : 's'}`);
  return parts.join(' ');
}

/**
 * Coarse elapsed time since a past date for the BAPTISM display: months only once a member is at
 * least a month in (e.g. "3 months", not "3 months 12 days"); days only under a month ("5 days").
 * Empty for a future/unknown date. Built on `monthsDaysAgo` so the month/day-borrow math stays in
 * one place; this just drops the trailing days once the month count is non-zero (#baptism-display).
 */
export function baptismElapsed(d: Date | null): string {
  const full = monthsDaysAgo(d);
  if (full === '') return '';
  // monthsDaysAgo emits "N month(s) M day(s)" once N>0; "M day(s)" under a month. Keep only the
  // months segment when present, otherwise keep the days segment unchanged.
  const monthsMatch = /^(\d+ months?)/.exec(full);
  return monthsMatch ? monthsMatch[1] : full;
}

/** "2h ago" relative label for a last-synced ISO. Mirrors `_ago`. */
export function ago(iso: unknown): string {
  if (iso == null) return String(iso);
  const t = new Date(String(iso));
  if (Number.isNaN(t.getTime())) return String(iso);
  const diffMin = Math.floor((Date.now() - t.getTime()) / 60_000);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}

/** Admin-style "ago" with "never" / "just now". Mirrors admin_page `_ago`. */
export function agoOrNever(iso: unknown): string {
  if (iso == null) return 'never';
  const t = new Date(String(iso));
  if (Number.isNaN(t.getTime())) return String(iso);
  const diffMin = Math.floor((Date.now() - t.getTime()) / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.floor(diffH / 24)}d ago`;
}

/** Human duration for a job's execution time (seconds → "45s", "2m 13s", "1h 4m"). Mirrors `_dur`. */
export function dur(seconds: unknown): string {
  const s = typeof seconds === 'number' ? Math.trunc(seconds) : Number.parseInt(String(seconds ?? ''), 10);
  if (Number.isNaN(s) || s < 0) return '';
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), rs = s % 60;
  if (m < 60) return rs === 0 ? `${m}m` : `${m}m ${rs}s`;
  const h = Math.floor(m / 60), rm = m % 60;
  return rm === 0 ? `${h}h` : `${h}h ${rm}m`;
}

export type Staleness = 'fresh' | 'warn' | 'stale';

/**
 * Staleness bucket for a last-synced timestamp (#18): warn after 2 days, stale after 2 weeks,
 * fresh otherwise; an unparseable/never value reads as stale. Mirrors `_staleColor`.
 */
export function staleness(iso: unknown): Staleness {
  const t = new Date(String(iso ?? ''));
  if (Number.isNaN(t.getTime())) return 'stale';
  const days = Math.floor((Date.now() - t.getTime()) / 86_400_000);
  if (days >= 14) return 'stale';
  if (days >= 2) return 'warn';
  return 'fresh';
}
