// Baptisms tab — a CARD PER PERSON (item 1). Each investigator with a planned (future) baptism date
// gets their OWN card showing: the planned date + countdown, their unit, full leader notes/comments,
// relevant covenant-path info, their Golden Hour next steps, and the assigned (full-time) missionaries
// for their unit (who teach them, as far as the synced data tells us — see the data-availability note).
//
// Overdue dates (the date already passed) surface first in a "needs attention" section; genuinely
// upcoming dates follow. A SECOND section below lists the assigned missionaries per unit/ward (item 3).
// Investigators only (N7). React rework of the former combined-timeline baptisms_view.

import { useNavigate } from 'react-router-dom';
import { useDashboard } from '../../hooks/useDashboard';
import { usePersistentState } from '../../hooks/usePersistentState';
import { useTier, colsFor } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate, fmtMonShort, fmtWeekdayShort, dayOnly, daysBetween } from '../../logic/dates';
import { nextSteps } from '../../logic/milestones';
import { hexA } from '../../theme/tokens';
import { Icon } from '../../components/Icon';
import { Avatar, CountBadge, SectionCard } from '../../components/ui';
import { PageScaffold, SectionTitle, Columns } from '../../components/dashboard';
import { MissionaryStrip, MissionariesSection, useUnitMissionaries } from '../../components/Missionaries';
import { GoldenHourChips } from '../../components/GoldenHourChips';
import { TabGate } from '../../components/TabGate';

interface Dated {
  m: Member;
  date: Date;
}

export function BaptismsTab() {
  return (
    <TabGate>
      <BaptismsBody />
    </TabGate>
  );
}

function BaptismsBody() {
  const d = useDashboard();
  const tier = useTier();
  const [byUnit, setByUnit] = usePersistentState<boolean>('baptisms.byUnit', false); // item 9

  const today = dayOnly(new Date());
  const items: Dated[] = [];
  for (const m of d.members) {
    if (!isInvestigator(m)) continue;
    const dt = parseMemberDate(m['baptism_goal_date']);
    if (dt) items.push({ m, date: dayOnly(dt) });
  }
  items.sort((a, b) => a.date.getTime() - b.date.getTime());

  // Every stake unit that has missionaries synced — the full per-unit breakdown for the section
  // below (item 4); independent of who's in the baptism list, so it's a complete missionary roster.
  const unitsWithMissionaries = Object.keys(d.missionaries)
    .filter((u) => u.trim() && (d.missionaries[u]?.length ?? 0) > 0)
    .sort();

  return (
    <PageScaffold
      tier={tier}
      header={
        <SectionTitle
          title="Upcoming Baptisms"
          count={items.length}
          byDate={!byUnit}
          onToggle={(v) => setByUnit(!v)}
        />
      }
    >
      {items.length === 0 ? (
        <p style={{ textAlign: 'center', padding: 32 }}>No baptisms scheduled yet.</p>
      ) : byUnit ? (
        <PerUnit items={items} today={today} tier={tier} />
      ) : (
        <PersonCardSections items={items} today={today} tier={tier} />
      )}

      {/* SECOND section (item 4): assigned/full-time missionaries — a full per-unit breakdown. */}
      {unitsWithMissionaries.length > 0 && (
        <MissionariesByUnitSection units={unitsWithMissionaries} tier={tier} />
      )}
    </PageScaffold>
  );
}

/** All people's cards, split into "needs attention — date passed" then "scheduled", laid out in
 *  responsive columns. Card-per-person (item 1). */
