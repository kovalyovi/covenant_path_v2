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
import { SectionCardSkeleton } from '../../components/Skeletons';
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
    // Glimmer the SAME column grid of unit cards the loaded view renders, so staffing cards fade in
    // over their own shapes instead of an avatar-list skeleton (which was the wrong shape here).
    return (
      <PageScaffold tier={tier} header={header}>
        <Columns cols={colsFor(tier)}>
          {Array.from({ length: 6 }, (_, i) => (
            <SectionCardSkeleton key={i} lines={5} titleWidth={150} />
          ))}
        </Columns>
      </PageScaffold>
    );
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

// The LCR ward-leadership/callings page (where a leader fills the gaps). The URL isn't per-unit-
// parameterized by LCR, but a leader lands on their org's leadership list after the unit picker.
const LCR_LEADERSHIP_URL =
  'https://lcr.churchofjesuschrist.org/mlt/orgs?unitTypeId=7,8&list=true&leadership=true&lang=eng';

function UnitLeadershipCard({ unit, missionaries }: { unit: UnitRow; missionaries: Array<Record<string, unknown>> }) {
  const roster = unit.staffing ?? [];
  const gaps = staffingGaps(roster);
  const missing = gaps.filter((g) => !g.ok).length;

  const badge = missing > 0
    ? <span className="chip" style={{ background: hexA(status.danger, 0.14), borderColor: hexA(status.danger, 0.5), color: status.danger, fontSize: 12, fontWeight: 700 }}>
        {missing} gap{missing === 1 ? '' : 's'}
      </span>
    : <span className="chip" style={{ background: hexA(status.success, 0.14), borderColor: hexA(status.success, 0.5), color: status.success, fontSize: 12, fontWeight: 700 }}>
        fully staffed
      </span>;

  return (
    <SectionCard title={unit.name} icon="badge" trailing={badge}>
      {/* Required-role checklist: the calling on the LEFT, just a green CHECK when it's filled, or
          "Not filled" (warning) when it's a gap. No counts, no holder names (#leaders). */}
      <div className="stack" style={{ gap: 6 }}>
        {gaps.map((g) => (
          <div key={g.key} className="row" style={{ justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
            <span style={{ fontWeight: 600, minWidth: 0 }}>{g.label}</span>
            {g.ok ? (
              <Icon name="check_circle" size={17} color={status.success} />
            ) : (
              <span className="row small" style={{ gap: 5, alignItems: 'center', color: status.danger, fontWeight: 600 }}>
                <Icon name="warning" size={15} color={status.danger} /> Not filled
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Missionaries — ALWAYS shown; a warning when none are assigned to the unit. */}
      <hr className="divider" />
      <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
        Missionaries
      </div>
      {missionaries.length > 0 ? (
        <MissionaryStrip missionaries={missionaries} />
      ) : (
        <div className="row small" style={{ gap: 6, alignItems: 'center', color: status.warning }}>
          <Icon name="warning" size={15} color={status.warning} /> No missionaries assigned to this unit
        </div>
      )}

      {/* Per-unit deeplink to LCR's leadership page (to view/fill callings). */}
      <hr className="divider" />
      <a
        className="row small"
        href={LCR_LEADERSHIP_URL}
        target="_blank"
        rel="noopener noreferrer"
        style={{ gap: 5, alignItems: 'center', color: 'var(--primary)', fontWeight: 600 }}
      >
        <Icon name="open_in_new" size={15} /> {unit.name} leadership in LCR
      </a>
    </SectionCard>
  );
}
