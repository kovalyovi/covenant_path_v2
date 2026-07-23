// KPIs tab — stake metrics from this stake's own covenant-path data. React port of kpis_view.dart:
//   • Baptisms by month (#1/#2) — convert cohort by baptism month over YTD/12mo/24mo/All + best month
//   • Investigators / New Members at Sacrament — attendance bucketed by the page period (line charts)
//   • New Friends Being Taught — first-lesson starts in the period
//   • Overview stat grid + which unit integrates converts best (#26)
// Each chart card overlays the previous equal window (compare toggle) and drills by unit/date.

import { useState } from 'react';
import { useDashboard } from '../../hooks/useDashboard';
import { usePersistentState } from '../../hooks/usePersistentState';
import { useTier, colsFor } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate, fmtMonShort, fmtMonYear, fmtMonthDayYear, dayOnly } from '../../logic/dates';
import { avgCompletion } from '../../logic/milestones';
import { currentCycle, goalRows, unitOptions, type GoalRow } from '../../logic/wardGoals';
import {
  metricData, attendedDates, firstLessonDate, lessonsWithMember,
  membersWithMemberLessons, unitCompletion, assignUnitColors,
  type Period, type Ev, type Series, type DateRange,
} from '../../logic/kpis';
import { Icon, type IconName } from '../../components/Icon';
import { SectionCard, Segmented, RangePill, Progress } from '../../components/ui';
import { Dropdown, type DropdownOption } from '../../components/Dropdown';
import { useToast } from '../../components/Toast';
import { useCountUp } from '../../hooks/useCountUp';
import { PageScaffold, BigHeader, Columns } from '../../components/dashboard';
import { SkeletonBox } from '../../components/Skeletons';
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
  // Persisted view state (item 9): period, unit filter, compare toggle. (customRange holds Date
  // objects + is a one-off power action → kept session-only.)
  const [period, setPeriod] = usePersistentState<Period>('kpis.period', 'month');
  const [unit, setUnit] = usePersistentState<string | null>('kpis.unit', null);
  const [compare, setCompare] = usePersistentState<boolean>('kpis.compare', false);
  const [customRange, setCustomRange] = useState<DateRange | null>(null); // #7
  const [drill, setDrill] = useState<Drill | null>(null);

  const units = [...new Set(d.members.map((m) => String(m['unit_name'] ?? '')).filter(Boolean))].sort();
  const unitColors = assignUnitColors(d.members);
  const rows = unit == null ? d.members : d.members.filter((m) => m['unit_name'] === unit);
  const baptized = rows.filter((m) => !isInvestigator(m));
  const investigators = rows.filter(isInvestigator);
  const allUnits = new Set(rows.map((m) => String(m['unit_name'] ?? '—')));
  // #6/#7: YTD and custom show period TOTALS (this period vs the same span last year).
  const showTotals = period === 'ytd' || period === 'custom';

  const cr = customRange ?? undefined;
  const friendsAtSac = metricData(investigators, attendedDates, period, cr);
  const newAtSac = metricData(baptized, attendedDates, period, cr);
  const newFriends = metricData(investigators, firstLessonDate, period, cr);
  // Baptisms now obey the GENERAL period (counted per week/month bucket like the other charts) instead
  // of their own YTD/12mo/24mo selector.
  const baptisms = metricData(baptized, baptismDatesOf, period, cr);
  const lessons = lessonsWithMember(rows);
  const completion = avgCompletion(baptized);

  // #7: custom date-range helpers (two native date inputs).
  const toISO = (dt: Date) => dt.toISOString().slice(0, 10);
  const activateCustom = () => {
    if (!customRange) setCustomRange({ start: new Date(new Date().getFullYear(), 0, 1), end: new Date() });
    setPeriod('custom');
  };
  const onCustomStart = (s: string) => {
    const dt = new Date(`${s}T00:00:00`);
    if (!Number.isNaN(dt.getTime())) setCustomRange((r) => ({ start: dt, end: r?.end ?? new Date() }));
  };
  const onCustomEnd = (s: string) => {
    const dt = new Date(`${s}T00:00:00`);
    if (!Number.isNaN(dt.getTime())) {
      setCustomRange((r) => ({ start: r?.start ?? new Date(new Date().getFullYear(), 0, 1), end: dt }));
    }
  };

  const compareLabels: [string, string] =
    period === 'month' ? ['Last month', 'This month']
      : period === 'year' || period === 'ytd' || period === 'custom' ? ['Last year', 'This year']
      : ['Prev. month', 'This month'];

  function periodRangeLabel(): string | null {
    const now = new Date();
    if (period === 'month') {
      const from = new Date(now.getTime() - 35 * 86_400_000);
      return `${fmtMonShort(from)} ${from.getDate()} – ${fmtMonShort(now)} ${now.getDate()}, ${now.getFullYear()}`;
    }
    if (period === 'ytd') {
      const from = new Date(now.getFullYear(), 0, 1); // Jan 1 → today
      return `${fmtMonShort(from)} ${from.getDate()} – ${fmtMonShort(now)} ${now.getDate()}, ${now.getFullYear()}`;
    }
    if (period === 'year') {
      const from = new Date(now.getFullYear(), now.getMonth() - 11, 1);
      return `${fmtMonYear(from)} – ${fmtMonYear(now)}`;
    }
    if (period === 'custom' && customRange) {
      const f = (dt: Date) => `${fmtMonShort(dt)} ${dt.getDate()}, ${dt.getFullYear()}`;
      return `${f(customRange.start)} – ${f(customRange.end)}`;
    }
    return null;
  }

  function evs(ms: Member[], dateField: string): Ev[] {
    return ms.map((m) => ({ m, date: parseMemberDate(m[dateField]) ?? new Date(), bucket: 0 }));
  }

  function baptismDatesOf(m: Member): Date[] {
    const dt = parseMemberDate(m['baptism_date']);
    return dt ? [dt] : [];
  }

  const rangeLabel = periodRangeLabel();

  // The four trend graphs (the 3 metric charts here + the Baptisms-by-month chart in its own section).
  const trendCards: React.ReactNode[] = [
    <MetricCard
      key="friends-sac"
      title="Being Taught at Sacrament"
      icon="groups"
      color="#fb8c00"
      series={friendsAtSac.series}
      events={friendsAtSac.events}
      allUnits={allUnits}
      compareLabels={compareLabels}
      showCompare={compare}
      ytdTotals={showTotals}
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
      ytdTotals={showTotals}
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
      ytdTotals={showTotals}
      suffix="people who started lessons in the period"
      onDrill={setDrill}
    />,
  ];

  const overviewCards: React.ReactNode[] = [
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
          label: 'Lessons with a member present',
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

  // While the stake data loads, glimmer the page with the real "KPIs" header + the Overview stat grid
  // and the trend-chart cards, so it never flashes a zeros/empty state before the numbers arrive.
  if (d.loading && d.members.length === 0) {
    return (
      <PageScaffold
        tier={tier}
        header={<BigHeader text="KPIs" subtitle="From this stake's covenant-path data" />}
      >
        <KpisSkeleton />
      </PageScaffold>
    );
  }

  return (
    <>
      <PageScaffold
        tier={tier}
        header={
          <div className="stack" style={{ gap: 8 }}>
            <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
              <div style={{ flex: '1 1 240px', minWidth: 0 }}>
                <BigHeader text="KPIs" subtitle="From this stake's covenant-path data" />
              </div>
              {units.length > 1 && (
                <Dropdown
                  ariaLabel="Unit"
                  value={unit ?? ''}
                  options={[
                    { value: '', label: d.stakeName ?? 'All units', icon: 'groups' },
                    ...units.map((u): DropdownOption => ({ value: u, label: u, color: unitColors.get(u) })),
                  ]}
                  onChange={(v) => setUnit(v || null)}
                />
              )}
            </div>
            {/* General filters on top — they drive EVERY widget below (Baptisms included). */}
            <div style={{ display: 'flex', justifyContent: 'center', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <Segmented<Period>
                ariaLabel="Period"
                value={period}
                onChange={setPeriod}
                options={[
                  { value: 'month', label: 'Month' },
                  { value: 'ytd', label: 'YTD' },
                  { value: 'year', label: 'Year' },
                  { value: 'all', label: 'All' },
                ]}
              />
              <button
                type="button"
                className="chip"
                aria-pressed={period === 'custom'}
                onClick={activateCustom}
                style={period === 'custom' ? { background: 'var(--secondary-container)', color: 'var(--on-secondary-container)', borderColor: 'transparent' } : undefined}
              >
                <Icon name="event" size={16} color={period === 'custom' ? 'var(--primary)' : undefined} />
                Custom
              </button>
              {period !== 'all' && (
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
              )}
            </div>
            {period === 'custom' && customRange && (
              <div className="row" style={{ justifyContent: 'center', gap: 8, alignItems: 'center' }}>
                <input type="date" className="input" style={{ width: 'auto' }} aria-label="Custom range start"
                  max={toISO(customRange.end)} value={toISO(customRange.start)} onChange={(e) => onCustomStart(e.target.value)} />
                <span className="muted">–</span>
                <input type="date" className="input" style={{ width: 'auto' }} aria-label="Custom range end"
                  min={toISO(customRange.start)} value={toISO(customRange.end)} onChange={(e) => onCustomEnd(e.target.value)} />
              </div>
            )}
            {rangeLabel && (
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <RangePill text={rangeLabel} />
              </div>
            )}
          </div>
        }
      >
        {/* Baptisms FIRST — now a per-period trend chart (counts baptisms per bucket) using the general
            filters + Compare, then the other Trends, then Overview. */}
        <SectionHeading icon="water_drop">Baptisms</SectionHeading>
        <div style={{ maxWidth: 640 }}>
          <BaptismsCard
            series={baptisms.series}
            events={baptisms.events}
            allUnits={allUnits}
            showCompare={compare}
            compareLabels={compareLabels}
            onDrill={setDrill}
          />
        </div>

        <SectionHeading icon="flag">Ward Goals</SectionHeading>
        <div style={{ maxWidth: 640 }}>
          <WardGoalsCard />
        </div>

        <SectionHeading icon="leaderboard">Trends</SectionHeading>
        <Columns cols={Math.min(2, colsFor(tier))}>{trendCards}</Columns>

        <SectionHeading icon="summarize">Overview</SectionHeading>
        <Columns cols={Math.min(2, colsFor(tier))}>{overviewCards}</Columns>
      </PageScaffold>
      <DrillHost drill={drill} onClose={() => setDrill(null)} />
    </>
  );
}

/** Ward baptism goals for the CURRENT transfer cycle: per unit, goal vs actual (baptized in the cycle
 *  window), with an inline-editable goal number. A ward leader sees only their unit, a stake leader all
 *  (RLS scopes both the members read and the ward_goals write). Needs the transfer schedule to exist. */
function WardGoalsCard() {
  const d = useDashboard();
  const toast = useToast();
  const cycle = currentCycle(d.transferDates, dayOnly(new Date()));
  const units = unitOptions(d.members);
  const baptized = d.members.filter((m) => !isInvestigator(m));

  if (!cycle) {
    return (
      <SectionCard title="Ward goals" icon="flag">
        <p className="muted" style={{ margin: 0 }}>
          Set the transfer schedule on the Baptisms page to track ward baptism goals per cycle.
        </p>
      </SectionCard>
    );
  }

  const rows = goalRows(units, baptized, d.wardGoals, cycle.transferId, cycle.window);

  async function save(row: GoalRow, goal: number) {
    try {
      await d.upsertWardGoal({ unitId: row.unitId, unitName: row.unitName, transferId: cycle!.transferId, goal });
    } catch (e) {
      toast.show({ message: `Could not save goal: ${e instanceof Error ? e.message : e}` });
    }
  }

  return (
    <SectionCard
      title="Ward goals"
      icon="flag"
      trailing={<span className="tiny muted">Cycle ending {fmtMonthDayYear(cycle.window.end)}</span>}
    >
      {rows.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>No units to show yet.</p>
      ) : (
        <div className="stack" style={{ gap: 10 }}>
          {rows.map((row) => (
            <WardGoalRow key={row.unitId ?? row.unitName} row={row} onSave={(g) => void save(row, g)} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function WardGoalRow({ row, onSave }: { row: GoalRow; onSave: (goal: number) => void }) {
  const [val, setVal] = useState(row.goal == null ? '' : String(row.goal));
  const goalNum = row.goal ?? 0;
  const pct = goalNum > 0 ? Math.min(1, row.actual / goalNum) : 0;
  const met = goalNum > 0 && row.actual >= goalNum;

  function commit() {
    const trimmed = val.trim();
    if (trimmed === '') return; // leaving it blank keeps the current goal (or "unset")
    const n = Math.max(0, Math.floor(Number(trimmed)));
    if (Number.isNaN(n)) {
      setVal(row.goal == null ? '' : String(row.goal));
      return;
    }
    if (n !== (row.goal ?? -1)) onSave(n);
  }

  return (
    <div className="stack" style={{ gap: 4 }}>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{row.unitName}</span>
        <span className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span className="tiny muted">
            {row.actual} of {row.goal ?? '—'} baptized
          </span>
          <input
            className="input"
            type="number"
            min={0}
            inputMode="numeric"
            aria-label={`Baptism goal for ${row.unitName}`}
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
            style={{ width: 64 }}
          />
        </span>
      </div>
      {goalNum > 0 && <Progress value={pct} color={met ? 'var(--good, var(--primary))' : undefined} />}
    </div>
  );
}

/** #33: a labeled section divider grouping the KPIs page (Baptisms / Trends / Overview). */
function SectionHeading({ icon, children }: { icon: IconName; children: string }) {
  return (
    <div className="row" style={{ gap: 8, alignItems: 'center', margin: '20px 0 6px' }}>
      <span className="accent-bar" style={{ height: 22 }} />
      <Icon name={icon} size={18} color="var(--primary)" />
      <h3 style={{ fontSize: '1.05rem', fontWeight: 700, margin: 0 }}>{children}</h3>
    </div>
  );
}

/** Make a chart bucket label human-readable for the "Best period" stat: a weekly bucket reads as
 *  "M/d" (e.g. "5/5") → render it as "May 5, '26". Monthly/yearly labels ("May", "May '25") are
 *  already readable and pass through. */
function prettyBucket(label: string): string {
  const m = /^(\d{1,2})\/(\d{1,2})$/.exec(label);
  if (!m) return label;
  const dt = new Date(new Date().getFullYear(), Number(m[1]) - 1, Number(m[2]));
  return `${fmtMonShort(dt)} ${dt.getDate()}, '${String(dt.getFullYear()).slice(2)}`;
}

/** A chart card footer: the descriptive text on its OWN full-width row, then the "By unit" button
 *  right-aligned on the row below — so neither wraps awkwardly or pushes the other off (#kpis). */
function ChartFooter({ suffix, onByUnit }: { suffix: string; onByUnit: () => void }) {
  return (
    <div className="stack" style={{ gap: 4, marginTop: 6 }}>
      <span className="small muted">{suffix}</span>
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn--text" onClick={(e) => { e.stopPropagation(); onByUnit(); }}>
          <Icon name="groups" size={16} /> By unit
        </button>
      </div>
    </div>
  );
}

// ---- Baptisms (#1/#2) — a per-period trend chart, driven by the general filters (like every chart) --

function BaptismsCard({
  series,
  events,
  allUnits,
  showCompare,
  compareLabels,
  onDrill,
}: {
  series: Series;
  events: Ev[];
  allUnits: Set<string>;
  showCompare: boolean;
  compareLabels: [string, string];
  onDrill: (d: Drill) => void;
}) {
  const color = '#0277BD';
  const values = series.current;
  const total = values.reduce((a, b) => a + b, 0);
  const priorTotal = series.prev.reduce((a, b) => a + b, 0);
  let bi = -1;
  let bc = 0;
  values.forEach((v, i) => { if (v > bc) { bc = v; bi = i; } });
  const bestLabel = bi >= 0 ? prettyBucket(series.labels[bi]) : null;
  const delta = total - priorTotal;
  return (
    <SectionCard
      title="Baptisms"
      icon="water_drop"
      iconColor={color}
      trailing={showCompare && series.prev.length > 0 ? <DeltaBadge delta={delta} /> : undefined}
      onClick={events.length === 0 ? undefined : () => onDrill({ kind: 'metric', title: 'Baptisms', events, allUnits })}
    >
      <div className="row" style={{ alignItems: 'stretch' }}>
        <Kv label={`Baptized · ${compareLabels[1]}`} value={String(total)} />
        <div style={{ width: 1, background: 'var(--outline-variant)', margin: '0 14px' }} />
        <Kv label="Best period" value={bestLabel == null ? '—' : `${bestLabel}  ·  ${bc}`} />
      </div>
      <div style={{ height: 14 }} />
      <TrendLine
        values={values}
        labels={series.labels}
        color={color}
        prev={showCompare ? series.prev : []}
        onBucketTap={(i) =>
          onDrill({
            kind: 'metric',
            title: 'Baptisms',
            events: events.filter((e) => e.bucket === i),
            allUnits,
            bucketLabel: i < series.labels.length ? series.labels[i] : null,
          })
        }
      />
      <ChartFooter suffix="baptisms, counted in their week/month bucket" onByUnit={() => onDrill({ kind: 'metric', title: 'Baptisms', events, allUnits })} />
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
  ytdTotals = false,
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
  ytdTotals?: boolean;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const values = series.current;
  // #6: for YTD the big-stat pair is YTD TOTALS (this year vs the same Jan–today span last year);
  // otherwise it's the last two buckets (month-over-month).
  let last: number | null;
  let prior: number | null;
  let delta: number | null;
  if (ytdTotals) {
    const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
    last = sum(values);
    prior = sum(series.prev);
    delta = last - prior;
  } else {
    last = values.length > 0 ? values[values.length - 1] : null;
    prior = values.length >= 2 ? values[values.length - 2] : null;
    delta = last != null && prior != null ? last - prior : null;
  }

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
      <ChartFooter suffix={suffix} onByUnit={() => onDrill({ kind: 'metric', title, events, allUnits })} />
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
  const n = useCountUp(v); // animate the big stat up on load / period change
  const display = Number.isInteger(v) ? String(Math.round(n)) : n.toFixed(1);
  return (
    <div style={{ flex: 1 }}>
      <div className="small muted">{label}</div>
      <div style={{ fontSize: '1.6rem', fontWeight: 700, marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>
        {display}
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

/** Loading glimmer for the KPIs tab: the Overview stat grid (4 tiles, matching `StatGridCard`) and the
 *  three trend-chart cards (title + a chart-area rectangle, matching `MetricCard`). Reuses the real
 *  `.card`/`.section-card__head`/`.wrap` chrome so cards and tiles land in the same places. */
function KpisSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="card">
        <div className="card__body">
          <div className="section-card__head">
            <SkeletonBox width={26} height={26} radius={8} />
            <span className="section-card__title"><SkeletonBox width={96} height={16} /></span>
          </div>
          <div className="wrap" style={{ gap: 24 }}>
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} style={{ width: 124 }}>
                <SkeletonBox width={56} height={28} />
                <div style={{ height: 7 }} />
                <SkeletonBox width={104} height={11} />
              </div>
            ))}
          </div>
        </div>
      </div>
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} className="card">
          <div className="card__body">
            <div className="section-card__head">
              <SkeletonBox width={26} height={26} radius={8} />
              <span className="section-card__title"><SkeletonBox width={170} height={16} /></span>
            </div>
            <SkeletonBox width="100%" height={120} radius={8} />
          </div>
        </div>
      ))}
    </div>
  );
}

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
