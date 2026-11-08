// Design tokens — the single source of nav/status/org colors so components compose from a shared
// vocabulary (mirrors apps/viewer/lib/theme/tokens.dart + the per-tab nav palette in dashboard_page.dart).

/** Semantic status colors (meaning-named, not hue-named). */
export const status = {
  success: '#2E7D32',
  successFg: '#43A047',
  warning: '#EF6C00',
  info: '#1E88E5',
  danger: '#E53935',
  neutral: '#616161',
} as const;

/** Data-table cell fills (Yes / No / N-A / recommend-expired) — centralized here (#6a) so the one set
 *  of values is shared instead of re-declared in each view. These are FILL backgrounds (3:1 against the
 *  adjacent surface is the bar to clear), with dark text on top. */
export const cell = {
  yes: '#c8e6c9',
  no: '#ffcdd2',
  na: '#e0e0e0',
  amber: '#ffe082',
} as const;

/** The sacrament-attendance health level → a semantic status hue. One mapping, shared by the pill and
 *  the detail timeline (#1e/#10b). `level` is the pure logic value from `logic/kpis.attendanceBucket`. */
export function attendanceColor(level: 'great' | 'fair' | 'poor' | 'none' | 'unknown'): string {
  switch (level) {
    case 'great': return status.success;
    case 'fair': return status.warning;
    case 'poor':
    case 'none': return status.danger;
    case 'unknown': return status.neutral;
  }
}

/** The 5 dashboard tabs — each carries its own accent so the nav reads at a glance (#nav). */
export interface TabDef {
  path: string;
  label: string;
  icon: string;
  color: string;
}

export const TABS: TabDef[] = [
  { path: 'baptisms', label: 'Baptisms', icon: 'event_available', color: '#0277BD' },
  { path: 'golden-hour', label: 'Golden Hour', icon: 'timelapse', color: '#F9A825' },
  { path: 'needs', label: 'Needs', icon: 'checklist', color: '#D84315' },
  { path: 'kpis', label: 'KPIs', icon: 'insights', color: '#2E7D32' },
  // Families (part-member families, Turley proposal) replaced Table + Leaders in the tab bar
  // (2026-11-08): Table and Leaders now live in Settings. The tab bar shows ALL five tabs, always
  // — never hidden behind an overflow/"more" menu, and the mobile bottom nav never hides on scroll.
  { path: 'families', label: 'Families', icon: 'groups', color: '#6A1B9A' },
  // "By Month" is no longer its own tab — the chart now lives at the bottom of KPIs (#1).
];

/** Soft tinted background for a status pill/tag of [hex] (alpha ~0.12, like AppColors.tint). */
export function tint(hex: string, alpha = 0.12): string {
  return hexA(hex, alpha);
}

/** A hex color with an alpha channel, e.g. hexA('#1565C0', 0.2) -> 'rgba(21,101,192,0.2)'. */
export function hexA(hex: string, alpha: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
