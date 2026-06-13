// Needs tab — what's left to do: a category selector along the top (one milestone at a time, each
// with its own outstanding count), then the *eligible* members still missing that step, with a
// per-unit colored breakdown. React port of needs_view.dart. New members only (N7); org-filtered.

import { useState } from 'react';
import { useDashboard } from '../../hooks/useDashboard';
import { useTier } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate } from '../../logic/dates';
import {
  needsCategories, responsibleOrg, isMissing, ORG_BUCKETS, type OrgBucket, type Milestone,
} from '../../logic/milestones';
import { assignUnitColors } from '../../logic/kpis';
import { hexA } from '../../theme/tokens';
import { Icon, type IconName } from '../../components/Icon';
import { CountBadge, SectionCard, IconButton } from '../../components/ui';
import {
  PageScaffold, BigHeader, OrgFilterBar, SubtleNote, MemberRow, Columns, orgNoteFor,
} from '../../components/dashboard';
import { TabGate } from '../../components/TabGate';

export function NeedsTab() {
  return (
    <TabGate>
      <NeedsBody />
    </TabGate>
  );
}

function NeedsBody() {
  const d = useDashboard();
  const tier = useTier();
  const [selected, setSelected] = useState<number | null>(null);
  const [ascending, setAscending] = useState(true);
  const [orgs, setOrgs] = useState<Set<OrgBucket>>(new Set(ORG_BUCKETS));
  const [ward, setWard] = useState<string | null>(null); // null = Stake (all wards)

  function toggleOrg(b: OrgBucket) {
    setOrgs((cur) => {
      const next = new Set(cur);
      if (next.has(b)) {
        if (next.size > 1) next.delete(b);
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
  // Ward dropdown (default Stake = all wards) filters on top of the org filter.
  const baptized = ward == null ? orgScoped : orgScoped.filter((m) => String(m['unit_name'] ?? '') === ward);
  // "Missing" = expected-but-incomplete: eligible AND the field isn't N/A (N/A ≠ not-done, so a
  // not-applicable field — priesthood for a woman, a patriarchal blessing for a young child — never
  // shows the member as missing). `isMissing` is the shared rule across all completion surfaces.
  const missingByMs = needsCategories.map((ms) =>
    baptized.filter((m) => isMissing(ms, m)).sort(cmp),
  );
  const total = missingByMs.reduce((acc, l) => acc + l.length, 0);
  const note = orgNoteFor(orgs);

  const filters = (
    <div className="stack" style={{ gap: 6 }}>
      <div style={{ height: 10 }} />
      <OrgFilterBar selected={orgs} onToggle={toggleOrg} onClear={() => setOrgs(new Set(ORG_BUCKETS))} />
      {!allOrgs && note && <SubtleNote text={note} />}
      <WardSelect wards={wards} ward={ward} onChange={setWard} />
    </div>
  );

  if (total === 0) {
    return (
      <PageScaffold
        tier={tier}
        header={
          <div className="stack" style={{ gap: 0 }}>
            <BigHeader text="Needs Action" subtitle="Eligible members still missing each integration step" />
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

  const firstNonEmpty = missingByMs.findIndex((l) => l.length > 0);
  const sel = selected ?? (firstNonEmpty < 0 ? 0 : firstNonEmpty);
  const ms = needsCategories[sel];
  const missing = missingByMs[sel];
  const unitColors = assignUnitColors(d.members);

  return (
    <PageScaffold
      tier={tier}
      header={
        <div className="stack" style={{ gap: 0 }}>
          <BigHeader text="Needs Action" subtitle="Eligible members still missing each integration step" />
          {filters}
          <div style={{ height: 12 }} />
          <div className="wrap">
            {needsCategories.map((m, i) => (
              <CategoryChip key={m.abbr} ms={m} count={missingByMs[i].length} selected={i === sel} onClick={() => setSelected(i)} />
            ))}
          </div>
          <div className="row" style={{ gap: 6 }}>
            <Icon name="sort" size={15} color="var(--on-surface-variant)" />
            <span className="small muted">Baptism date, then unit</span>
            <IconButton
              icon={ascending ? 'arrow_up' : 'arrow_down'}
              label={ascending ? 'Oldest first (tap for newest)' : 'Newest first (tap for oldest)'}
              size={18}
              onClick={() => setAscending((a) => !a)}
            />
          </div>
        </div>
      }
    >
      <Columns cols={1}>
        {[<CategorySection key="cat" ms={ms} missing={missing} unitColors={unitColors} />]}
      </Columns>
    </PageScaffold>
  );
}

function CategorySection({
  ms,
  missing,
  unitColors,
}: {
  ms: Milestone;
  missing: Member[];
  unitColors: Map<string, string>;
}) {
  const byUnit = new Map<string, number>();
  for (const m of missing) {
    const u = String(m['unit_name'] ?? '—');
    byUnit.set(u, (byUnit.get(u) ?? 0) + 1);
  }
  const units = [...byUnit.entries()].sort((a, b) => b[1] - a[1]);
  return (
    <SectionCard title={`Needs ${ms.label}`} icon={ms.icon as IconName} iconColor={ms.color} trailing={<CountBadge n={missing.length} />}>
      {missing.length === 0 ? (
        <p style={{ padding: '16px 0' }}>Everyone eligible has this. 🎉</p>
      ) : (
        <>
          <div className="wrap" style={{ gap: 6 }}>
            {units.map(([unit, count]) => {
              const color = unitColors.get(unit) ?? '#37474F';
              return (
                <span
                  key={unit}
                  className="chip"
                  style={{ background: hexA(color, 0.1), borderColor: hexA(color, 0.35), color, fontSize: 12 }}
                >
                  {unit} · {count}
                </span>
              );
            })}
          </div>
          <hr className="divider" />
          <div className="stack">
            {missing.map((m, i) => (
              <MemberRow key={i} m={m} showUnit showResp />
            ))}
          </div>
        </>
      )}
    </SectionCard>
  );
}

function CategoryChip({
  ms,
  count,
  selected,
  onClick,
}: {
  ms: Milestone;
  count: number;
  selected: boolean;
  onClick: () => void;
}) {
  const done = count === 0;
  const base = done ? '#9e9e9e' : ms.color;
  const fg = selected ? '#fff' : base;
  return (
    <button
      type="button"
      className="chip"
      aria-pressed={selected}
      onClick={onClick}
      style={{
        whiteSpace: 'nowrap',
        background: selected ? base : hexA(base, 0.1),
        borderColor: hexA(base, selected ? 1 : 0.35),
        color: fg,
      }}
    >
      <Icon name={done ? 'check_circle' : (ms.icon as IconName)} size={17} color={fg} />
      {ms.label}
      {!done && (
        <span
          style={{
            padding: '1px 7px',
            borderRadius: 'var(--radius-pill)',
            background: selected ? 'rgba(255,255,255,0.25)' : hexA(base, 0.16),
            fontWeight: 700,
            fontSize: 12,
          }}
        >
          {count}
        </span>
      )}
    </button>
  );
}

/** Ward picker below the org filters — one ward or the whole stake (default). A single-unit leader
 *  (only one ward in view) has nothing to pick, so it hides itself. */
function WardSelect({ wards, ward, onChange }: {
  wards: string[]; ward: string | null; onChange: (w: string | null) => void;
}) {
  if (wards.length <= 1) return null;
  return (
    <label className="row" style={{ gap: 8, alignItems: 'center', paddingTop: 4 }}>
      <Icon name="groups" size={16} color="var(--on-surface-variant)" />
      <select
        value={ward ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        aria-label="Filter by ward"
        style={{
          flex: 1, maxWidth: 340, padding: '7px 10px', borderRadius: 10, font: 'inherit',
          border: '1px solid var(--outline)', background: 'var(--surface)', color: 'var(--on-surface)',
        }}
      >
        <option value="">Stake — all wards</option>
        {wards.map((w) => (
          <option key={w} value={w}>{w}</option>
        ))}
      </select>
    </label>
  );
}
