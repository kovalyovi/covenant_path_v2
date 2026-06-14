// Leadership tab (#12) — per unit: who's serving in the tracked leadership callings, which REQUIRED
// positions are GAPS (ward mission leader, ≥2 ward missionaries, EQ & RS presidents), and the assigned
// full-time missionaries. Reads units.staffing (RLS-scoped per unit by units_select — stake leaders see
// every unit, a ward leader sees only their own) + the missionary roster the dashboard already loaded.

import { useEffect, useState } from 'react';
import { supabase } from '../../lib/supabase';
import { useDashboard } from '../../hooks/useDashboard';
import { useTier, colsFor } from '../../hooks/useTier';
import { staffingGaps, type StaffingMember } from '../../logic/staffing';
import { hexA, status } from '../../theme/tokens';
import { Icon } from '../../components/Icon';
import { SectionCard } from '../../components/ui';
import { PageScaffold, BigHeader, Columns } from '../../components/dashboard';
import { MissionaryStrip } from '../../components/Missionaries';
import { MemberListSkeleton } from '../../components/Skeletons';
import { TabGate } from '../../components/TabGate';

interface UnitRow {
  id: string;
  name: string;
  staffing?: StaffingMember[] | null;
}

export function LeadershipTab() {
  return (
    <TabGate>
      <LeadershipBody />
    </TabGate>
  );
}

function LeadershipBody() {
  const d = useDashboard();
  const tier = useTier();
  const [units, setUnits] = useState<UnitRow[] | null>(null);

  useEffect(() => {
    supabase
      .from('units')
      .select('id, name, staffing')
      .order('name')
      .then(({ data }) => setUnits((data ?? []) as UnitRow[]), () => setUnits([]));
  }, []);

  const header = (
    <BigHeader
      text="Leadership"
      subtitle="Who's serving in each unit, the staffing gaps, and the assigned missionaries"
    />
  );

  if (units == null) {
    return <PageScaffold tier={tier} header={header}><MemberListSkeleton /></PageScaffold>;
  }
  if (units.length === 0) {
    return (
      <PageScaffold tier={tier} header={header}>
        <p style={{ textAlign: 'center', padding: 32 }}>No unit staffing on record yet — it fills on the next sync.</p>
      </PageScaffold>
    );
  }

  return (
    <PageScaffold tier={tier} header={header}>
      <Columns cols={colsFor(tier)}>
        {units.map((u) => (
          <UnitLeadershipCard key={u.id} unit={u} missionaries={d.missionaries[u.name] ?? []} />
        ))}
      </Columns>
    </PageScaffold>
  );
}

function UnitLeadershipCard({ unit, missionaries }: { unit: UnitRow; missionaries: Array<Record<string, unknown>> }) {
  const roster = unit.staffing ?? [];
  const gaps = staffingGaps(roster);
  const missing = gaps.filter((g) => !g.ok).length;
  // Everything we tracked for this unit, sorted, for the "currently serving" list.
  const serving = [...roster].sort((a, b) => a.position.localeCompare(b.position));

  const badge = missing > 0
    ? <span className="chip" style={{ background: hexA(status.danger, 0.14), borderColor: hexA(status.danger, 0.5), color: status.danger, fontSize: 12, fontWeight: 700 }}>
        {missing} gap{missing === 1 ? '' : 's'}
      </span>
    : <span className="chip" style={{ background: hexA(status.success, 0.14), borderColor: hexA(status.success, 0.5), color: status.success, fontSize: 12, fontWeight: 700 }}>
        fully staffed
      </span>;

  return (
    <SectionCard title={unit.name} icon="badge" trailing={badge}>
      {/* Required-role checklist (the gaps the user cares about). */}
      <div className="stack" style={{ gap: 6 }}>
        {gaps.map((g) => (
          <div key={g.key} className="row" style={{ justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
            <span className="row" style={{ gap: 6, alignItems: 'center', minWidth: 0 }}>
              <Icon name={g.ok ? 'check_circle' : 'warning'} size={15} color={g.ok ? status.success : status.danger} />
              <span style={{ fontWeight: 600 }}>{g.label}</span>
              {g.min > 1 && <span className="tiny muted">({g.have}/{g.min})</span>}
            </span>
            <span className="small muted" style={{ textAlign: 'right', minWidth: 0 }}>
              {g.holders.length > 0 ? g.holders.join(', ') : (g.ok ? '' : 'Not filled')}
            </span>
          </div>
        ))}
      </div>

      {serving.length > 0 && (
        <>
          <hr className="divider" />
          <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
            Currently serving
          </div>
          <div className="stack" style={{ gap: 2 }}>
            {serving.map((s, i) => (
              <div key={i} className="row small" style={{ justifyContent: 'space-between', gap: 8 }}>
                <span style={{ minWidth: 0 }}>{s.position}</span>
                <span className="muted" style={{ textAlign: 'right', minWidth: 0 }}>{s.person ?? '—'}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {missionaries.length > 0 && (
        <>
          <hr className="divider" />
          <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
            Missionaries
          </div>
          <MissionaryStrip missionaries={missionaries} />
        </>
      )}
    </SectionCard>
  );
}
