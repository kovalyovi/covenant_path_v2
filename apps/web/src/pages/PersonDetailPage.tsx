// Full covenant-path detail for one member, laid out like LCR's "new member" record — React port of
// person_detail_page.dart. Driven by member.details (the rich one-work subtree); when that's null it
// falls back to the flat fields. Sections: covenant-path chips, sacrament dots, friends, priesthood /
// calling / ministering, temple ordinances & experiences, principles taught, self-reliance, flags,
// plus leader notes (RLS-scoped). The member is read from the loaded dashboard data by person_uuid.

import { useNavigate, useParams } from 'react-router-dom';
import { useDashboard } from '../hooks/useDashboard';
import type { Member } from '../lib/member';
import { detailsOf, freshness } from '../lib/member';
import {
  endowmentDisplay, completionOf, callingEligible, ministeringAssignmentEligible,
  aaronicEligible, melchizedekEligible, priesthoodEligible, templeRecommendEligible,
  patriarchalEligible, ageOf,
} from '../logic/milestones';
import { agoOrNever } from '../logic/dates';
import { Avatar, IconButton, SectionCard } from '../components/ui';
import { Icon, type IconName } from '../components/Icon';
import { GoldenHourChips } from '../components/GoldenHourChips';
import { CommentsSection } from '../components/CommentsSection';

export function PersonDetailPage() {
  const { id } = useParams();
  const d = useDashboard();
  const navigate = useNavigate();
  const member = d.members.find((m) => String(m['person_uuid'] ?? '') === id);

  if (!member) {
    return (
      <div className="app-shell">
        <DetailAppBar title="Member" uuid={undefined} onBack={() => navigate(-1)} />
        <main className="page">
          <div className="center-col" style={{ minHeight: '50vh' }}>
            <p className="muted">This member isn't in the current view.</p>
          </div>
        </main>
      </div>
    );
  }

  const name = String(member['name'] ?? '—');
  const details = detailsOf(member);
  const memberSince = String(details?.['memberSince'] ?? member['membership_duration'] ?? '');
  const isInvestigator = member['kind'] === 'investigator';
  const goalDate = String(member['baptism_goal_date'] ?? '');
  const baptismDate = String(member['baptism_date'] ?? '');
  const baptismLine = isInvestigator
    ? goalDate
      ? `Planned baptism ${goalDate}`
      : null
    : baptismDate && baptismDate !== 'needs-profile-api'
      ? `Baptized ${baptismDate}`
      : null;
  const uuid = member['person_uuid'] != null ? String(member['person_uuid']) : undefined;
  const sexLabel = member['sex'] === 'M' ? 'Male' : member['sex'] === 'F' ? 'Female' : '';
  const age = ageOf(member);
  const demo = [sexLabel, age].filter(Boolean).join(' · ');

  return (
    <div className="app-shell">
      <DetailAppBar title={name} uuid={uuid} onBack={() => navigate(-1)} />
      <main className="page">
        <div className="maxw" style={{ padding: '16px 16px 32px' }}>
          {/* header card */}
          <div
            className="card"
            style={{ background: 'var(--primary-container)', border: 'none', borderRadius: 'var(--radius-card)' }}
          >
            <div className="card__body row" style={{ alignItems: 'center', gap: 16 }}>
              <Avatar name={name} photoUrl={member['photo_url'] as string | undefined} size={60} />
              <div style={{ color: 'var(--on-primary-container)' }}>
                <h1 style={{ fontSize: '1.25rem' }}>{name}</h1>
                {String(member['unit_name'] ?? '') && <div>{String(member['unit_name'])}</div>}
                {memberSince && <div>{memberSince}</div>}
                {demo && <div className="small">{demo}</div>}
                {baptismLine && <div className="small">{baptismLine}</div>}
              </div>
            </div>
          </div>

          <SectionCard
            title="Covenant Path"
            iconNode={<CompletionRing pct={completionOf(member)} />}
          >
            <GoldenHourChips member={member} highlightNext labeled />
          </SectionCard>

          <RecordCard member={member} />

          {details && <RichBody member={member} d={details} />}

          {uuid && <CommentsSection member={member} />}
        </div>
      </main>
    </div>
  );
}

