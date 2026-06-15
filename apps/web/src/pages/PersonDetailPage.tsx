// Full covenant-path detail for one member, laid out like LCR's "new member" record — React port of
// person_detail_page.dart. Driven by member.details (the rich one-work subtree); when that's null it
// falls back to the flat fields. Sections: covenant-path chips, sacrament dots, friends, priesthood /
// calling / ministering, temple ordinances & experiences, principles taught, self-reliance, flags,
// plus leader notes (RLS-scoped). The member is read from the loaded dashboard data by person_uuid.

import { useEffect, useRef, useState } from 'react';
import { useDashboard } from '../hooks/useDashboard';
import type { Member } from '../lib/member';
import { detailsOf, freshness } from '../lib/member';
import { fieldDisplay } from '../logic/fieldDisplay';
import {
  endowmentDisplay, completionOf, callingEligible, ministeringAssignmentEligible,
  priesthoodEligible, templeRecommendEligible, patriarchalEligible, ageOf, nextSteps,
} from '../logic/milestones';
import { agoOrNever, parseMemberDate, tenure } from '../logic/dates';
import { sacramentWindow, SACRAMENT_WINDOW_WEEKS, attendanceBucket } from '../logic/kpis';
import { attendanceColor } from '../theme/tokens';
import { Avatar, SectionCard } from '../components/ui';
import { Icon, type IconName } from '../components/Icon';
import { GoldenHourChips } from '../components/GoldenHourChips';
import { MissionariesSection } from '../components/Missionaries';
import { NotesSection } from '../components/NotesSection';

/** LCR "member profile" deep link for a person uuid. (/mlt = the Member List Tool app, which renders
 *  the covenant-path record; the bare /records path is a raw RSC route the browser just downloads.) */
export function personLcrUrl(uuid: string): string {
  return `https://lcr.churchofjesuschrist.org/mlt/records/member-profile/${uuid}?lang=eng`;
}

/** The person-detail BODY — rendered inside the dashboard's side/bottom sheet (the Modal supplies the
 *  frame: title = the member's name, the "open in LCR" action, and close). `id` is the person_uuid;
 *  `autoEdit` opens the note editor straight away (from a long-press on a list row). */
export function PersonDetailBody({ id, autoEdit }: { id: string; autoEdit: boolean }) {
  const d = useDashboard();
  const member = d.members.find((m) => String(m['person_uuid'] ?? '') === id);

  if (!member) {
    return (
      <div className="center-col" style={{ minHeight: 200 }}>
        <p className="muted">{d.loading ? 'Loading…' : "This member isn't in the current view."}</p>
      </div>
    );
  }

  const name = String(member['name'] ?? '—');
  const details = detailsOf(member);
  const memberSince = String(details?.['memberSince'] ?? member['membership_duration'] ?? '');
  const isInvestigator = member['kind'] === 'investigator';
  const goalDate = String(member['baptism_goal_date'] ?? '');
  const baptismDate = String(member['baptism_date'] ?? '');
  const baptismDt = parseMemberDate(baptismDate);
  const tenureStr = baptismDt ? tenure(baptismDt) : '';
  // Baptized <date> and, in parentheses, how long they've been a member (#person-detail).
  const baptismLine = isInvestigator
    ? goalDate
      ? `Planned baptism ${goalDate}`
      : null
    : baptismDt
      ? `Baptized ${baptismDate}${tenureStr ? ` (${tenureStr})` : ''}`
      : null;
  const uuid = member['person_uuid'] != null ? String(member['person_uuid']) : undefined;
  const sexLabel = member['sex'] === 'M' ? 'Male' : member['sex'] === 'F' ? 'Female' : '';
  const age = ageOf(member);
  const demo = [sexLabel, age].filter(Boolean).join(' · ');

  return (
    <div style={{ paddingTop: 4, paddingBottom: 16 }}>
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
            {baptismLine && <div style={{ fontWeight: 600, marginTop: 2 }}>{baptismLine}</div>}
            {demo && <div className="small">{demo}</div>}
            {memberSince && memberSince !== baptismLine && <div className="small">{memberSince}</div>}
          </div>
        </div>
      </div>

      <SectionCard
        title="Covenant Path"
        iconNode={<CompletionRing pct={completionOf(member)} />}
        /* #10c: a completeness border — green at 100%, amber while in progress, red at none. */
        tone={completionOf(member) >= 1 ? 'good' : completionOf(member) > 0 ? 'warn' : 'bad'}
      >
        {/* #10a: the labeled chips are the SINGLE covenant-path representation — each carries its
            ✓ done / ○ not yet / ⚠ data-issue state AND a tap tooltip. */}
        <GoldenHourChips member={member} highlightNext labeled />
      </SectionCard>

      {/* Investigator (being-taught) extras (item 2): unit, the full-time missionaries who teach them,
          and their next steps — the not-yet-done Golden Hour milestones. */}
      {isInvestigator && <InvestigatorSection member={member} unitName={String(member['unit_name'] ?? '')} />}

      {details ? (
        <RichBody member={member} d={details} isAdmin={d.isAdmin} />
      ) : (
        <StatusSections member={member} isAdmin={d.isAdmin} />
      )}

      {uuid && <NotesSection member={member} autoEdit={autoEdit} />}
    </div>
  );
}

