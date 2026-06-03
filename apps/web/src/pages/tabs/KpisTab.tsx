// KPIs tab — stake metrics from this stake's own covenant-path data. React port of kpis_view.dart:
//   • Baptisms by month (#1/#2) — convert cohort by baptism month over YTD/12mo/24mo/All + best month
//   • Investigators / New Members at Sacrament — attendance bucketed by the page period (line charts)
//   • New Friends Being Taught — first-lesson starts in the period
//   • Overview stat grid + which unit integrates converts best (#26)
// Each chart card overlays the previous equal window (compare toggle) and drills by unit/date.

import { useState } from 'react';
import { useDashboard } from '../../hooks/useDashboard';
import { useTier, colsFor } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate, fmtMonShort, fmtMonYear } from '../../logic/dates';
import { avgCompletion } from '../../logic/milestones';
import {
  metricData, attendedDates, firstLessonDate, lessonsWithMember,
  membersWithMemberLessons, unitCompletion, type Period, type Ev, type Series,
} from '../../logic/kpis';
import { Icon, type IconName } from '../../components/Icon';
import { SectionCard, Segmented, RangePill, Progress } from '../../components/ui';
import { PageScaffold, BigHeader, Columns } from '../../components/dashboard';
import { TrendLine } from '../../components/TrendLine';
import { TabGate } from '../../components/TabGate';
import { DrillHost, type Drill } from '../../components/DrillSheet';
import { hexA } from '../../theme/tokens';

export function KpisTab() {
  return (
    <TabGate>
      <KpisBody />
    </TabGate>
  );
}

function KpisBody() {
  const d = useDashboard();
  const tier = useTier();
  const [period, setPeriod] = useState<Period>('month');
  const [unit, setUnit] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const [drill, setDrill] = useState<Drill | null>(null);

  const units = [...new Set(d.members.map((m) => String(m['unit_name'] ?? '')).filter(Boolean))].sort();
  const rows = unit == null ? d.members : d.members.filter((m) => m['unit_name'] === unit);
  const baptized = rows.filter((m) => !isInvestigator(m));
  const investigators = rows.filter(isInvestigator);
  const allUnits = new Set(rows.map((m) => String(m['unit_name'] ?? '—')));

  const friendsAtSac = metricData(investigators, attendedDates, period);
  const newAtSac = metricData(baptized, attendedDates, period);
  const newFriends = metricData(investigators, firstLessonDate, period);
  const lessons = lessonsWithMember(rows);
  const completion = avgCompletion(baptized);

  const compareLabels: [string, string] =
    period === 'month' ? ['Last month', 'This month'] : period === 'year' ? ['Last year', 'This year'] : ['Prev. month', 'This month'];

  function periodRangeLabel(): string | null {
    const now = new Date();
    if (period === 'month') {
      const from = new Date(now.getTime() - 35 * 86_400_000);
      return `${fmtMonShort(from)} ${from.getDate()} – ${fmtMonShort(now)} ${now.getDate()}, ${now.getFullYear()}`;
    }
    if (period === 'year') {
      const from = new Date(now.getFullYear(), now.getMonth() - 11, 1);
      return `${fmtMonYear(from)} – ${fmtMonYear(now)}`;
    }
    return null;
  }

  function evs(ms: Member[], dateField: string): Ev[] {
    return ms.map((m) => ({ m, date: parseMemberDate(m[dateField]) ?? new Date(), bucket: 0 }));
  }

  const rangeLabel = periodRangeLabel();

  const cards: React.ReactNode[] = [
    // "Baptisms by month" now lives in its own dedicated tab (the last one) — see BaptismsByMonthTab.
    <MetricCard
      key="friends-sac"
      title="Investigators at Sacrament"
      icon="groups"
      color="#fb8c00"
      series={friendsAtSac.series}
      events={friendsAtSac.events}
      allUnits={allUnits}
      compareLabels={compareLabels}
      showCompare={compare}
      suffix="people being taught who attended sacrament"
      onDrill={setDrill}
    />,
    <MetricCard
      key="new-sac"
      title="New Members at Sacrament"
      icon="favorite"
      color="#B5532A"
      series={newAtSac.series}
      events={newAtSac.events}
      allUnits={allUnits}
      compareLabels={compareLabels}
      showCompare={compare}
      suffix="baptized members who attended sacrament"
      onDrill={setDrill}
    />,
    <MetricCard
      key="new-friends"
      title="New Friends Being Taught"
      icon="library"
      color="#00897B"
      series={newFriends.series}
      events={newFriends.events}
      allUnits={allUnits}
      compareLabels={compareLabels}
      showCompare={compare}
      suffix="people who started lessons in the period"
      onDrill={setDrill}
    />,
    <StatGridCard
      key="overview"
      items={[
        {
          label: 'Being taught now',
          value: String(investigators.length),
          onClick: () =>
            setDrill({ kind: 'metric', title: 'Being taught now', events: evs(investigators, 'baptism_goal_date'), allUnits }),
        },
        {
          label: 'Lessons w/ member present',
          value: String(lessons),
          onClick: () => setDrill({ kind: 'lessons', people: membersWithMemberLessons(rows) }),
        },
        {
          label: 'New members tracked',
          value: String(baptized.length),
          onClick: () =>
            setDrill({ kind: 'metric', title: 'New members tracked', events: evs(baptized, 'baptism_date'), allUnits }),
        },
        {
          label: 'Golden Hour',
          value: `${Math.round(completion * 100)}%`,
          onClick: () => setDrill({ kind: 'gh', rows: baptized }),
        },
      ]}
    />,
    unit == null && units.length > 1 ? (
      <UnitCompletionCard key="unit-completion" rows={baptized} onSelectUnit={setUnit} />
    ) : null,
  ];

  return (
    <>
      <PageScaffold
        tier={tier}
        header={
          <div className="stack" style={{ gap: 8 }}>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <BigHeader text="KPIs" subtitle="From this stake's covenant-path data" />
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
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <Segmented<Period>
                ariaLabel="Period"
                value={period}
                onChange={setPeriod}
                options={[
                  { value: 'month', label: 'Month' },
                  { value: 'year', label: 'Year' },
                  { value: 'all', label: 'All' },
                ]}
              />
            </div>
            {rangeLabel && (
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <RangePill text={rangeLabel} />
              </div>
            )}
            {period !== 'all' && (
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <button
                  type="button"
                  className="chip"
                  aria-pressed={compare}
                  onClick={() => setCompare((c) => !c)}
                  style={compare ? { background: 'var(--secondary-container)', color: 'var(--on-secondary-container)', borderColor: 'transparent' } : undefined}
                >
                  <Icon name="compare" size={18} color={compare ? 'var(--primary)' : undefined} />
                  Compare to previous
                </button>
              </div>
            )}
          </div>
        }
      >
        <Columns cols={Math.min(2, colsFor(tier))}>{cards}</Columns>
      </PageScaffold>
      <DrillHost drill={drill} onClose={() => setDrill(null)} />
    </>
  );
}