function DetailAppBar({ title, uuid, onBack }: { title: string; uuid?: string; onBack: () => void }) {
  return (
    <header className="appbar">
      <IconButton icon="chevron_left" label="Back" onClick={onBack} />
      <h1 className="appbar__title">{title}</h1>
      <span className="appbar__spacer" />
      {uuid && (
        <a
          className="iconbtn"
          /* /mlt = Member List Tool app: renders the person's covenant-path / "new member"
             record. The bare /records/member-profile/{uuid} path is a raw RSC data route the
             browser downloads instead of showing — hence the /mlt prefix. */
          href={`https://lcr.churchofjesuschrist.org/mlt/records/member-profile/${uuid}?lang=eng`}
          target="_blank"
          rel="noopener"
          aria-label="Open this person in LCR"
          title="Open this person in LCR"
        >
          <Icon name="open_in_new" size={22} />
        </a>
      )}
    </header>
  );
}

/** Two columns on wide screens, stacked on narrow. Mirrors `_RichBody`. */
function RichBody({ member, d }: { member: Member; d: Record<string, unknown> }) {
  // Eligibility-gated name sections: hide a section that doesn't APPLY to this person (no priesthood
  // for women, no calling for a child) — but never hide a section that has real recorded data.
  const priesthoodLines = strings(d['priesthoodOrdinations']);
  const callingLines = strings(d['callings']);
  const maLines = strings(d['ministeringAssignments']);
  const left = (
    <>
      <SacramentSection d={d} />
      <FriendsSection d={d} recordedYes={member['friends'] === 'Yes'} count={asNum(member['friends_count'])} />
      {(priesthoodEligible(member) || priesthoodLines.length > 0) && (
        <ListTextSection title="Priesthood Ordination" icon="premium" lines={priesthoodLines} emptyText="No priesthood ordination on record." />
      )}
      {(callingEligible(member) || callingLines.length > 0) && (
        <ListTextSection
          title="Calling"
          icon="badge"
          lines={callingLines}
          emptyText="Not yet been given a calling."
          emptyIsAlert
          recordedYes={member['calling'] === 'Yes'}
        />
      )}
      {(ministeringAssignmentEligible(member) || maLines.length > 0) && (
        <ListTextSection
          title="Ministering Assignment"
          icon="volunteer"
          lines={maLines}
          emptyText="Not yet received a ministering assignment."
          recordedYes={member['ministering_assignment'] === 'Yes'}
        />
      )}
      <NamesSection
        title="Ministering Brothers & Sisters"
        icon="diversity"
        names={[...strings(d['ministeringBrothers']), ...strings(d['ministeringSisters'])]}
        emptyText="No ministers assigned."
        recordedYes={member['ministering_brothers_sisters'] === 'Yes'}
      />
    </>
  );
  const right = (
    <>
      <TempleSection d={d} />
      <PrinciplesSection d={d} />
      <TogglesSection title="Self-Reliance Classes Completed" icon="rule" items={toggles(d['selfReliance'])} />
      <TagsSection d={d} />
    </>
  );
  return (
    <div className="detail-cols">
      <div>{left}</div>
      <div>{right}</div>
    </div>
  );
}

