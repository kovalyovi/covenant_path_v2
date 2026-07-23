// Baptisms tab — a CARD PER PERSON (item 1). Each investigator with a planned (future) baptism date
// gets their OWN card showing: the planned date + countdown, their unit, full leader notes/comments,
// relevant covenant-path info, their Golden Hour next steps, and the assigned (full-time) missionaries
// for their unit (who teach them, as far as the synced data tells us — see the data-availability note).
//
// Overdue dates (the date already passed) surface first in a "needs attention" section; genuinely
// upcoming dates follow. A SECOND section below lists the assigned missionaries per unit/ward (item 3).
// Investigators only (N7). React rework of the former combined-timeline baptisms_view.

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDashboard } from '../../hooks/useDashboard';
import { usePersistentState } from '../../hooks/usePersistentState';
import { useTier, colsFor } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator, detailsOf } from '../../lib/member';
import { parseMemberDate, fmtMonShort, fmtWeekdayShort, dayOnly, daysBetween } from '../../logic/dates';
import { nextSteps } from '../../logic/milestones';
import { hexA, status } from '../../theme/tokens';
import { Icon } from '../../components/Icon';
import { Avatar, CountBadge, SectionCard } from '../../components/ui';
import { PageScaffold, SectionTitle, Columns } from '../../components/dashboard';
import { SectionCardSkeleton } from '../../components/Skeletons';
import { MissionaryStrip, MissionariesSection, useUnitMissionaries, baptismCardMissionaries } from '../../components/Missionaries';
import { NotesThread } from '../../components/NotesThread';
import { NextTransferBanner } from '../../components/TransferDates';
import { ManualMembersSection } from '../../components/ManualMembers';
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

  // EVERY unit the user can see (from members + the missionary roster), so the section below lists
  // wards WITHOUT missionaries too — each highlighted with a warning so the gap is obvious.
  const allUnits = [...new Set([
    ...d.members.map((m) => String(m['unit_name'] ?? '')),
    ...Object.keys(d.missionaries),
  ])].filter((u) => u.trim()).sort();

  // While the stake data loads, glimmer the page with the real "Upcoming Baptisms" header + a grid of
  // person-card skeletons, so the baptism cards fade in over their own shapes.
  if (d.loading && d.members.length === 0) {
    return (
      <PageScaffold
        tier={tier}
        header={<SectionTitle title="Upcoming Baptisms" count={0} byDate={!byUnit} onToggle={(v) => setByUnit(!v)} />}
      >
        <Columns cols={tier === 'mobile' ? 1 : 2}>
          {Array.from({ length: 4 }, (_, i) => (
            <SectionCardSkeleton key={i} lines={5} titleWidth={150} />
          ))}
        </Columns>
      </PageScaffold>
    );
  }

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
      <NextTransferBanner />

      {items.length === 0 ? (
        <p style={{ textAlign: 'center', padding: 32 }}>No baptisms scheduled yet.</p>
      ) : byUnit ? (
        <PerUnit items={items} today={today} tier={tier} />
      ) : (
        <PersonCardSections items={items} today={today} />
      )}

      {/* Leader-added baptism candidates (not yet in LCR): add / edit / remove, with baptism date +
          optional missionaries. Kept as its own block so it never disrupts the synced-card layout. */}
      <div style={{ marginTop: 20, maxWidth: 640 }}>
        <ManualMembersSection />
      </div>

      {/* SECOND section (item 4): assigned missionaries — a full per-unit breakdown, INCLUDING wards
          with none (highlighted with a warning). */}
      {allUnits.length > 0 && (
        <MissionariesByUnitSection units={allUnits} tier={tier} />
      )}
    </PageScaffold>
  );
}

/** All people's cards, split into "needs attention — date passed" then "scheduled", laid out in
 *  responsive columns. Card-per-person (item 1). */
function PersonCardSections({ items, today }: { items: Dated[]; today: Date }) {
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
          overdue={false}
        />
      )}
    </div>
  );
}

function PersonCardGroup({
  title, icon, color, items, today, overdue,
}: {
  title: string; icon: 'warning' | 'event_available'; color: string;
  items: Dated[]; today: Date; overdue: boolean;
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
      {/* #3c: a SINGLE column of [date pill | person card] rows for easier tracking + conversations.
          On desktop the column shrinks to the WIDEST card's content (capped) and all rows match it —
          so the cards aren't stretched edge-to-edge across a wide screen (see `.baptism-card-list`). */}
      <div className="baptism-card-list">
        {items.map((it) => (
          <BaptismPersonCard key={String(it.m['person_uuid'] ?? it.m['name'])} item={it} today={today} overdue={overdue} />
        ))}
      </div>
    </div>
  );
}

function _lessonTaught(level: unknown): boolean {
  const s = String(level ?? '');
  return s.length > 0 && s !== '0' && s !== '0.0';
}

/** #3: one pill per lesson — FILLED green when taught, with a person badge on the corner when a member
 *  was present for it. Reads `details.lessons[].principles[]` ({taughtLevel, memberPresent}). */