function PersonCardSections({ items, today, tier }: { items: Dated[]; today: Date; tier: ReturnType<typeof useTier> }) {
  const overdue = items.filter((i) => i.date.getTime() < today.getTime());
  const upcoming = items.filter((i) => i.date.getTime() >= today.getTime());
  return (
    <div className="stack" style={{ gap: 18 }}>
      {overdue.length > 0 && (
        <PersonCardGroup
          title="Needs attention — date has passed"
          icon="warning"
          color="var(--warning)"
          items={overdue}
          today={today}
          tier={tier}
          overdue
        />
      )}
      {upcoming.length > 0 && (
        <PersonCardGroup
          title="Scheduled"
          icon="event_available"
          color="var(--primary)"
          items={upcoming}
          today={today}
          tier={tier}
          overdue={false}
        />
      )}
    </div>
  );
}

function PersonCardGroup({
  title, icon, color, items, today, tier, overdue,
}: {
  title: string; icon: 'warning' | 'event_available'; color: string;
  items: Dated[]; today: Date; tier: ReturnType<typeof useTier>; overdue: boolean;
}) {
  return (
    <div>
      <div className="row" style={{ gap: 6, marginBottom: 8 }}>
        <Icon name={icon} size={16} color={color} />
        <strong className="small" style={{ color }}>
          {title}
        </strong>
        <CountBadge n={items.length} />
      </div>
      <Columns cols={colsFor(tier)}>
        {items.map((it) => (
          <BaptismPersonCard key={String(it.m['person_uuid'] ?? it.m['name'])} item={it} today={today} overdue={overdue} />
        ))}
      </Columns>
    </div>
  );
}

/** ONE card for ONE person being taught: date badge + countdown, unit, full notes, Golden Hour next
 *  steps, and the assigned missionaries who teach them (their unit's full-time missionaries). */
