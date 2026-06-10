// Baptisms tab — people being taught who have a *planned* (future) baptism date (the missionary
// "baptismGoalDate"). React port of baptisms_view.dart: a combined date timeline or per-unit
// timelines (header toggle); dates already passed surface in a "needs attention — overdue" block
// on top, genuinely upcoming dates follow. Investigators only (N7).

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDashboard } from '../../hooks/useDashboard';
import { useTier, colsFor } from '../../hooks/useTier';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { parseMemberDate, fmtMonShort, fmtWeekdayShort, dayOnly, daysBetween } from '../../logic/dates';
import { hexA } from '../../theme/tokens';
import { Icon, type IconName } from '../../components/Icon';
import { Avatar, CountBadge, SectionCard } from '../../components/ui';
import { PageScaffold, SectionTitle, Columns, NoteLine } from '../../components/dashboard';
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
  const [byUnit, setByUnit] = useState(false);

  const today = dayOnly(new Date());
  const items: Dated[] = [];
  for (const m of d.members) {
    if (!isInvestigator(m)) continue;
    const dt = parseMemberDate(m['baptism_goal_date']);
    if (dt) items.push({ m, date: dayOnly(dt) });
  }
  items.sort((a, b) => a.date.getTime() - b.date.getTime());

  return (
    <PageScaffold
      tier={tier}
      header={
        <SectionTitle
          title="Prospective Baptisms"
          count={items.length}
          byDate={!byUnit}
          onToggle={(v) => setByUnit(!v)}
        />
      }
    >
      {items.length === 0 ? (
        <p style={{ textAlign: 'center', padding: 32 }}>No prospective baptisms with a planned date.</p>
      ) : byUnit ? (
        <PerUnit items={items} today={today} tier={tier} missionaries={d.missionaries} />
      ) : (
        <div style={{ maxWidth: 640, margin: '0 auto' }}>
          <Timeline items={items} today={today} />
        </div>
      )}
    </PageScaffold>
  );
}

function PerUnit({
  items,
  today,
  tier,
  missionaries,
}: {
  items: Dated[];
  today: Date;
  tier: ReturnType<typeof useTier>;
  missionaries: Record<string, Array<Record<string, unknown>>>;
}) {
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
          {(missionaries[u] ?? []).length > 0 && (
            <>
              <MissionaryStrip missionaries={missionaries[u]} />
              <hr className="divider" />
            </>
          )}
          <Timeline items={byUnit.get(u)!} today={today} embedded />
        </SectionCard>
      ))}
    </Columns>
  );
}

function Timeline({ items, today, embedded = false }: { items: Dated[]; today: Date; embedded?: boolean }) {
  const overdue = items.filter((i) => i.date.getTime() < today.getTime());
  const upcoming = items.filter((i) => i.date.getTime() >= today.getTime());
  return (
    <div className="stack">
      {overdue.length > 0 && (
        <DateSection
          title="Needs attention — date passed"
          icon="warning"
          color="var(--warning)"
          items={overdue}
          today={today}
          overdue
          embedded={embedded}
        />
      )}
      {upcoming.length > 0 && (
        <DateSection
          title="Scheduled"
          icon="event_available"
          color="var(--primary)"
          items={upcoming}
          today={today}
          overdue={false}
          embedded={embedded}
        />
      )}
      {overdue.length === 0 && upcoming.length === 0 && <p style={{ padding: 16 }}>No planned dates.</p>}
    </div>
  );
}

function DateSection({
  title,
  icon,
  color,
  items,
  today,
  overdue,
  embedded,
}: {
  title: string;
  icon: IconName;
  color: string;
  items: Dated[];
  today: Date;
  overdue: boolean;
  embedded: boolean;
}) {
  const byDate = new Map<number, Dated[]>();
  for (const it of items) {
    const key = it.date.getTime();
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key)!.push(it);
  }
  const dates = [...byDate.keys()].sort((a, b) => a - b);
  const rail = (
    <div className="stack">
      {dates.map((key, di) => (
        <div key={key}>
          {di > 0 && <hr className="divider" style={{ margin: '9px 0' }} />}
          <DateRow date={new Date(key)} people={byDate.get(key)!} today={today} overdue={overdue} />
        </div>
      ))}
    </div>
  );
  if (embedded) {
    return (
      <div>
        <div className="row" style={{ gap: 6, marginTop: 4 }}>
          <Icon name={icon} size={16} color={color} />
          <strong className="small" style={{ color }}>
            {title}
          </strong>
        </div>
        <div style={{ height: 8 }} />
        {rail}
      </div>
    );
  }
  return (
    <SectionCard title={title} icon={icon} iconColor={color}>
      {rail}
    </SectionCard>
  );
}

function DateRow({ date, people, today, overdue }: { date: Date; people: Dated[]; today: Date; overdue: boolean }) {
  const navigate = useNavigate();
  const accent = overdue ? 'var(--warning)' : 'var(--primary)';
  const accentHex = overdue ? '#ef6c00' : '#4554b8';
  const days = daysBetween(today, date);
  const rel = overdue
    ? `${-days} day${days === -1 ? '' : 's'} ago`
    : days === 0
      ? 'Today'
      : days === 1
        ? 'Tomorrow'
        : `in ${days} days`;
  return (
    <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
      <div
        style={{
          width: 54,
          padding: '6px 0',
          textAlign: 'center',
          borderRadius: 10,
          background: hexA(accentHex, 0.1),
          flexShrink: 0,
        }}
      >
        <div className="tiny" style={{ color: accent, fontWeight: 700 }}>
          {fmtMonShort(date).toUpperCase()}
        </div>
        <div style={{ fontSize: 22, lineHeight: 1, color: accent, fontWeight: 700 }}>{date.getDate()}</div>
        <div className="tiny muted">{fmtWeekdayShort(date)}</div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="tiny" style={{ color: overdue ? accent : 'var(--on-surface-variant)', fontWeight: 600 }}>
          {rel}
        </div>
        {people.map((p, i) => {
          const id = p.m['person_uuid'] != null ? String(p.m['person_uuid']) : '';
          return (
            <button
              key={i}
              type="button"
              className="member-row"
              style={{ borderTop: 'none', padding: '5px 0' }}
              onClick={() => id && navigate(`/person/${encodeURIComponent(id)}`)}
            >
              <Avatar name={String(p.m['name'] ?? '?')} photoUrl={p.m['photo_url'] as string | undefined} size={36} />
              <span className="member-row__main">
                <span className="member-row__name">{String(p.m['name'] ?? '—')}</span>
                <span className="tiny muted" style={{ display: 'block' }}>
                  {String(p.m['unit_name'] ?? '')}
                </span>
                <NoteLine uuid={id} />
              </span>
              <Icon name="chevron_right" size={18} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

function MissionaryStrip({ missionaries }: { missionaries: Array<Record<string, unknown>> }) {
  return (
    <div className="row" style={{ alignItems: 'flex-start', gap: 6 }}>
      <Icon name="volunteer" size={16} color="var(--primary)" />
      <div className="wrap" style={{ gap: 6 }}>
        {missionaries.map((m, i) => {
          const contact = [m['phone'], m['email']].filter((x) => x != null && String(x).length > 0).join('\n');
          return (
            <span
              key={i}
              className="chip"
              title={contact}
              style={{ background: hexA('#4554b8', 0.1), border: 'none', color: 'var(--primary)', fontSize: 12 }}
            >
              {String(m['name'] ?? '')}
            </span>
          );
        })}
      </div>
    </div>
  );
}
