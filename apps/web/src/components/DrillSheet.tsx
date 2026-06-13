// Drill-down sheets that list the people behind a stat — React ports of `_DrillSheet`,
// `_showGoldenHourBreakdown`, and `_showLessonsDrill` (kpis_view.dart). A small declarative API:
// open a sheet by setting state to a descriptor; the host renders <DrillHost />.

import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Member } from '../lib/member';
import { memberId } from '../lib/member';
import { fmtLong } from '../logic/dates';
import { milestones, expected, isMissing, type Milestone } from '../logic/milestones';
import type { Ev, MemberLessonCount } from '../logic/kpis';
import { Modal } from './Modal';
import { Avatar, CountBadge, Segmented, Progress } from './ui';

function PersonTile({ m, subtitle, trailing, onPick }: { m: Member; subtitle?: string; trailing?: ReactNode; onPick: () => void }) {
  return (
    <button type="button" className="list-tile" onClick={onPick} style={{ padding: '8px 4px' }}>
      <Avatar name={String(m['name'] ?? '?')} photoUrl={m['photo_url'] as string | undefined} size={32} />
      <span className="list-tile__main">
        <span>{String(m['name'] ?? '—')}</span>
        {subtitle && (
          <span className="tiny muted" style={{ display: 'block' }}>
            {subtitle}
          </span>
        )}
      </span>
      {trailing}
    </button>
  );
}

// ---- Metric drill (by unit / by date) ---------------------------------------------------------

interface MetricDrill {
  kind: 'metric';
  title: string;
  events: Ev[];
  allUnits: Set<string>;
  bucketLabel?: string | null;
}

function MetricDrillBody({ drill, onClose }: { drill: MetricDrill; onClose: () => void }) {
  const navigate = useNavigate();
  const [byUnit, setByUnit] = useState(true);
  const open = (m: Member) => {
    const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
    onClose();
    if (id) navigate(`/person/${encodeURIComponent(id)}`);
  };

  const unitName = (m: Member) => String(m['unit_name'] ?? '—');

  let body: ReactNode;
  if (byUnit) {
    const byU = new Map<string, Map<string, Member>>();
    for (const u of drill.allUnits) byU.set(u, new Map());
    for (const e of drill.events) {
      if (!byU.has(unitName(e.m))) byU.set(unitName(e.m), new Map());
      byU.get(unitName(e.m))!.set(memberId(e.m), e.m);
    }
    const units = [...byU.keys()].sort();
    body = (
      <>
        {units.map((u) => {
          const members = [...byU.get(u)!.values()].sort((a, b) =>
            String(a['name'] ?? '').localeCompare(String(b['name'] ?? '')),
          );
          return (
            <details key={u} open={members.length > 0} className="card" style={{ padding: 8, marginBottom: 4 }}>
              <summary style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <span style={{ flex: 1 }}>{u}</span>
                {members.length > 0 ? <CountBadge n={members.length} /> : <span className="muted">0</span>}
              </summary>
              {members.map((m, i) => (
                <PersonTile key={i} m={m} onPick={() => open(m)} />
              ))}
            </details>
          );
        })}
      </>
    );
  } else {
    const sorted = [...drill.events].sort((a, b) => b.date.getTime() - a.date.getTime());
    body =
      sorted.length === 0 ? (
        <p className="muted" style={{ padding: 16 }}>
          No one in this view.
        </p>
      ) : (
        sorted.map((e, i) => (
          <PersonTile key={i} m={e.m} subtitle={`${unitName(e.m)} · ${fmtLong(e.date)}`} onPick={() => open(e.m)} />
        ))
      );
  }

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
        <Segmented<'unit' | 'date'>
          ariaLabel="Drill grouping"
          value={byUnit ? 'unit' : 'date'}
          onChange={(v) => setByUnit(v === 'unit')}
          options={[
            { value: 'unit', label: 'By unit', icon: 'groups' },
            { value: 'date', label: 'By date', icon: 'schedule' },
          ]}
        />
      </div>
      {body}
    </>
  );
}

// ---- Golden Hour by-category drill ------------------------------------------------------------

interface GhDrill {
  kind: 'gh';
  rows: Member[];
}

