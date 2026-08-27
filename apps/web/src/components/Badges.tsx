// Compact shared badges used on every person card so the same information reads identically across
// Needs / Golden Hour / Baptisms / detail (the plan's "build once" primitives):
//   • OrgBadge       — WML/RS/EQ SHORTHAND + org color + a tooltip carrying the full label (#1d/#8c/#8.1c/#3)
//   • AttendancePill — recent sacrament-attendance health (#1e); 0 is BOLD with a red ⓘ (non-color cue)
import { responsibleOrg, orgInfo, type OrgBucket } from '../logic/milestones';
import { memberAttendance, attendanceCadence, type AttendanceBucket } from '../logic/kpis';
import type { Member } from '../lib/member';
import { hexA, attendanceColor } from '../theme/tokens';
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

/** Sacrament-attendance pill (#1e): "Sacrament 7/8" colored by health. The 0 case is BOLD with a red
 *  ⓘ glyph (so it's not signalled by color alone — WCAG 1.4.1). `unknown` (no data) renders nothing in
 *  compact rows. Pass an explicit `bucket` or a `member` to derive it from `details.sacrament`. */
export function AttendancePill({ bucket, member }: { bucket?: AttendanceBucket; member?: Member }) {
  const b = bucket ?? (member ? memberAttendance(member) : null);
  if (!b || b.level === 'unknown') return null;
  const color = attendanceColor(b.level);
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

/** Attendance CADENCE indicator: the rhythm ("Weekly", "Most weeks", "Occasional", "Not attending")
 *  plus a trend arrow when the recent half of the window differs from the older half. This answers
 *  what the bare count can't — a 4/8 who came the LAST four Sundays and a 4/8 who came the first four
 *  and stopped read identically as a count, but are opposite pastoral situations. The arrow is backed
 *  by text in the tooltip + aria-label, never colour alone (WCAG 1.4.1). Renders nothing with no data. */
export function AttendanceCadenceBadge({ member }: { member: Member }) {
  const c = attendanceCadence(member);
  if (c.level === 'unknown') return null;
  const color = attendanceColor(c.level);
  const arrow = c.trend === 'improving' ? 'arrow_up' : c.trend === 'declining' ? 'arrow_down' : null;
  const trendText = c.trend === 'improving' ? 'trending up'
    : c.trend === 'declining' ? 'trending down'
      : c.trend === 'steady' ? 'holding steady' : '';
  const full = `${c.label} — ${c.detail}${trendText ? ` · ${trendText}` : ''}`;
  return (
    <span
      className="chip"
      title={full}
      aria-label={`Attendance cadence: ${full}`}
      style={{
        gap: 4, padding: '1px 8px', fontSize: 11, fontWeight: 700, lineHeight: 1.7,
        background: hexA(color, 0.12), borderColor: hexA(color, 0.4), color,
      }}
    >
      {c.label}
      {arrow && <Icon name={arrow as IconName} size={12} color={color} />}
    </span>
  );
}

/** The last few Sundays as a dot strip, newest LAST so it reads left-to-right like a timeline.
 *  A filled dot = present, hollow = missed. Gives the cadence a shape at a glance. */
export function AttendanceDots({ member, size = 7 }: { member: Member; size?: number }) {
  const c = attendanceCadence(member);
  if (c.total === 0) return null;
  const color = attendanceColor(c.level);
  const oldestFirst = [...c.recent].reverse();
  return (
    <span
      className="row"
      title={c.detail}
      aria-label={`${c.detail}, oldest to newest`}
      style={{ gap: 3, alignItems: 'center' }}
    >
      {oldestFirst.map((present, i) => (
        <span
          key={i}
          aria-hidden="true"
          style={{
            width: size, height: size, borderRadius: '50%',
            background: present ? color : 'transparent',
            border: `1px solid ${present ? color : hexA(color, 0.45)}`,
          }}
        />
      ))}
    </span>
  );
}