/** Item 2 — for a friend / investigator (being taught): their unit, the full-time missionaries who
 *  teach them (their unit's assigned missionaries — the best link the synced data gives), and the
 *  next steps they need to take (their not-yet-done Golden Hour milestones, from the shared logic). */
function InvestigatorSection({ member, unitName }: { member: Member; unitName: string }) {
  const steps = nextSteps(member);
  return (
    <>
      <SectionCard title="Unit" icon="groups">
        {unitName ? (
          <p style={{ margin: 0 }}>{unitName}</p>
        ) : (
          <p className="muted" style={{ margin: 0 }}>No unit on record.</p>
        )}
      </SectionCard>
      <MissionariesSection unitName={unitName} title="Missionaries Teaching" />
      <SectionCard title="Next Steps" icon="checklist">
        {steps.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>All Golden Hour steps are complete — ready for baptism.</p>
        ) : (
          <ul className="gh-rows" role="list">
            {steps.map((ms) => (
              <li key={ms.abbr} className="gh-row gh-row--not-done" title={ms.description}>
                <Icon name="circle_outline" size={18} color={ms.color} />
                <span className="gh-row__label">{ms.label}</span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </>
  );
}

/** Two columns on wide screens, stacked on narrow. Mirrors `_RichBody`. */
function RichBody({ member, d, isAdmin }: { member: Member; d: Record<string, unknown>; isAdmin: boolean }) {
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
          emptyText="No calling yet."
          emptyIsAlert
          recordedYes={member['calling'] === 'Yes'}
        />
      )}
      {(ministeringAssignmentEligible(member) || maLines.length > 0) && (
        <ListTextSection
          title="Ministering Assignment"
          icon="volunteer"
          lines={maLines}
          emptyText="No ministering assignment yet."
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
      <StatusSections member={member} isAdmin={isAdmin} />
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
  // Attendance over the LAST 8 weeks of data (not the whole history — we no longer say "52 missed
  // of 54"). The window is the most recent up-to-8 weekly records; fewer when there's less data.
  const win = sacramentWindow(all);
  if (win == null) return null;
  const bucket = attendanceBucket(win);
  const summaryColor = attendanceColor(bucket.level);
  // newest-first; drop FUTURE-dated Sundays (upcoming weeks a synced calendar may include) so only
  // meetings up to today show in the most-recent-8 window.
  const now = Date.now();
  const withDates = all
    .map((s) => ({ s, dt: parseMemberDate(s['date']) }))
    .filter((x) => x.dt == null || x.dt.getTime() <= now);
  const anyDates = withDates.some((x) => x.dt != null);
  const ordered = anyDates
    ? [...withDates].sort((a, b) => (b.dt?.getTime() ?? -Infinity) - (a.dt?.getTime() ?? -Infinity))
    : withDates;
  // Newest → oldest (most recent week first).
  const shown = ordered.slice(0, SACRAMENT_WINDOW_WEEKS).map((x) => x.s);
  const n = Math.max(1, shown.length);
  return (
    <SectionCard
      title="Sacrament Attendance"
      icon="event_available"
      trailing={
        <span className="row" style={{ gap: 4, color: summaryColor, fontWeight: bucket.bold ? 800 : 700 }}>
          {bucket.level === 'none' && <Icon name="info" size={14} color={summaryColor} />}
          {bucket.label}
        </span>
      }
    >
      {/* #10b: a connected timeline (Ricky-style) — a line threads the weekly markers; PRESENT is a
          filled ✓ and ABSENT is a hollow ✕ (shape, not just color, so it reads for color-blind users).
          Horizontally scrollable on a narrow phone. */}
      {/* #10b: connected weekly timeline — horizontal on desktop (scrolls if long), a vertical COLUMN on
          phones (nicer + no sideways scroll). PRESENT = filled ✓, ABSENT = hollow ✕ (shape, not color). */}
      <div className="sacrament-timeline">
        <div className="sacrament-track" style={{ minWidth: n * 40 }}>
          <div className="sacrament-line" style={{ left: `${50 / n}%`, right: `${50 / n}%` }} />
          {shown.map((s, i) => {
            const present = s['attended'] === true;
            const label = String(s['label'] ?? '');
            return (
              <div key={i} className="sacrament-mark">
                {/* Radio-button marker (matches the principle dots): present = filled, absent = empty. */}
                <span
                  role="img"
                  aria-label={`${label || `week ${i + 1}`} — ${present ? 'present' : 'absent'}`}
                  title={`${label} — ${present ? 'present' : 'absent'}`}
                  className={`sacrament-dot${present ? ' sacrament-dot--present' : ''}`}
                />
                <span className="muted sacrament-mark__label">{label}</span>
              </div>
            );
          })}
        </div>
      </div>
      <p style={{ marginTop: 12, color: summaryColor }}>
        Attended <b>{win.attended}</b> of <b>{win.total}</b> over the last{' '}
        {win.total === 1 ? 'week' : `${win.total} weeks`}
      </p>
    </SectionCard>
  );
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
          {/* A friend is stored as a member-uuid reference; the NAME is resolved from this stake's
              synced directory. A friend in a unit you can't see (or not yet in the directory) won't
              resolve — show an honest placeholder rather than a bare "—". */}
          {friends.map((f, i) => {
            const fname = String(f['name'] ?? '').trim();
            return (
              <div key={i} className="row" style={{ padding: '3px 0' }}>
                <Avatar name={fname || '?'} size={30} />
                <div style={{ minWidth: 0 }}>
                  {fname ? (
                    <div>{fname}</div>
                  ) : (
                    <div className="muted" style={{ fontStyle: 'italic' }}>Name not available (outside your synced units)</div>
                  )}
                  {String(f['unit'] ?? '') && <div className="small muted">{String(f['unit'])}</div>}
                </div>
              </div>
            );
          })}
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
        <span className="row tiny" style={{ gap: 8 }}>
          <span className="row" style={{ gap: 4 }}>
            <span className="principle-dot principle-dot--legend principle-dot--filled" /> taught
          </span>
          <span className="row" style={{ gap: 4 }}>
            <span className="principle-dot principle-dot--legend" /> not yet
          </span>
          <span className="row" style={{ gap: 4, color: GREEN }}>
            <Icon name="account" size={14} color={GREEN} /> present
          </span>
        </span>
      }
    >
      <div className="stack" style={{ gap: 0 }}>
        {lessons.map((l, li) => {
          const principles = (l['principles'] as Array<Record<string, unknown>>) ?? [];
          const taughtCount = principles.filter((p) => principleTaught(p['taughtLevel'])).length;
          return (
            <div
              key={li}
              className="lesson-block"
              style={li > 0 ? { borderTop: '1px solid var(--outline)' } : undefined}
            >
              <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontWeight: 600 }}>{String(l['name'] ?? `Lesson ${li + 1}`)}</span>
                {principles.length > 0 && (
                  <span className="tiny muted">{taughtCount}/{principles.length} taught</span>
                )}
              </div>
              {principles.length > 0 && (
                <div className="principle-row">
                  {principles.map((p, pi) => (
                    <PrincipleDot
                      key={pi}
                      name={String(p['name'] ?? '')}
                      taught={principleTaught(p['taughtLevel'])}
                      present={p['memberPresent'] === true}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

/** One principle within a lesson: a bordered circle (empty = not taught, filled = taught), with a
 *  member-present marker. Hover OR click/tap reveals what the principle is (its name) + status. */
function PrincipleDot({ name, taught, present }: { name: string; taught: boolean; present: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const status = taught ? 'Taught' : 'Not yet taught';
  const label = name || 'Principle';

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    // `click` (not `mousedown`) so the opening tap can't immediately re-close the tooltip.
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <span ref={ref} className="principle-dot-wrap">
      <button
        type="button"
        className={`principle-dot principle-dot--btn${taught ? ' principle-dot--filled' : ''}`}
        aria-expanded={open}
        aria-label={`${label} — ${status}${present ? ', member present' : ''}`}
        title={`${label} — ${status}${present ? ' (member present)' : ''}`}
        onClick={() => setOpen((o) => !o)}
      >
        {present && <Icon name="account" size={12} />}
      </button>
      <span role="tooltip" className={`gh-tip${open ? ' gh-tip--open' : ''}`}>
        <b>{label}</b> · {status}
        {present && <span className="gh-tip__body">The member was present when this was taught.</span>}
      </span>
    </span>
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

/** Each tracked covenant-path status that lacks its own rich section, shown as its OWN section card
 *  (like "Attended Sacrament Meeting"): Temple Recommend, Endowment, Patriarchal Blessing. Eligibility-
 *  gated (endowment shows "N/A" for the not-yet-eligible). Works from flat fields, so it renders with
 *  or without the rich `details` subtree. */
function StatusSections({ member, isAdmin }: { member: Member; isAdmin: boolean }) {
  return (
    <>
      {templeRecommendEligible(member) && (
        <StatusSection title="Temple Recommend" icon="premium" member={member} field="temple_recommend"
          raw={member['temple_recommend']} isAdmin={isAdmin} />
      )}
      <StatusSection title="Endowment" icon="premium" member={member} field="living_ordinance"
        raw={endowmentDisplay(member)} isAdmin={isAdmin} />
      {patriarchalEligible(member) && (
        <StatusSection title="Patriarchal Blessing" icon="menu_book" member={member} field="patriarchal_blessing"
          raw={member['patriarchal_blessing']} isAdmin={isAdmin} />
      )}
    </>
  );
}

/** A single covenant-path status, rendered under the CLIENT DISPLAY CONTRACT (item 5):
 *   - a real value (Active/Yes/No/…) shows verbatim (green when it's a "good" Active/Yes);
 *   - "N/A" (not eligible) shows quietly, NEVER a warning;
 *   - a DATA ISSUE (the needs-profile-api sentinel OR null/empty) shows a ⚠ warning indicator and
 *     never the raw sentinel string (admins additionally see the raw sentinel text for diagnosis).
 *  The separate freshness "schedule" chip (stale-but-known) is still shown for a real value. */
function StatusSection({ title, icon, member, field, raw, isAdmin }: {
  title: string; icon: IconName; member: Member; field: string; raw: unknown; isAdmin: boolean;
}) {
  const fd = fieldDisplay(raw, isAdmin);
  const good = fd.status === 'value' && (fd.text === 'Active' || fd.text === 'Yes');
  const fr = freshness(member, field);
  const stale = fd.status === 'value' && (fr.state === 'warn' || fr.state === 'error' || fr.state === 'never');
  return (
    <SectionCard title={title} icon={icon}>
      <span className="row" style={{ gap: 8, alignItems: 'center' }}>
        {fd.warn ? (
          <span className="row" style={{ gap: 6, alignItems: 'center', color: '#f9a825' }}>
            <Icon name="warning" size={16} color="#f9a825" title="Data issue — value unavailable" />
            <span className="small">Not available yet</span>
            {/* Admins see the raw sentinel for diagnosis; leaders never do. */}
            {isAdmin && fd.text && <span className="tiny muted">({fd.text})</span>}
          </span>
        ) : (
          <strong style={{ fontSize: '1.05rem', color: good ? '#2e7d32' : undefined }}>{fd.text}</strong>
        )}
        {stale && (
          <Icon name="schedule" size={13} color={fr.state === 'warn' ? '#f9a825' : '#e53935'}
            title={fr.state === 'never' ? 'Not fetched yet' : `Last fetched ${agoOrNever(fr.fetched)}`} />
        )}
      </span>
    </SectionCard>
  );
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