function BaptismPersonCard({ item, today, overdue }: { item: Dated; today: Date; overdue: boolean }) {
  const navigate = useNavigate();
  const { notes } = useDashboard();
  const m = item.m;
  const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
  const name = String(m['name'] ?? '—');
  const unitName = String(m['unit_name'] ?? '').trim();
  const missionaries = useUnitMissionaries(unitName);
  const note = id ? notes[id] : undefined;
  const steps = nextSteps(m);

  const accent = overdue ? 'var(--warning)' : 'var(--primary)';
  const accentHex = overdue ? '#ef6c00' : '#4554b8';
  const days = daysBetween(today, item.date);
  const rel = overdue
    ? `${-days} day${days === -1 ? '' : 's'} ago`
    : days === 0
      ? 'Today'
      : days === 1
        ? 'Tomorrow'
        : `in ${days} days`;

  return (
    <div className="card baptism-card">
      <div className="card__body">
        {/* Header: avatar + name + (tappable to detail), date badge on the right. */}
        <div className="row" style={{ alignItems: 'flex-start', gap: 12, justifyContent: 'space-between' }}>
          <button
            type="button"
            className="baptism-card__head"
            onClick={() => id && navigate(`/person/${encodeURIComponent(id)}`)}
          >
            <Avatar name={name} photoUrl={m['photo_url'] as string | undefined} size={44} />
            <span style={{ minWidth: 0 }}>
              <span className="baptism-card__name">{name}</span>
              {unitName && <span className="tiny muted" style={{ display: 'block' }}>{unitName}</span>}
            </span>
          </button>
          <div
            style={{
              width: 56,
              padding: '6px 0',
              textAlign: 'center',
              borderRadius: 10,
              background: hexA(accentHex, 0.1),
              flexShrink: 0,
            }}
          >
            <div className="tiny" style={{ color: accent, fontWeight: 700 }}>
              {fmtMonShort(item.date).toUpperCase()}
            </div>
            <div style={{ fontSize: 22, lineHeight: 1, color: accent, fontWeight: 700 }}>{item.date.getDate()}</div>
            <div className="tiny muted">{fmtWeekdayShort(item.date)}</div>
          </div>
        </div>

        <div className="tiny" style={{ color: accent, fontWeight: 600, marginTop: 6 }}>
          Planned baptism · {rel}
        </div>

        {/* Golden Hour chips — quick covenant-path glance + suggested next step. */}
        <div style={{ marginTop: 10 }}>
          <GoldenHourChips member={m} size={22} highlightNext />
        </div>

        {/* Next steps (the not-yet-done Golden Hour milestones for this person). */}
        {steps.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6 }}>
              Next steps
            </div>
            <div className="wrap" style={{ gap: 6, marginTop: 4 }}>
              {steps.map((ms) => (
                <span key={ms.abbr} className="chip" style={{ background: 'var(--surface-container-highest)', border: 'none', fontSize: 12 }}>
                  <Icon name="circle_outline" size={13} color={ms.color} />
                  {ms.label}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Full leader notes / comments for this person. */}
        {note?.text && (
          <div className="baptism-card__notes" style={{ marginTop: 10 }}>
            <div className="row tiny" style={{ gap: 4, alignItems: 'flex-start', color: 'var(--on-surface-variant)' }}>
              <Icon name="note" size={13} color="var(--primary)" />
              <span style={{ whiteSpace: 'pre-wrap', fontStyle: 'italic', minWidth: 0 }}>{note.text}</span>
            </div>
          </div>
        )}

        {/* Missionary info: who teaches them (their unit's assigned missionaries). */}
        <hr className="divider" style={{ margin: '12px 0 10px' }} />
        <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
          Missionaries
        </div>
        {missionaries.length > 0 ? (
          <MissionaryStrip missionaries={missionaries} />
        ) : (
          <p className="tiny muted" style={{ margin: 0 }}>No assigned missionaries on record for this ward.</p>
        )}
      </div>
    </div>
  );
}

/** The by-unit grouping toggle: one card per unit holding that unit's people-cards + missionary strip.
 *  Kept for leaders who prefer the unit-grouped layout. */
function PerUnit({ items, today, tier }: { items: Dated[]; today: Date; tier: ReturnType<typeof useTier> }) {
  const byUnit = new Map<string, Dated[]>();
  for (const it of items) {
    const u = String(it.m['unit_name'] ?? '—');
    if (!byUnit.has(u)) byUnit.set(u, []);
    byUnit.get(u)!.push(it);
  }
  const units = [...byUnit.keys()].sort();
  return (
    <Columns cols={Math.min(2, colsFor(tier))}>
      {units.map((u) => (
        <SectionCard key={u} title={u} icon="groups" trailing={<CountBadge n={byUnit.get(u)!.length} />}>
          <UnitMissionaryStrip unitName={u} />
          <div className="stack" style={{ gap: 12 }}>
            {byUnit.get(u)!.map((it) => (
              <BaptismPersonCard key={String(it.m['person_uuid'] ?? it.m['name'])} item={it} today={today} overdue={it.date.getTime() < today.getTime()} />
            ))}
          </div>
        </SectionCard>
      ))}
    </Columns>
  );
}

function UnitMissionaryStrip({ unitName }: { unitName: string }) {
  const list = useUnitMissionaries(unitName);
  if (list.length === 0) return null;
  return (
    <>
      <MissionaryStrip missionaries={list} />
      <hr className="divider" />
    </>
  );
}

/** Item 3 — the SECOND section below the people-cards: the assigned (full-time) missionaries per
 *  unit/ward. One card per unit; a clean empty state when a unit has none synced. */
function MissionariesByUnitSection({ units, tier }: { units: string[]; tier: ReturnType<typeof useTier> }) {
  if (units.length === 0) return null;
  return (
    <div style={{ marginTop: 26 }}>
      <div className="section-title" style={{ marginBottom: 8 }}>
        <div className="section-title__left">
          <span className="accent-bar" />
          <h2>Missionaries by Unit</h2>
          <CountBadge n={units.length} />
        </div>
      </div>
      <Columns cols={colsFor(tier)}>
        {units.map((u) => (
          <MissionariesSection key={u} unitName={u} title={u} />
        ))}
      </Columns>
    </div>
  );
}