function SacramentSection({ d }: { d: Record<string, unknown> }) {
  const all = (d['sacrament'] as Array<Record<string, unknown>>) ?? [];
  if (all.length === 0) return null;
  const recent = 6;
  // newest-first stored; show most recent N rendered oldest→newest so the timeline reads L→R.
  const shown = all.slice(0, recent).reverse();
  const missed = missedCount(d, all);
  const GREEN = '#2e7d32';
  return (
    <SectionCard
      title="Attended Sacrament Meeting"
      icon="event_available"
      trailing={
        all.length > recent ? <span className="tiny muted">{all.length} recorded</span> : undefined
      }
    >
      <div className="wrap" style={{ gap: 14 }}>
        {shown.map((s, i) => (
          <div key={i} style={{ textAlign: 'center' }}>
            <div className="tiny muted">{String(s['label'] ?? '')}</div>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 26,
                height: 26,
                marginTop: 4,
                borderRadius: '50%',
                background: s['attended'] === true ? GREEN : 'transparent',
                border: `1.4px solid ${s['attended'] === true ? GREEN : 'var(--outline)'}`,
                color: '#fff',
              }}
            >
              {s['attended'] === true && <Icon name="check" size={16} />}
            </span>
          </div>
        ))}
      </div>
      {missed > 0 && (
        <p style={{ marginTop: 10, color: 'var(--danger)' }}>
          {missed} sacrament meeting{missed === 1 ? '' : 's'} missed
        </p>
      )}
    </SectionCard>
  );
}

function missedCount(d: Record<string, unknown>, list: Array<Record<string, unknown>>): number {
  const m = Number(d['sacramentMissed']);
  if (Number.isFinite(m)) return m;
  return list.filter((s) => s['attended'] !== true).length;
}

