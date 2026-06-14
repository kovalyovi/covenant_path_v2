// Golden Hour completion — the user-chosen layout: ONE ROW PER ITEM with a status icon.
//   ✓ done (green check)   ○ not done (outline circle)   ⚠ data issue (amber warning)
// N/A items are OMITTED entirely (not eligible — handled upstream in `goldenHourRows`), so this view
// never renders a "N/A" row. The ⚠ row is visibly distinct from both done and not-done.
//
// Used by the person/friend detail view (and the per-person Baptisms card) to show each Golden Hour
// step's status at a glance, alongside the description tooltip from the single milestone definition.

import type { Member } from '../lib/member';
import { goldenHourRows, type GhRow, type Milestone } from '../logic/milestones';
import { Icon } from './Icon';

const GREEN = '#2e7d32';
const AMBER = '#f9a825';
const GREY = 'var(--on-surface-variant)';

/** Render the completion rows for a member. `list` lets a caller include the longer-horizon covenants
 *  (pass `needsCategories`); defaults to the integration milestones. */
export function GoldenHourRows({ member, list }: { member: Member; list?: Milestone[] }) {
  const rows = goldenHourRows(member, list);
  if (rows.length === 0) {
    return <p className="muted small">No Golden Hour steps apply yet.</p>;
  }
  return (
    <ul className="gh-rows" role="list">
      {rows.map((r) => (
        <GoldenHourRow key={r.milestone.abbr} row={r} />
      ))}
    </ul>
  );
}

function GoldenHourRow({ row }: { row: GhRow }) {
  const { milestone: ms, status } = row;
  const { icon, color, label, sr } = statusVisuals(status);
  return (
    <li className={`gh-row gh-row--${status}`} title={`${ms.label} — ${label}. ${ms.description}`}>
      <Icon name={icon} size={18} color={color} title={sr} />
      <span className="gh-row__label">{ms.label}</span>
      <span className="gh-row__status" style={{ color }}>
        {label}
      </span>
    </li>
  );
}

function statusVisuals(status: GhRow['status']): {
  icon: 'check_circle' | 'circle_outline' | 'warning';
  color: string;
  label: string;
  sr: string;
} {
  switch (status) {
    case 'done':
      return { icon: 'check_circle', color: GREEN, label: 'Done', sr: 'Completed' };
    case 'issue':
      // A DATA ISSUE — the value should be known but isn't (sentinel / missing). Distinct from N/A
      // (which is omitted) and from an honest not-done.
      return { icon: 'warning', color: AMBER, label: 'Needs data', sr: 'Data issue — value unavailable' };
    case 'not-done':
    default:
      return { icon: 'circle_outline', color: GREY, label: 'Not yet', sr: 'Not yet completed' };
  }
}
