// Golden Hour tab — two sections: **Being Taught** (investigators with a planned baptism date) and
// **New Members** (baptized — integration milestone chips, next step highlighted, org-filtered,
// recency-windowed). React port of golden_hour_view.dart.

import { useState } from 'react';
import { useDashboard } from '../../hooks/useDashboard';
import { usePersistentState, setCodec } from '../../hooks/usePersistentState';
import { useTier, type Tier } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate, fmtMonShort } from '../../logic/dates';
import {
  milestones, responsibleOrg, expected, isMissing, unitGoldenHour, ORG_BUCKETS, type OrgBucket,
} from '../../logic/milestones';
import { FilledRing, SectionedRing } from '../../components/Rings';
import {
  PageScaffold, SectionTitle, OrgFilterBar, SubtleNote, UnitGrid, DateList, orgNoteFor, scrollToUnit,
} from '../../components/dashboard';
import { Segmented, SectionCard, RangePill, Progress } from '../../components/ui';
import { Icon, type IconName } from '../../components/Icon';
import { TabGate } from '../../components/TabGate';
import { DrillHost, type Drill } from '../../components/DrillSheet';
import { ManualMembersSection } from '../../components/ManualMembers';

type Window = 'week' | 'month' | 'year' | 'all';
type GhSection = 'newMembers' | 'beingTaught';

export function GoldenHourTab() {
  return (
    <TabGate>
      <GoldenHourBody />
    </TabGate>
  );
}

