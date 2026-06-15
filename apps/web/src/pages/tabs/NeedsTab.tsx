// Needs tab — what's left to do. One compact filter ROW (Category dropdown · Units dropdown · org
// toggle chips), then the *eligible* members still missing that step (or, for the Sacrament-attendance
// category, those slipping in recent attendance), grouped or flat with an optional per-unit snapshot.
// New members only (N7). #1.

import { useDashboard } from '../../hooks/useDashboard';
import { usePersistentState, setCodec } from '../../hooks/usePersistentState';
import { useTier } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate } from '../../logic/dates';
import {
  needsCategories, responsibleOrg, isMissing, ORG_BUCKETS, type OrgBucket,
} from '../../logic/milestones';
import { assignUnitColors, memberAttendance } from '../../logic/kpis';
import { hexA, status } from '../../theme/tokens';
import { Icon, type IconName } from '../../components/Icon';
import { CountBadge, SectionCard, IconButton, Segmented } from '../../components/ui';
import {
  PageScaffold, BigHeader, OrgFilterBar, SubtleNote, MemberRow, Columns, orgNoteFor,
} from '../../components/dashboard';
import { TabGate } from '../../components/TabGate';
import { Dropdown, type DropdownOption } from '../../components/Dropdown';

export function NeedsTab() {
  return (
    <TabGate>
      <NeedsBody />
    </TabGate>
  );
}

/** A "needs" category: a milestone the member is still missing, or the synthetic Sacrament-attendance
 *  category (members slipping in recent attendance). `match` selects who's outstanding; `rank` (when
 *  present) orders worst-first within the category before the shared date sort. */
interface NeedCat {
  key: string;
  label: string;
  icon: IconName;
  color: string;
  match: (m: Member) => boolean;
  rank?: (m: Member) => number;
}

const ATTENDANCE_KEY = '__attendance__';