function FriendsSection({ d, recordedYes, count }: { d: Record<string, unknown>; recordedYes: boolean; count: number | null }) {
  const friends = (d['friends'] as Array<Record<string, unknown>>) ?? [];
  const n = count ?? (friends.length > 0 ? friends.length : null);
  return (
    <SectionCard title={n != null ? `Friends in the Church · ${n}` : 'Friends in the Church'} icon="handshake">
      {friends.length === 0 ? (
        count != null && count > 0 ? (
          <p className="muted">
            {count} friend{count === 1 ? '' : 's'} recorded (names not available).
          </p>
        ) : recordedYes ? (
          <RecordedYesNote />
        ) : (
          <p className="muted">No friends recorded yet.</p>
        )
      ) : (
        <div className="stack">
          {friends.some((f) => f['inStake'] === true) && <p className="small muted" style={{ marginBottom: 4 }}>Inside the Stake</p>}
          {friends.map((f, i) => (
            <div key={i} className="row" style={{ padding: '3px 0' }}>
              <Avatar name={String(f['name'] ?? '?')} size={30} />
              <div>
                <div>{String(f['name'] ?? '—')}</div>
                {String(f['unit'] ?? '') && <div className="small muted">{String(f['unit'])}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function RecordedYesNote() {
  return (
    <div className="row" style={{ alignItems: 'flex-start', gap: 6 }}>
      <Icon name="info" size={15} color="var(--warning)" />
      <span className="small" style={{ color: 'var(--warning)' }}>
        Recorded as yes — names are temporarily unavailable from LCR and will appear once its detail
        data loads on a future sync.
      </span>
    </div>
  );
}

function ListTextSection({
  title,
  icon,
  lines,
  emptyText,
  emptyIsAlert,
  recordedYes,
}: {
  title: string;
  icon: IconName;
  lines: string[];
  emptyText: string;
  emptyIsAlert?: boolean;
  recordedYes?: boolean;
}) {
  return (
    <SectionCard title={title} icon={icon}>
      {lines.length === 0 ? (
        recordedYes ? (
          <RecordedYesNote />
        ) : (
          <p style={{ color: emptyIsAlert ? 'var(--danger)' : 'var(--on-surface-variant)' }}>{emptyText}</p>
        )
      ) : (
        <div className="stack">
          {lines.map((l, i) => (
            <p key={i} style={{ padding: '2px 0' }}>
              {l}
            </p>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function NamesSection({
  title,
  icon,
  names,
  emptyText,
  recordedYes,
}: {
  title: string;
  icon: IconName;
  names: string[];
  emptyText: string;
  recordedYes?: boolean;
}) {
  return (
    <SectionCard title={title} icon={icon}>
      {names.length === 0 ? (
        recordedYes ? (
          <RecordedYesNote />
        ) : (
          <p className="muted">{emptyText}</p>
        )
      ) : (
        <div className="stack">
          {names.map((n, i) => (
            <div key={i} className="row" style={{ padding: '3px 0' }}>
              <Avatar name={n} size={28} />
              <span>{n}</span>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function TempleSection({ d }: { d: Record<string, unknown> }) {
  const experiences = toggles(d['templeExperiences']);
  const ordinances = strings(d['templeOrdinances']);
  if (experiences.length === 0 && ordinances.length === 0) return null;
  return (
    <SectionCard title="Temple Ordinances and Experiences" icon="premium">
      {experiences.map((t, i) => (
        <ToggleRow key={i} label={t[0]} on={t[1]} />
      ))}
      {ordinances.length > 0 && <div style={{ height: 8 }} />}
      {ordinances.map((o, i) => (
        <p key={i} style={{ padding: '2px 0' }}>
          {o}
        </p>
      ))}
    </SectionCard>
  );
}

function PrinciplesSection({ d }: { d: Record<string, unknown> }) {
  const lessons = (d['lessons'] as Array<Record<string, unknown>>) ?? [];
  if (lessons.length === 0) return null;
  const GREEN = '#2e7d32';
  return (
    <SectionCard
      title="Principles Taught"
      icon="menu_book"
      trailing={
        <span className="row tiny" style={{ gap: 4, color: GREEN }}>
          <Icon name="account" size={16} color={GREEN} />= Member Present
        </span>
      }
    >
      <div className="stack" style={{ gap: 12 }}>
        {lessons.map((l, li) => (
          <div key={li}>
            <div style={{ color: GREEN, fontWeight: 500 }}>{String(l['name'] ?? '')}</div>
            <div className="wrap" style={{ gap: 6, marginTop: 6 }}>
              {((l['principles'] as Array<Record<string, unknown>>) ?? []).map((p, pi) => {
                const taught = principleTaught(p['taughtLevel']);
                const present = p['memberPresent'] === true;
                return (
                  <span
                    key={pi}
                    title={`${String(p['name'] ?? '')} — ${taught ? 'taught' : 'not yet'}${present ? ' (member present)' : ''}`}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: 22,
                      height: 22,
                      borderRadius: '50%',
                      background: taught ? GREEN : 'transparent',
                      border: `1.4px solid ${GREEN}`,
                      color: taught ? '#fff' : GREEN,
                    }}
                  >
                    {present && <Icon name="account" size={13} />}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function principleTaught(level: unknown): boolean {
  if (level == null) return false;
  const s = String(level);
  return s.length > 0 && s !== '0' && s !== '0.0';
}

function TogglesSection({ title, icon, items }: { title: string; icon: IconName; items: Array<[string, boolean]> }) {
  if (items.length === 0) return null;
  return (
    <SectionCard title={title} icon={icon}>
      {items.map((t, i) => (
        <ToggleRow key={i} label={t[0]} on={t[1]} />
      ))}
    </SectionCard>
  );
}

function ToggleRow({ label, on }: { label: string; on: boolean }) {
  const GREEN = '#2e7d32';
  return (
    <div
      className="row"
      style={{
        margin: '3px 0',
        padding: '9px 12px',
        borderRadius: 10,
        background: on ? 'rgba(46,125,50,0.08)' : 'color-mix(in srgb, var(--surface-container-highest) 40%, transparent)',
      }}
    >
      <Icon name={on ? 'check_circle' : 'circle_outline'} size={20} color={on ? GREEN : 'var(--outline)'} />
      <span style={{ fontWeight: on ? 500 : 400 }}>{label}</span>
    </div>
  );
}

function TagsSection({ d }: { d: Record<string, unknown> }) {
  const tags = strings(d['tags']);
  if (tags.length === 0) return null;
  return (
    <SectionCard title="Flags" icon="warning">
      <div className="wrap">
        {tags.map((t, i) => (
          <span key={i} className="chip" style={{ background: '#ffe082', border: 'none', color: '#5d4037' }}>
            {t}
          </span>
        ))}
      </div>
    </SectionCard>
  );
}

/** Circular completion ring for the Covenant Path header: arc fills with the member's eligible-only
 *  milestone completion, and goes solid green with a check at 100%. */
function CompletionRing({ pct, size = 30 }: { pct: number; size?: number }) {
  const done = pct >= 1;
  const stroke = 3;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const GREEN = '#2e7d32';
  const color = done ? GREEN : 'var(--primary)';
  return (
    <span
      style={{ position: 'relative', display: 'inline-flex', width: size, height: size, flex: '0 0 auto' }}
      title={`Covenant Path ${Math.round(pct * 100)}% complete${done ? ' — all steps done' : ''}`}
      aria-label={`Covenant Path ${Math.round(pct * 100)} percent complete`}
    >
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--outline-variant)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - Math.max(0, Math.min(1, pct)))}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset .45s ease' }}
        />
      </svg>
      {done && (
        <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="check" size={15} color={GREEN} />
        </span>
      )}
    </span>
  );
}

/** "Record": every covenant-path status that APPLIES to this member, as key→value with stale clocks —
 *  the comprehensive at-a-glance summary. Eligibility-gated (no priesthood rows for women, no calling
 *  for a child); endowment shows "N/A" for the not-yet-eligible. Works from flat fields, so it renders
 *  even when the rich `details` subtree is absent. */
function RecordCard({ member }: { member: Member }) {
  const rows: Array<[string, string, string]> = ([
    ['Friends', 'friends', disp(member['friends']), true],
    ['Calling', 'calling', disp(member['calling']), callingEligible(member)],
    ['Has ministers', 'ministering_brothers_sisters', disp(member['ministering_brothers_sisters']), true],
    ['Ministering assignment', 'ministering_assignment', disp(member['ministering_assignment']), ministeringAssignmentEligible(member)],
    ['Aaronic Priesthood', 'aaronic_priesthood', disp(member['aaronic_priesthood']), aaronicEligible(member)],
    ['Melchizedek Priesthood', 'melchizedek_priesthood', disp(member['melchizedek_priesthood']), melchizedekEligible(member)],
    ['Temple recommend', 'temple_recommend', disp(member['temple_recommend']), templeRecommendEligible(member)],
    ['Endowment', 'living_ordinance', disp(endowmentDisplay(member)), true],
    ['Patriarchal blessing', 'patriarchal_blessing', disp(member['patriarchal_blessing']), patriarchalEligible(member)],
  ] as Array<[string, string, string, boolean]>)
    .filter(([, , , show]) => show)
    .map(([label, key, value]) => [label, key, value]);
  return (
    <SectionCard title="Record" icon="badge">
      <div>
        {rows.map(([label, key, value]) => {
          const fr = freshness(member, key);
          const stale = fr.state === 'warn' || fr.state === 'error' || fr.state === 'never';
          return (
            <div key={key} className="row" style={{ justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid var(--outline-variant)' }}>
              <span className="muted">{label}</span>
              <span className="row" style={{ gap: 6, alignItems: 'center' }}>
                {stale && (
                  <Icon
                    name="schedule"
                    size={13}
                    color={fr.state === 'warn' ? '#f9a825' : '#e53935'}
                    title={fr.state === 'never' ? 'Not fetched yet' : `Last fetched ${agoOrNever(fr.fetched)}`}
                  />
                )}
                <strong>{value}</strong>
              </span>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

/** Clean a status value for display: sentinels (needs-profile-api / blocked) → "—" (unknown). */
function disp(v: unknown): string {
  const s = String(v ?? '');
  if (!s || s === 'needs-profile-api' || s.startsWith('blocked')) return '—';
  return s;
}

// ---- helpers ---------------------------------------------------------------

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.map((e) => String(e)).filter((s) => s.length > 0) : [];
}

function toggles(v: unknown): Array<[string, boolean]> {
  if (!Array.isArray(v)) return [];
  return v
    .filter((e) => e && typeof e === 'object')
    .map((e) => [String((e as Record<string, unknown>)['name'] ?? ''), (e as Record<string, unknown>)['done'] === true] as [string, boolean])
    .filter((t) => t[0].length > 0);
}

function asNum(v: unknown): number | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