function GoldenHourBody() {
  const d = useDashboard();
  const tier = useTier();
  // Persisted view state (item 9): section, recency window, sort mode/direction, org filter.
  const [section, setSection] = usePersistentState<GhSection>('gh.section', 'newMembers');
  const [windowSel, setWindowSel] = usePersistentState<Window>('gh.window', 'all');
  const [byDate, setByDate] = usePersistentState<boolean>('gh.byDate', false);
  const [asc, setAsc] = usePersistentState<boolean | null>('gh.asc', null);
  const [orgs, setOrgs] = usePersistentState<Set<OrgBucket>>(
    'gh.orgs', new Set(ORG_BUCKETS), setCodec as never);
  const [drill, setDrill] = useState<Drill | null>(null);

  const newMembers = d.members.filter((m) => !isInvestigator(m));
  const beingTaught = d.members.filter(isInvestigator);

  const ascending = asc ?? section === 'beingTaught';

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

  function within(m: Member): boolean {
    if (windowSel === 'all') return true;
    const dt = parseMemberDate(m['baptism_date']);
    if (dt == null) return false;
    const days = Math.floor((Date.now() - dt.getTime()) / 86_400_000);
    return windowSel === 'week' ? days <= 7 : windowSel === 'month' ? days <= 31 : days <= 366;
  }

  function windowRangeLabel(): string | null {
    if (windowSel === 'all') return null;
    const now = new Date();
    const days = windowSel === 'week' ? 7 : windowSel === 'month' ? 31 : 366;
    const from = new Date(now.getTime() - days * 86_400_000);
    return `Baptized ${fmtMonShort(from)} ${from.getDate()} – ${fmtMonShort(now)} ${now.getDate()}, ${now.getFullYear()}`;
  }

  const sectionToggle = (
    <div style={{ display: 'flex', justifyContent: 'center' }}>
      <Segmented<GhSection>
        ariaLabel="Section"
        value={section}
        onChange={setSection}
        options={[
          { value: 'newMembers', label: `New Members (${newMembers.length})`, icon: 'verified' },
          { value: 'beingTaught', label: `Being Taught (${beingTaught.length})`, icon: 'menu_book' },
        ]}
      />
    </div>
  );

  if (section === 'beingTaught') {
    return (
      <>
        <PageScaffold
          tier={tier}
          maxWidth={960}
          header={
            <div className="stack" style={{ gap: 8 }}>
              {sectionToggle}
              <SectionTitle
                title="Being Taught"
                count={beingTaught.length}
                byDate={byDate}
                onToggle={setByDate}
                ascending={ascending}
                onAscToggle={() => setAsc(!ascending)}
              />
            </div>
          }
        >
          {/* Leader-added people being taught + merge suggestions (item 11) — always available so a
              leader can track friends/investigators before LCR has a record. */}
          <ManualMembersSection />
          {beingTaught.length === 0 ? (
            <p style={{ textAlign: 'center', padding: 32 }}>No one is being taught in the Church records yet.</p>
          ) : byDate ? (
            <DateList rows={beingTaught} chips={false} dateField="baptism_goal_date" ascending={ascending} />
          ) : (
            <UnitGrid rows={beingTaught} tier={tier} chips={false} dateField="baptism_goal_date" ascending={ascending} />
          )}
        </PageScaffold>
        <DrillHost drill={drill} onClose={() => setDrill(null)} />
      </>
    );
  }

  const allOrgs = orgs.size === ORG_BUCKETS.length;
  const rows = newMembers
    .filter(within)
    .filter((m) => allOrgs || orgs.has(responsibleOrg(m) as OrgBucket));

  const rangeLabel = windowRangeLabel();
  const note = orgNoteFor(orgs);

  return (
    <>
      <PageScaffold
        tier={tier}
        maxWidth={960}
        header={
          <div className="stack" style={{ gap: 10 }}>
            {sectionToggle}
            <OrgFilterBar
              selected={orgs}
              onToggle={toggleOrg}
              onClear={() => setOrgs(new Set(ORG_BUCKETS))}
            />
            {!allOrgs && note && <SubtleNote text={note} />}
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <Segmented<Window>
                ariaLabel="Recency window"
                value={windowSel}
                onChange={setWindowSel}
                options={[
                  { value: 'week', label: 'Week' },
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
            <SectionTitle
              title="Recently Baptized"
              count={rows.length}
              byDate={byDate}
              onToggle={setByDate}
              ascending={ascending}
              onAscToggle={() => setAsc(!ascending)}
            />
            <CompletionCard rows={rows} onDrill={setDrill} />
            <UnitCompletionCard rows={rows} tier={tier} />
          </div>
        }
      >
        {rows.length === 0 ? (
          <p style={{ textAlign: 'center', padding: 32 }}>No new members in this window.</p>
        ) : byDate ? (
          <DateList rows={rows} chips ascending={ascending} elapsedBaptism showResp />
        ) : (
          <UnitGrid rows={rows} tier={tier} chips ascending={ascending} elapsedBaptism showResp />
        )}
      </PageScaffold>
      <DrillHost drill={drill} onClose={() => setDrill(null)} />
    </>
  );
}

/** Per-unit Golden Hour indicators (#8d): for each unit, a SECTIONED ring (one arc per person, filled
 *  when fully complete) = % of people done, and a FILLED ring = % of eligible items complete overall.
 *  Hidden for a single-unit leader (nothing to compare). */
function UnitCompletionCard({ rows, tier }: { rows: Member[]; tier: Tier }) {
  const units = unitGoldenHour(rows);
  if (units.length <= 1) return null;
  // On phones: smaller rings + no sublabels + tighter gap so each unit fits on ONE line.
  const mobile = tier === 'mobile';
  const ring = mobile ? 44 : 64;
  return (
    // Sized to its content (~half width), not stretched edge-to-edge.
    <div style={{ maxWidth: 540 }}>
      <SectionCard title="Completion by unit">
        <div className="tiny muted" style={{ marginBottom: 10 }}>
          Left: people fully complete (one arc each). Right: items complete overall. Tap a unit to jump to it.
        </div>
        <div className="stack" style={{ gap: 6 }}>
          {units.map((u) => (
            // #25: each row jumps to that unit's card below (smooth scroll + a brief pop).
            <button
              key={u.unit}
              type="button"
              className="unit-jump"
              onClick={() => scrollToUnit(u.unit)}
              title={`Jump to ${u.unit}`}
            >
              <span style={{ fontWeight: 600, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{u.unit}</span>
              <span className="row" style={{ gap: mobile ? 8 : 12, marginLeft: mobile ? 8 : 24, flexShrink: 0, alignItems: 'center' }}>
                <SectionedRing size={ring} total={u.people} filled={u.fullyComplete} sublabel={mobile ? undefined : 'people'} />
                <FilledRing size={ring} value={u.itemsTotal ? u.itemsDone / u.itemsTotal : 1} sublabel={mobile ? undefined : 'items'} />
                {!mobile && <Icon name="chevron_right" size={18} />}
              </span>
            </button>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}

function CompletionCard({ rows, onDrill }: { rows: Member[]; onDrill: (d: Drill) => void }) {
  if (rows.length === 0) return null;
  return (
    <SectionCard title="Golden Hour completion">
      {/* Balanced 2-column grid that spans the FULL width (esp. on mobile). `grid-auto-rows: 1fr`
          keeps sibling cells the SAME height even when one label wraps to two lines, so it reads as
          a clean two-column flow; full label text — never truncated with "…". */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
        {milestones.map((ms) => {
          // Expected-only: eligible AND not N/A (N/A ≠ not-done), so the % + drill exclude
          // not-applicable members entirely.
          const eligible = rows.filter((m) => expected(ms, m));
          if (eligible.length === 0) return null;
          const done = eligible.filter(ms.complete);
          const missing = eligible.filter((m) => isMissing(ms, m));
          const pct = done.length / eligible.length;
          return (
            <button
              key={ms.abbr}
              type="button"
              onClick={() => onDrill({ kind: 'category', label: ms.label, missing })}
              style={{
                display: 'flex',
                flexDirection: 'column',
                flex: '1 1 calc(50% - 7px)',
                minWidth: 150,
                background: 'transparent',
                border: 'none',
                textAlign: 'left',
                color: 'inherit',
                padding: 0,
              }}
            >
              <div className="row" style={{ gap: 5, alignItems: 'center' }}>
                {/* #8a: the milestone's own icon + color next to its completion rate. */}
                <Icon name={ms.icon as IconName} size={17} color={ms.color} />
                <span style={{ fontSize: '1.25rem', fontWeight: 700 }}>{Math.round(pct * 100)}%</span>
                <span className="tiny muted">
                  {done.length}/{eligible.length}
                </span>
              </div>
              {/* Full label, wraps to as many lines as needed (no ellipsis); flex-grow pushes the bar
                  to the bottom so a one-line cell aligns its bar with a two-line sibling. */}
              <div className="tiny muted" style={{ flex: 1 }}>
                {ms.label}
              </div>
              <div style={{ marginTop: 4 }}>
                <Progress value={pct} />
              </div>
            </button>
          );
        })}
      </div>
    </SectionCard>
  );
}