function NeedsBody() {
  const d = useDashboard();
  const tier = useTier();
  // Persisted view state (#1): selected category, sort direction, org + ward filters, group-by-unit,
  // and whether the per-unit snapshot pills show.
  const [selectedKey, setSelectedKey] = usePersistentState<string | null>('needs.catKey', null);
  const [ascending, setAscending] = usePersistentState<boolean>('needs.ascending', true);
  const [groupByUnit, setGroupByUnit] = usePersistentState<boolean>('needs.groupByUnit', false);
  const [showSnapshot, setShowSnapshot] = usePersistentState<boolean>('needs.snapshot', true);
  const [orgs, setOrgs] = usePersistentState<Set<OrgBucket>>(
    'needs.orgs', new Set(ORG_BUCKETS), setCodec as never);
  const [ward, setWard] = usePersistentState<string | null>('needs.ward', null); // null = all wards

  function toggleOrg(b: OrgBucket) {
    setOrgs((cur) => {
      const next = new Set(cur);
      if (next.has(b)) {
        if (next.size > 1) next.delete(b); // never-empty: keep at least one selected
      } else {
        next.add(b);
      }
      return next;
    });
  }

  function cmp(a: Member, b: Member): number {
    const da = parseMemberDate(a['baptism_date']);
    const db = parseMemberDate(b['baptism_date']);
    let c: number;
    if (da == null && db == null) c = 0;
    else if (da == null) c = 1;
    else if (db == null) c = -1;
    else c = da.getTime() - db.getTime();
    if (c === 0) c = String(a['unit_name'] ?? '').localeCompare(String(b['unit_name'] ?? ''));
    return ascending ? c : -c;
  }

  const all = d.members.filter((m) => !isInvestigator(m));
  const wards = [...new Set(all.map((m) => String(m['unit_name'] ?? '')).filter(Boolean))].sort();
  const allOrgs = orgs.size === ORG_BUCKETS.length;
  const orgScoped = allOrgs ? all : all.filter((m) => orgs.has(responsibleOrg(m) as OrgBucket));
  const baptized = ward == null ? orgScoped : orgScoped.filter((m) => String(m['unit_name'] ?? '') === ward);

  // Unified category list: every milestone (eligible-but-incomplete) + the Sacrament-attendance health
  // category (members at poor/none recent attendance, worst-first).
  const cats: NeedCat[] = [
    ...needsCategories.map((ms) => ({
      key: ms.abbr, label: ms.label, icon: ms.icon as IconName, color: ms.color,
      match: (m: Member) => isMissing(ms, m),
    })),
    {
      key: ATTENDANCE_KEY, label: 'Sacrament attendance', icon: 'event_available' as IconName,
      color: status.warning,
      match: (m: Member) => { const lv = memberAttendance(m).level; return lv === 'poor' || lv === 'none'; },
      // none (0) first, then by fewest attended.
      rank: (m: Member) => { const b = memberAttendance(m); return b.level === 'none' ? -1 : b.attended; },
    },
  ];

  function listFor(c: NeedCat): Member[] {
    const l = baptized.filter(c.match);
    if (c.rank) l.sort((a, b) => (c.rank!(a) - c.rank!(b)) || cmp(a, b));
    else l.sort(cmp);
    return l;
  }

  const lists = cats.map(listFor);
  const counts = lists.map((l) => l.length);
  const total = counts.reduce((a, b) => a + b, 0);
  const note = orgNoteFor(orgs);

  // Resolve the selected category (default: first with outstanding, else first).
  const firstNonEmpty = counts.findIndex((n) => n > 0);
  const selIdx = (() => {
    const i = cats.findIndex((c) => c.key === selectedKey);
    if (i >= 0) return i;
    return firstNonEmpty < 0 ? 0 : firstNonEmpty;
  })();
  const cat = cats[selIdx];
  const missing = lists[selIdx];
  const isAttendance = cat.key === ATTENDANCE_KEY;
  const unitColors = assignUnitColors(d.members);

  const filters = (
    <div className="stack" style={{ gap: 8 }}>
      <div style={{ height: 6 }} />
      <div className="wrap" style={{ gap: 8, alignItems: 'center' }}>
        <CategorySelect cats={cats} counts={counts} value={cat.key} onChange={setSelectedKey} />
        <WardSelect wards={wards} ward={ward} onChange={setWard} unitColors={unitColors} stakeName={d.stakeName} />
        <OrgFilterBar selected={orgs} onToggle={toggleOrg} onClear={() => setOrgs(new Set(ORG_BUCKETS))} />
      </div>
      {!allOrgs && note && <SubtleNote text={note} />}
      <div className="wrap" style={{ gap: 10, alignItems: 'center' }}>
        <Segmented
          ariaLabel="Group results"
          options={[{ value: 'flat', label: 'Flat' }, { value: 'unit', label: 'By unit' }]}
          value={groupByUnit ? 'unit' : 'flat'}
          onChange={(v) => setGroupByUnit(v === 'unit')}
        />
        <span className="row" style={{ gap: 4, alignItems: 'center' }}>
          <span className="small muted">{isAttendance ? 'Worst first' : 'Baptism date'}</span>
          <IconButton
            icon={ascending ? 'arrow_up' : 'arrow_down'}
            label={ascending ? 'Ascending (tap to reverse)' : 'Descending (tap to reverse)'}
            size={18}
            onClick={() => setAscending((a) => !a)}
          />
        </span>
        <label className="row small" style={{ gap: 8, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" className="switch" checked={showSnapshot} onChange={(e) => setShowSnapshot(e.target.checked)} />
          Unit snapshot
        </label>
      </div>
    </div>
  );

  if (total === 0) {
    return (
      <PageScaffold
        tier={tier}
        header={
          <div className="stack" style={{ gap: 0 }}>
            <BigHeader text="Action Needed" subtitle="Eligible members still working toward each step" />
            {filters}
          </div>
        }
      >
        <p style={{ textAlign: 'center', padding: 32 }}>
          {allOrgs ? 'Nothing outstanding — everyone eligible is on track. 🎉' : 'Nothing outstanding for the selected orgs. 🎉'}
        </p>
      </PageScaffold>
    );
  }

  return (
    <PageScaffold
      tier={tier}
      maxWidth={880}
      header={
        <div className="stack" style={{ gap: 0 }}>
          <BigHeader text="Action Needed" subtitle="Eligible members still working toward each step" />
          {filters}
        </div>
      }
    >
      <Columns cols={1}>
        {[
          <CategorySection
            key="cat"
            title={isAttendance ? 'Slipping in sacrament attendance' : `Still working toward: ${cat.label}`}
            icon={cat.icon}
            iconColor={cat.color}
            missing={missing}
            unitColors={unitColors}
            showSnapshot={showSnapshot}
            groupByUnit={groupByUnit}
            showAttendance={isAttendance}
            revealKey={`${cat.key}-${ascending}-${groupByUnit}-${ward ?? ''}`}
          />,
        ]}
      </Columns>
    </PageScaffold>
  );
}

function CategorySection({
  title,
  icon,
  iconColor,
  missing,
  unitColors,
  showSnapshot,
  groupByUnit,
  showAttendance,
  revealKey,
}: {
  title: string;
  icon: IconName;
  iconColor: string;
  missing: Member[];
  unitColors: Map<string, string>;
  showSnapshot: boolean;
  groupByUnit: boolean;
  showAttendance: boolean;
  /** Re-keys the result list so changing category/sort/group/ward replays a quick fade (#anim). */
  revealKey: string;
}) {
  const byUnit = new Map<string, Member[]>();
  for (const m of missing) {
    const u = String(m['unit_name'] ?? '—');
    if (!byUnit.has(u)) byUnit.set(u, []);
    byUnit.get(u)!.push(m);
  }
  const unitsByCount = [...byUnit.entries()].sort((a, b) => b[1].length - a[1].length);

  const row = (m: Member, i: number) => (
    <MemberRow key={i} m={m} showUnit={!groupByUnit} showResp showAttendance={showAttendance} />
  );

  return (
    <SectionCard title={title} icon={icon} iconColor={iconColor} trailing={<CountBadge n={missing.length} />}>
      {missing.length === 0 ? (
        <p style={{ padding: '16px 0' }}>Everyone eligible has this. 🎉</p>
      ) : (
        <>
          {showSnapshot && (
            <div className="wrap" style={{ gap: 6 }}>
              {unitsByCount.map(([unit, list]) => {
                const color = unitColors.get(unit) ?? '#37474F';
                return (
                  <span
                    key={unit}
                    className="chip"
                    style={{ background: hexA(color, 0.1), borderColor: hexA(color, 0.35), color, fontSize: 12 }}
                  >
                    {unit} · {list.length}
                  </span>
                );
              })}
            </div>
          )}
          {showSnapshot && <hr className="divider" />}
          <div className="reveal" key={revealKey}>
            {groupByUnit ? (
              <div className="stack" style={{ gap: 14 }}>
                {[...byUnit.keys()].sort().map((unit) => (
                  <div key={unit} className="stack" style={{ gap: 4 }}>
                    <div className="row small" style={{ gap: 6, fontWeight: 700, color: unitColors.get(unit) ?? 'var(--on-surface)' }}>
                      <Icon name="groups" size={14} color={unitColors.get(unit) ?? 'var(--on-surface-variant)'} />
                      {unit} <CountBadge n={byUnit.get(unit)!.length} />
                    </div>
                    <div className="stack">{byUnit.get(unit)!.map(row)}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="stack">{missing.map(row)}</div>
            )}
          </div>
        </>
      )}
    </SectionCard>
  );
}

/** Single-select category dropdown (#1a) — a custom dropdown showing each milestone's icon + color and
 *  its outstanding count. */
function CategorySelect({ cats, counts, value, onChange }: {
  cats: NeedCat[]; counts: number[]; value: string; onChange: (k: string) => void;
}) {
  const options: DropdownOption[] = cats.map((c, i) => ({
    value: c.key, label: c.label, icon: c.icon, color: c.color,
    trailing: counts[i] ? String(counts[i]) : undefined,
  }));
  return <Dropdown ariaLabel="Category" value={value} options={options} onChange={onChange} />;
}

/** Unit picker — one unit or the whole stake (default), each with its pill color. A single-unit leader
 *  has nothing to pick. The "all" option reads as the stake's name (not "Stake — all units"). */
function WardSelect({ wards, ward, onChange, unitColors, stakeName }: {
  wards: string[]; ward: string | null; onChange: (w: string | null) => void; unitColors: Map<string, string>;
  stakeName: string | null;
}) {
  if (wards.length <= 1) return null;
  const options: DropdownOption[] = [
    { value: '', label: stakeName ?? 'All units', icon: 'groups' },
    ...wards.map((w) => ({ value: w, label: w, color: unitColors.get(w) })),
  ];
  return <Dropdown ariaLabel="Filter by unit" value={ward ?? ''} options={options} onChange={(v) => onChange(v || null)} />;
}
