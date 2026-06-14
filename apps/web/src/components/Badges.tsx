// Compact shared badges used on every person card so the same information reads identically across
// Needs / Golden Hour / Baptisms / detail (the plan's "build once" primitives):
//   • OrgBadge       — WML/RS/EQ SHORTHAND + org color + a tooltip carrying the full label (#1d/#8c/#8.1c/#3)
//   • AttendancePill — recent sacrament-attendance health (#1e); 0 is BOLD with a red ⓘ (non-color cue)
import { responsibleOrg, orgInfo, type OrgBucket } from '../logic/milestones';
import { memberAttendance, type AttendanceBucket, type AttendanceLevel } from '../logic/kpis';
import type { Member } from '../lib/member';
import { status, hexA } from '../theme/tokens';
import { Icon, type IconName } from './Icon';

/** WML/RS/EQ shorthand badge: the org color + a "SHORT — Long" tooltip (hover + screen-reader label).
 *  Pass an explicit `org`, or a `member` to derive it from the convert-responsibility rule. Renders
 *  nothing when there's no responsible org (e.g. no baptism date yet). */
export function OrgBadge({ org, member }: { org?: OrgBucket | null; member?: Member }) {
  const b = org ?? (member ? responsibleOrg(member) : null);
  if (!b) return null;
  const i = orgInfo(b);
  return (
    <span
      className="chip"
      title={`${i.short} — ${i.label}`}
      aria-label={`${i.short} — ${i.label}`}
      style={{
        gap: 4, padding: '1px 8px', fontSize: 11, fontWeight: 700, lineHeight: 1.7,
        background: hexA(i.color, 0.12), borderColor: hexA(i.color, 0.4), color: i.color,
      }}
    >
      <Icon name={i.icon as IconName} size={12} color={i.color} />
      {i.short}
    </span>
  );
}

/** Map the (theme-independent) attendance level to a semantic status color here in the UI layer. */
const ATT_COLOR: Record<AttendanceLevel, string> = {
  great: status.success,
  fair: status.warning,
  poor: status.danger,
  none: status.danger,
  unknown: status.neutral,
};

/** Sacrament-attendance pill (#1e): "Sacrament 7/8" colored by health. The 0 case is BOLD with a red
 *  ⓘ glyph (so it's not signalled by color alone — WCAG 1.4.1). `unknown` (no data) renders nothing in
 *  compact rows. Pass an explicit `bucket` or a `member` to derive it from `details.sacrament`. */
export function AttendancePill({ bucket, member }: { bucket?: AttendanceBucket; member?: Member }) {
  const b = bucket ?? (member ? memberAttendance(member) : null);
  if (!b || b.level === 'unknown') return null;
  const color = ATT_COLOR[b.level];
  const attention = b.level === 'none';
  return (
    <span
      className="row"
      title={`Sacrament: present ${b.label} of the recent weeks`}
      aria-label={`Sacrament attendance ${b.label}${attention ? ', none — needs attention' : ''}`}
      style={{ gap: 4, color, fontWeight: b.bold ? 800 : 600, fontSize: 12, alignItems: 'center' }}
    >
      <Icon name={attention ? 'info' : 'event_available'} size={13} color={color} />
      <span>Sacrament {b.label}</span>
    </span>
  );
}
