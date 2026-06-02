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
  { path: 'table', label: 'Table', icon: 'grid_on', color: '#5E35B1' },
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
