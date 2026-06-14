// Full-time / assigned missionaries, surfaced from the stake's synced `missionaries` map (keyed by
// UNIT NAME — the data the daily sync already stores on `stakes.missionaries`). These are the ward's
// assigned missionaries; we do NOT have a per-person "who teaches THIS investigator" link in the
// synced data, so we surface the assigned missionaries for the person's UNIT as the best available
// answer (see the data-availability note in the change report).

import { useDashboard } from '../hooks/useDashboard';
import { hexA } from '../theme/tokens';
import { Icon } from './Icon';
import { Avatar, SectionCard } from './ui';

export type MissionaryRec = Record<string, unknown>;

/** The assigned missionaries for a unit (by unit name), or [] when none are synced for it. */
export function useUnitMissionaries(unitName: string | null | undefined): MissionaryRec[] {
  const { missionaries } = useDashboard();
  if (!unitName) return [];
  return missionaries[unitName] ?? [];
}

function contactOf(m: MissionaryRec): string {
  return [m['phone'], m['email']].filter((x) => x != null && String(x).length > 0).join('\n');
}

/** A compact chip row of missionary names (used inside a person card / unit card). */
export function MissionaryStrip({ missionaries }: { missionaries: MissionaryRec[] }) {
  if (missionaries.length === 0) return null;
  return (
    <div className="row" style={{ alignItems: 'flex-start', gap: 6 }}>
      <Icon name="volunteer" size={16} color="var(--primary)" />
      <div className="wrap" style={{ gap: 6 }}>
        {missionaries.map((m, i) => (
          <span
            key={i}
            className="chip"
            title={contactOf(m)}
            style={{ background: hexA('#4554b8', 0.1), border: 'none', color: 'var(--primary)', fontSize: 12 }}
          >
            {String(m['name'] ?? '')}
          </span>
        ))}
      </div>
    </div>
  );
}

/** A detail-style list of a unit's missionaries with contact lines (used in the person detail view).
 *  Renders a clean empty state when none are assigned/synced for the unit. */
export function MissionariesSection({
  unitName,
  title = 'Full-Time Missionaries',
}: {
  unitName: string | null | undefined;
  title?: string;
}) {
  const list = useUnitMissionaries(unitName);
  return (
    <SectionCard title={title} icon="volunteer">
      {list.length === 0 ? (
        <p className="muted">
          No assigned missionaries on record for {unitName ? `${unitName}.` : 'this unit.'}
        </p>
      ) : (
        <div className="stack">
          {list.map((m, i) => {
            const phone = m['phone'] != null ? String(m['phone']) : '';
            const email = m['email'] != null ? String(m['email']) : '';
            return (
              <div key={i} className="row" style={{ padding: '4px 0', alignItems: 'flex-start' }}>
                <Avatar name={String(m['name'] ?? '?')} size={32} />
                <div style={{ minWidth: 0 }}>
                  <div>{String(m['name'] ?? '—')}</div>
                  {phone && (
                    <a className="small muted" href={`tel:${phone}`} style={{ display: 'block' }}>
                      {phone}
                    </a>
                  )}
                  {email && (
                    <a className="small muted" href={`mailto:${email}`} style={{ display: 'block', wordBreak: 'break-all' }}>
                      {email}
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}