function LessonPills({ m }: { m: Member }) {
  const lessons = detailsOf(m)?.['lessons'];
  if (!Array.isArray(lessons) || lessons.length === 0) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 }}>
        Lessons
      </div>
      <div className="wrap" style={{ gap: 7 }}>
        {lessons.map((raw, i) => {
          const l = (raw ?? {}) as Record<string, unknown>;
          const principles = (l['principles'] as Array<Record<string, unknown>>) ?? [];
          const taught = principles.some((p) => _lessonTaught(p?.['taughtLevel']));
          const present = principles.some((p) => p?.['memberPresent'] === true);
          const label = String(l['label'] ?? `Lesson ${i + 1}`);
          return (
            <span
              key={i}
              title={`${label}${taught ? ' · taught' : ' · not yet'}${present ? ' · a member was present' : ''}`}
              aria-label={`${label}${taught ? ' taught' : ' not yet'}${present ? ', member present' : ''}`}
              style={{
                position: 'relative', display: 'inline-flex', alignItems: 'center', fontSize: 11, fontWeight: 600,
                padding: '3px 9px', borderRadius: 'var(--radius-pill)',
                border: `1.5px solid ${taught ? status.success : 'var(--outline)'}`,
                background: taught ? hexA(status.success, 0.12) : 'transparent',
                color: taught ? status.success : 'var(--on-surface-variant)',
              }}
            >
              {label}
              {present && (
                <span
                  title="A member was present"
                  style={{
                    position: 'absolute', top: -5, right: -5, width: 15, height: 15, borderRadius: '50%',
                    background: status.info, display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    border: '1.5px solid var(--surface)',
                  }}
                >
                  <Icon name="account" size={9} color="#fff" />
                </span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** ONE card for ONE person being taught: date badge + countdown, unit, full notes, Golden Hour next
 *  steps, and the assigned missionaries who teach them (their unit's full-time missionaries). */
// `nested` = this card sits inside a by-unit SectionCard, which already shows the unit's missionary
// strip — so we suppress the per-card Missionaries section to avoid showing them twice (the by-date
// view leaves nested=false and keeps the per-person strip). Exported for the regression test.
export function BaptismPersonCard({ item, today, overdue, nested = false }:
  { item: Dated; today: Date; overdue: boolean; nested?: boolean }) {
  const navigate = useNavigate();
  const m = item.m;
  const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
  const name = String(m['name'] ?? '—');
  const unitName = String(m['unit_name'] ?? '').trim();
  // Touch devices have no hover: the FIRST tap anywhere on the card reveals the "Add note"
  // affordance (see .baptism-card.is-revealed in components.css); hover/focus covers desktop.
  const [revealed, setRevealed] = useState(false);
  // Per-person card shows the (one) TEACHING companionship — senior couples are dropped here (they
  // still appear in the "Missionaries by Unit" section below).
  const missionaries = baptismCardMissionaries(useUnitMissionaries(unitName));
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
    // #3e: a narrow DATE pill on the LEFT, OUTSIDE the card; the person card sits to its right.
    <div className="row" style={{ gap: 12, alignItems: 'flex-start' }}>
      <div style={{ width: 58, flexShrink: 0, textAlign: 'center', paddingTop: 8 }}>
        <div className="tiny" style={{ color: accent, fontWeight: 700 }}>{fmtMonShort(item.date).toUpperCase()}</div>
        <div style={{ fontSize: 26, lineHeight: 1, color: accent, fontWeight: 800 }}>{item.date.getDate()}</div>
        <div className="tiny muted">{fmtWeekdayShort(item.date)}</div>
        <div className="tiny" style={{ color: accent, fontWeight: 600, marginTop: 4 }}>{rel}</div>
      </div>

      <div
        className={`card baptism-card${revealed ? ' is-revealed' : ''}`}
        style={{ flex: 1, minWidth: 0, borderLeft: `3px solid ${hexA(accentHex, 0.9)}` }}
        onClick={() => setRevealed(true)}
      >
        <div className="card__body">
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

          {/* #3b: lead with the leader's NOTES — the conversation about this person, as a chat-style
              thread with an in-card "Add note" (hover on desktop, tap-to-reveal on touch). */}
          <NotesThread member={m} />

          {/* #3b: the PATH toward baptism — the remaining steps (no covenant-path milestone pills). */}
          {steps.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6 }}>
                Path to baptism
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

          {/* #3: one pill per lesson — FILLED when taught, with a person indicator on the corner when
              a member was present for it. */}
          <LessonPills m={m} />

          {/* Missionary info: who teaches them (their unit's assigned missionaries). Hidden in the
              by-unit grouping (nested) — that view shows the unit's missionaries once at the card top. */}
          {!nested && (
            <>
              <hr className="divider" style={{ margin: '12px 0 10px' }} />
              <div className="tiny muted" style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 6 }}>
                Missionaries
              </div>
              {missionaries.length > 0 ? (
                <MissionaryStrip missionaries={missionaries} />
              ) : (
                <p className="tiny muted" style={{ margin: 0 }}>No assigned missionaries on record for this ward.</p>
              )}
            </>
          )}
        </div>
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
              <BaptismPersonCard key={String(it.m['person_uuid'] ?? it.m['name'])} item={it} today={today} overdue={it.date.getTime() < today.getTime()} nested />
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
