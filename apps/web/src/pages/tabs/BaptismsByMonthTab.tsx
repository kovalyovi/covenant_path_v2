// "By Month" tab (the last tab) — baptized-convert counts by baptism month, with its own window
// filter that defaults to year-to-date. React port of _BaptismsByMonthView
// (apps/viewer/lib/views/baptisms_by_month_view.dart). Adds a stake-wide unit filter on top of the
// card's own YTD / 12 mo / 24 mo / All window. Chart + by-unit drill come from BaptismsCard.

import { useState } from 'react';
import { useDashboard } from '../../hooks/useDashboard';
import { useTier } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { baptismsByMonth, type BWindow } from '../../logic/kpis';
import { Icon } from '../../components/Icon';
import { SectionCard, Segmented } from '../../components/ui';
import { PageScaffold, BigHeader } from '../../components/dashboard';
import { TrendLine } from '../../components/TrendLine';
import { TabGate } from '../../components/TabGate';
import { DrillHost, type Drill } from '../../components/DrillSheet';

export function BaptismsByMonthTab() {
  return (
    <TabGate>
      <BaptismsByMonthBody />
    </TabGate>
  );
}

function BaptismsByMonthBody() {
  const d = useDashboard();
  const tier = useTier();
  const [unit, setUnit] = useState<string | null>(null);
  const [drill, setDrill] = useState<Drill | null>(null);

  const units = [...new Set(d.members.map((m) => String(m['unit_name'] ?? '')).filter(Boolean))].sort();
  const rows = unit == null ? d.members : d.members.filter((m) => m['unit_name'] === unit);
  const baptized = rows.filter((m) => !isInvestigator(m));
  const allUnits = new Set(rows.map((m) => String(m['unit_name'] ?? '—')));

  return (
    <>
      <PageScaffold
        tier={tier}
        header={
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <BigHeader text="Baptisms by Month" subtitle="Baptized & confirmed converts" />
            </div>
            {units.length > 1 && (
              <select
                className="select"
                style={{ width: 'auto' }}
                value={unit ?? ''}
                onChange={(e) => setUnit(e.target.value || null)}
                aria-label="Unit"
              >
                <option value="">All units</option>
                {units.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            )}
          </div>
        }
      >
        <div style={{ maxWidth: 640, margin: '0 auto' }}>
          <BaptismsCard baptized={baptized} allUnits={allUnits} onDrill={setDrill} />
        </div>
      </PageScaffold>
      <DrillHost drill={drill} onClose={() => setDrill(null)} />
    </>
  );
}

// ---- Baptisms by month (#1/#2) — own window selector, defaults to YTD --------------------------

function BaptismsCard({
  baptized,
  allUnits,
  onDrill,
}: {
  baptized: Member[];
  allUnits: Set<string>;
  onDrill: (d: Drill) => void;
}) {
  const [w, setW] = useState<BWindow>('ytd'); // default to year-to-date
  const color = '#0277BD';
  const d = baptismsByMonth(baptized, w);
  return (
    <SectionCard
      title="Baptisms by month"
      icon="water_drop"
      iconColor={color}
      onClick={d.events.length === 0 ? undefined : () => onDrill({ kind: 'metric', title: 'Baptisms', events: d.events, allUnits })}
    >
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <Segmented<BWindow>
          ariaLabel="Baptisms window"
          value={w}
          onChange={setW}
          options={[
            { value: 'ytd', label: 'YTD' },
            { value: 'm12', label: '12 mo' },
            { value: 'm24', label: '24 mo' },
            { value: 'all', label: 'All' },
          ]}
        />
      </div>
      <div style={{ height: 14 }} />
      <div className="row" style={{ alignItems: 'stretch' }}>
        <Kv label="Baptized in window" value={String(d.total)} />
        <div style={{ width: 1, background: 'var(--outline-variant)', margin: '0 14px' }} />
        <Kv label="Best month" value={d.bestLabel == null ? '—' : `${d.bestLabel}  ·  ${d.bestCount}`} />
      </div>
      <div style={{ height: 14 }} />
      <TrendLine
        values={d.counts}
        labels={d.labels}
        color={color}
        onBucketTap={(i) =>
          onDrill({
            kind: 'metric',
            title: 'Baptisms',
            events: d.events.filter((e) => e.bucket === i),
            allUnits,
            bucketLabel: i < d.labels.length ? d.labels[i] : null,
          })
        }
      />
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 4 }}>
        <span className="small muted">Baptized & confirmed converts, counted by baptism month.</span>
        <button
          type="button"
          className="btn btn--text"
          disabled={d.events.length === 0}
          onClick={(e) => {
            e.stopPropagation();
            onDrill({ kind: 'metric', title: 'Baptisms', events: d.events, allUnits });
          }}
        >
          <Icon name="groups" size={16} />
          By unit
        </button>
      </div>
    </SectionCard>
  );
}

function Kv({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ flex: 1 }}>
      <div className="small muted">{label}</div>
      <div style={{ fontWeight: 700, fontSize: '1rem', marginTop: 2 }}>{value}</div>
    </div>
  );
}