function GhDrillBody({ drill, onClose }: { drill: GhDrill; onClose: () => void }) {
  const navigate = useNavigate();
  const open = (m: Member) => {
    const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
    onClose();
    if (id) navigate(`/person/${encodeURIComponent(id)}`);
  };
  return (
    <>
      <p className="small muted">
        Eligible-only — members who don't qualify (age, sex, tenure) are excluded so the % reflects
        who actually still needs it.
      </p>
      {milestones.map((ms: Milestone) => {
        // Expected-only: eligible AND not N/A (N/A ≠ not-done), so the % reflects who actually needs it.
        const eligible = drill.rows.filter((m) => expected(ms, m));
        if (eligible.length === 0) return null;
        const missing = eligible
          .filter((m) => isMissing(ms, m))
          .sort((a, b) => String(a['name'] ?? '').localeCompare(String(b['name'] ?? '')));
        const done = eligible.length - missing.length;
        const pct = done / eligible.length;
        return (
          <details key={ms.abbr} open={missing.length > 0} className="card" style={{ padding: 8, marginBottom: 4 }}>
            <summary style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <span style={{ flex: 1 }}>
                {ms.label}
                <span style={{ display: 'block', marginTop: 6, maxWidth: 'calc(100% - 40px)' }}>
                  <Progress value={pct} />
                </span>
              </span>
              <strong>
                {Math.round(pct * 100)}% · {done}/{eligible.length}
              </strong>
            </summary>
            {missing.length === 0 ? (
              <p style={{ padding: 16 }}>Everyone eligible has this. 🎉</p>
            ) : (
              missing.map((m, i) => <PersonTile key={i} m={m} subtitle={String(m['unit_name'] ?? '')} onPick={() => open(m)} />)
            )}
          </details>
        );
      })}
    </>
  );
}

// ---- Lessons-with-member drill ----------------------------------------------------------------

interface LessonsDrill {
  kind: 'lessons';
  people: MemberLessonCount[];
}

function LessonsDrillBody({ drill, onClose }: { drill: LessonsDrill; onClose: () => void }) {
  const navigate = useNavigate();
  const open = (m: Member) => {
    const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
    onClose();
    if (id) navigate(`/person/${encodeURIComponent(id)}`);
  };
  return (
    <>
      <p className="small muted">
        {drill.people.length} {drill.people.length === 1 ? 'person' : 'people'} · ranked by count
      </p>
      <hr className="divider" />
      {drill.people.length === 0 ? (
        <p style={{ textAlign: 'center', padding: 20 }}>No member-present lessons recorded yet.</p>
      ) : (
        drill.people.map((p, i) => (
          <PersonTile
            key={i}
            m={p.m}
            subtitle={String(p.m['unit_name'] ?? '')}
            trailing={<CountBadge n={p.count} />}
            onPick={() => open(p.m)}
          />
        ))
      )}
    </>
  );
}

// ---- Still-need (single milestone) drill ------------------------------------------------------

interface CategoryDrill {
  kind: 'category';
  label: string;
  missing: Member[];
}

function CategoryDrillBody({ drill, onClose }: { drill: CategoryDrill; onClose: () => void }) {
  const navigate = useNavigate();
  const open = (m: Member) => {
    const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
    onClose();
    if (id) navigate(`/person/${encodeURIComponent(id)}`);
  };
  return (
    <>
      <p className="small muted">
        {drill.missing.length} eligible {drill.missing.length === 1 ? 'member' : 'members'}
      </p>
      <hr className="divider" />
      {drill.missing.length === 0 ? (
        <p style={{ textAlign: 'center', padding: 24 }}>Everyone eligible has this. 🎉</p>
      ) : (
        drill.missing.map((m, i) => <PersonTile key={i} m={m} subtitle={String(m['unit_name'] ?? '')} onPick={() => open(m)} />)
      )}
    </>
  );
}

export type Drill = MetricDrill | GhDrill | LessonsDrill | CategoryDrill;

/** Renders the active drill sheet (or nothing). Set `drill` to open; `onClose` clears it. */
export function DrillHost({ drill, onClose }: { drill: Drill | null; onClose: () => void }) {
  if (!drill) return null;
  let title: string;
  let body: ReactNode;
  switch (drill.kind) {
    case 'metric':
      title = drill.title + (drill.bucketLabel ? ` · ${drill.bucketLabel}` : '');
      body = <MetricDrillBody drill={drill} onClose={onClose} />;
      break;
    case 'gh':
      title = 'Golden Hour by category';
      body = <GhDrillBody drill={drill} onClose={onClose} />;
      break;
    case 'lessons':
      title = 'Lessons with a member present';
      body = <LessonsDrillBody drill={drill} onClose={onClose} />;
      break;
    case 'category':
      title = `Still need: ${drill.label}`;
      body = <CategoryDrillBody drill={drill} onClose={onClose} />;
      break;
  }
  return (
    <Modal open onClose={onClose} sheet title={title}>
      {body}
    </Modal>
  );
}