// ---- Metric chart card ------------------------------------------------------------------------

function MetricCard({
  title,
  icon,
  color,
  series,
  events,
  allUnits,
  compareLabels,
  showCompare,
  suffix,
  onDrill,
}: {
  title: string;
  icon: IconName;
  color: string;
  series: Series;
  events: Ev[];
  allUnits: Set<string>;
  compareLabels: [string, string];
  showCompare: boolean;
  suffix: string;
  onDrill: (d: Drill) => void;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const values = series.current;
  const last = values.length > 0 ? values[values.length - 1] : null;
  const prior = values.length >= 2 ? values[values.length - 2] : null;
  const delta = last != null && prior != null ? last - prior : null;

  return (
    <SectionCard
      title={title}
      icon={icon}
      iconColor={color}
      trailing={delta == null ? undefined : <DeltaBadge delta={delta} />}
      onClick={events.length === 0 ? undefined : () => onDrill({ kind: 'metric', title, events, allUnits })}
    >
      {last != null && prior != null && (
        <>
          <div className="row" style={{ alignItems: 'stretch' }}>
            <BigStat label={compareLabels[0]} v={prior} />
            <div style={{ width: 1, background: 'var(--outline-variant)', margin: '0 14px' }} />
            <BigStat label={compareLabels[1]} v={last} />
          </div>
          <div style={{ height: 16 }} />
        </>
      )}
      <TrendLine
        values={values}
        labels={series.labels}
        color={color}
        prev={showCompare ? series.prev : []}
        onHover={setHovered}
        onBucketTap={(i) =>
          onDrill({
            kind: 'metric',
            title,
            events: events.filter((e) => e.bucket === i),
            allUnits,
            bucketLabel: i < series.labels.length ? series.labels[i] : null,
          })
        }
      />
      <HoverSummary series={series} events={events} hovered={hovered} color={color} />
      <div className="row" style={{ justifyContent: 'space-between', marginTop: 4 }}>
        <span className="small muted">{suffix}</span>
        <button
          type="button"
          className="btn btn--text"
          onClick={(e) => {
            e.stopPropagation();
            onDrill({ kind: 'metric', title, events, allUnits });
          }}
        >
          <Icon name="groups" size={16} />
          By unit
        </button>
      </div>
    </SectionCard>
  );
}

function HoverSummary({
  series,
  events,
  hovered,
  color,
}: {
  series: Series;
  events: Ev[];
  hovered: number | null;
  color: string;
}) {
  let body: React.ReactNode;
  if (hovered == null || hovered >= series.labels.length) {
    body = <span className="small muted">Hover a point for the per-unit breakdown</span>;
  } else {
    const byUnit = new Map<string, Set<string>>();
    for (const e of events.filter((e) => e.bucket === hovered)) {
      const u = String(e.m['unit_name'] ?? '—');
      if (!byUnit.has(u)) byUnit.set(u, new Set());
      byUnit.get(u)!.add(String(e.m['person_uuid'] ?? e.m['name'] ?? ''));
    }
    const total = [...byUnit.values()].reduce((a, s) => a + s.size, 0);
    const parts = [...byUnit.entries()]
      .sort((a, b) => b[1].size - a[1].size)
      .map(([u, s]) => `${u} ${s.size}`)
      .join('  ·  ');
    body = (
      <span className="small" style={{ fontWeight: 500 }}>
        {total === 0 ? `${series.labels[hovered]} · none` : `${series.labels[hovered]} · ${total}  —  ${parts}`}
      </span>
    );
  }
  return (
    <div
      style={{
        minHeight: 38,
        marginTop: 6,
        padding: '4px 10px',
        borderRadius: 8,
        background: hovered == null ? 'transparent' : hexA(color, 0.08),
        display: 'flex',
        alignItems: 'center',
        overflow: 'hidden',
      }}
    >
      {body}
    </div>
  );
}

function BigStat({ label, v }: { label: string; v: number }) {
  return (
    <div style={{ flex: 1 }}>
      <div className="small muted">{label}</div>
      <div style={{ fontSize: '1.6rem', fontWeight: 700, marginTop: 2 }}>
        {v === Math.round(v) ? Math.round(v) : v.toFixed(1)}
      </div>
    </div>
  );
}

function DeltaBadge({ delta }: { delta: number }) {
  const up = delta >= 0;
  const c = up ? 'var(--success)' : 'var(--danger)';
  const v = delta === Math.round(delta) ? Math.abs(Math.round(delta)).toString() : Math.abs(delta).toFixed(1);
  return (
    <span className="chip" style={{ border: 'none', background: hexA(up ? '#2e7d32' : '#e53935', 0.12), color: c, fontSize: 12 }}>
      {up ? '+' : '−'}
      {v}
    </span>
  );
}

// ---- Overview stat grid -----------------------------------------------------------------------

function StatGridCard({ items }: { items: Array<{ label: string; value: string; onClick: () => void }> }) {
  return (
    <SectionCard title="Overview">
      <div className="wrap" style={{ gap: 24 }}>
        {items.map((it) => (
          <button
            key={it.label}
            type="button"
            onClick={it.onClick}
            style={{ width: 124, background: 'transparent', border: 'none', textAlign: 'left', color: 'inherit' }}
          >
            <div className="row" style={{ gap: 3 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>{it.value}</span>
              <Icon name="chevron_right" size={18} color="var(--on-surface-variant)" />
            </div>
            <span className="small muted">{it.label}</span>
          </button>
        ))}
      </div>
    </SectionCard>
  );
}

// ---- Golden Hour by unit (#26) ----------------------------------------------------------------

function UnitCompletionCard({ rows, onSelectUnit }: { rows: Member[]; onSelectUnit: (u: string) => void }) {
  const ranked = unitCompletion(rows, avgCompletion);
  if (ranked.length < 2) return null;
  return (
    <SectionCard title="Golden Hour by unit" icon="leaderboard">
      <div className="stack">
        {ranked.map((r) => (
          <button
            key={r.unit}
            type="button"
            onClick={() => onSelectUnit(r.unit)}
            style={{ background: 'transparent', border: 'none', textAlign: 'left', color: 'inherit', padding: '6px 2px', display: 'flex', alignItems: 'center', gap: 8 }}
          >
            <span style={{ flex: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.unit}</span>
            <span style={{ flex: 5 }}>
              <Progress value={r.pct} />
            </span>
            <span className="small" style={{ width: 62, textAlign: 'right' }}>
              {Math.round(r.pct * 100)}% · {r.n}
            </span>
          </button>
        ))}
      </div>
    </SectionCard>
  );
}
