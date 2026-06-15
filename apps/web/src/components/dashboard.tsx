// Shared dashboard building blocks — the React equivalents of the Flutter `_Page`, `_SectionTitle`,
// `_BigHeader`, `_SyncingBanner`, the freshness chip, `_MemberRow`, `_UnitGrid`, `_DateList`,
// `_OrgFilterBar`, and the small notes/pills. The tab views compose these so the layouts match.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Member } from '../lib/member';
import {
  ageOf, orgInfo, orgResponsibilityNote, type OrgBucket, ORG_BUCKETS,
} from '../logic/milestones';
import {
  parseMemberDate, fmtLong, fmtMonthDayYear, baptismElapsed, ago, staleness, fmtDateTime,
} from '../logic/dates';
import { assignUnitColors } from '../logic/kpis';
import { hexA } from '../theme/tokens';
import { Icon, type IconName } from './Icon';
import { Avatar, CountBadge, Segmented, SectionCard } from './ui';
import { OrgBadge, AttendancePill } from './Badges';
import { GoldenHourChips } from './GoldenHourChips';
import { Modal } from './Modal';
import type { Tier } from '../hooks/useTier';
import { colsFor } from '../hooks/useTier';
import { useDashboard } from '../hooks/useDashboard';

// ---- Page scaffold ----------------------------------------------------------------------------

export function PageScaffold({
  tier, header, children, maxWidth,
}: {
  tier: Tier;
  header: ReactNode;
  children: ReactNode;
  /** Constrain the column to a content-appropriate width (overrides the default 1280px cap) so a
   *  single-column view doesn't stretch edge-to-edge on wide screens (#24/#25). */
  maxWidth?: number;
}) {
  return (
    <div
      className={tier === 'mobile' ? 'page__inner page__inner--mobile' : 'page__inner'}
      style={maxWidth ? { maxWidth } : undefined}
    >
      {header}
      <div style={{ height: 8 }} />
      {children}
    </div>
  );
}

/** Lays children into `cols` balanced columns (CSS grid). Mirrors `_Columns`. */
export function Columns({ cols, children }: { cols: number; children: ReactNode[] }) {
  const list = children.filter(Boolean);
  if (cols <= 1 || list.length <= 1) {
    return <div className="stack" style={{ gap: 0 }}>{list}</div>;
  }
  // Distribute round-robin into N column stacks (variable-height friendly), like the Flutter version.
  const buckets: ReactNode[][] = Array.from({ length: cols }, () => []);
  list.forEach((c, i) => buckets[i % cols].push(c));
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: 12, alignItems: 'start' }}>
      {buckets.map((b, i) => (
        <div key={i} className="stack" style={{ gap: 0 }}>
          {b}
        </div>
      ))}
    </div>
  );
}

// ---- Headers ----------------------------------------------------------------------------------

interface SectionTitleProps {
  title: string;
  count: number;
  byDate: boolean;
  onToggle: (byDate: boolean) => void;
  ascending?: boolean;
  onAscToggle?: () => void;
}

/** Title + count on the left; a Unit/Date toggle (and optional asc/desc) on the right. Mirrors `_SectionTitle`. */
export function SectionTitle({ title, count, byDate, onToggle, ascending, onAscToggle }: SectionTitleProps) {
  return (
    <div className="section-title">
      <div className="section-title__left">
        <span className="accent-bar" />
        <h2>{title}</h2>
        <CountBadge n={count} />
      </div>
      <div className="row" style={{ gap: 8 }}>
        {onAscToggle && <SortToggle ascending={ascending === true} onClick={onAscToggle} />}
        <Segmented<'unit' | 'date'>
          ariaLabel="Group by"
          value={byDate ? 'date' : 'unit'}
          onChange={(v) => onToggle(v === 'date')}
          options={[
            { value: 'unit', label: 'Unit', icon: 'groups' },
            { value: 'date', label: 'Date', icon: 'event' },
          ]}
        />
      </div>
    </div>
  );
}

function SortToggle({ ascending, onClick }: { ascending: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="chip"
      onClick={onClick}
      title={ascending ? 'Oldest first (tap for newest)' : 'Newest first (tap for oldest)'}
      style={{ background: 'var(--surface-container-highest)', border: 'none' }}
    >
      <Icon name={ascending ? 'arrow_up' : 'arrow_down'} size={15} />
      {ascending ? 'Oldest' : 'Newest'}
    </button>
  );
}

export function BigHeader({ text, subtitle }: { text: string; subtitle: string }) {
  return (
    <div className="big-header">
      <span className="accent-bar" style={{ height: 34 }} />
      <div>
        <h2>{text}</h2>
        <p className="small muted">{subtitle}</p>
      </div>
    </div>
  );
}

/** A centered, muted one-liner (org-responsibility explanation under a filter). Mirrors `_SubtleNote`. */
export function SubtleNote({ text }: { text: string }) {
  return (
    <p className="small muted" style={{ textAlign: 'center', padding: '0 20px' }}>
      {text}
    </p>
  );
}

// ---- Banners ----------------------------------------------------------------------------------

/** Live "syncing your stake" banner with an elapsed-time counter (item 10). Mirrors `_SyncingBanner`. */
export function SyncingBanner({ startedAt }: { startedAt: string | null }) {
  const [, force] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const t = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [startedAt]);
  let elapsed = '';
  if (startedAt) {
    const d = Math.max(0, Date.now() - new Date(startedAt).getTime());
    const m = Math.floor(d / 60000);
    const s = Math.floor(d / 1000) % 60;
    elapsed = m > 0 ? ` · ${m}m ${s}s elapsed` : ` · ${s}s elapsed`;
  }
  return (
    <div className="banner banner--sync" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>Syncing your stake from LCR — fresh data in a few minutes{elapsed}.</span>
    </div>
  );
}

export function StaleBanner({
  state = 'revoked',
  isProvider = false,
  lastError = null,
  onReenroll,
}: {
  state?: string;
  isProvider?: boolean;
  lastError?: string | null;
  onReenroll: () => void;
  onSyncNow?: () => void; // accepted for caller compatibility; a dead credential can't sync until re-auth
}) {
  const revoked = state === 'revoked';
  // Message + action depend on revoked vs stale, and whether YOU are the credential's provider.
  let message: string;
  let actionLabel: string;
  if (revoked) {
    message = 'Sync paused — credential revoked. Re-enroll to resume daily updates.';
    actionLabel = 'Re-enroll';
  } else if (isProvider) {
    message = 'Sync stopped — your Church session expired, so this stake’s data isn’t updating. Re-authorize to resume.';
    actionLabel = 'Re-authorize';
  } else {
    message = 'This stake’s daily sync has failed. The leader who set it up needs to re-authorize — or you can take it over by signing in with your Church account.';
    actionLabel = 'Authorize on my account';
  }
  return (
    <div className="banner banner--stale" role="status">
      <span className="row" title={lastError ?? undefined}>
        <Icon name="warning" size={18} color="var(--warning)" />
        {message}
      </span>
      <button type="button" className="btn btn--text" onClick={onReenroll}>
        {actionLabel}
      </button>
    </div>
  );
}

/** Some member details (patriarchal blessing, and anything a member missed in the bulk directory) only
 *  fill from the per-member LCR profile read during a sync with a LIVE session — i.e. right after a
 *  re-authorization. Offer the credential provider (whose calling can read profiles) a one-tap re-auth
 *  that fills them ALL; `pending` counts real members still missing data. Hidden when pending is 0. */
export function PatriarchalBanner({ pending, onRefresh }: { pending: number; onRefresh: () => void }) {
  const who = pending === 1 ? 'member is' : 'members are';
  return (
    <div className="banner banner--info" role="status">
      <span className="row" style={{ gap: 8 }}>
        <Icon name="menu_book" size={18} color="var(--primary)" />
        {pending} {who} missing profile details the daily Church sync can’t pull (like patriarchal
        blessing). Re-authorize to refresh them.
      </span>
      <button type="button" className="btn btn--text" onClick={onRefresh}>
        Refresh
      </button>
    </div>
  );
}

// ---- Freshness chip (app bar) -----------------------------------------------------------------

export function LastUpdatedChip({
  iso,
  compact,
  syncing,
  onSyncNow,
}: {
  iso: string;
  compact: boolean;
  syncing: boolean;
  onSyncNow?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const s = staleness(iso);
  const color = s === 'stale' ? 'var(--danger)' : s === 'warn' ? 'var(--warning)' : undefined;
  return (
    <>
      <button
        type="button"
        className="chip"
        onClick={() => setOpen(true)}
        title={syncing ? 'Sync in progress…' : `Data last updated:\n${fmtDateTime(iso)}`}
        style={{ border: 'none', background: 'transparent', color }}
      >
        {syncing ? (
          <span className="spinner" aria-hidden="true" style={{ width: 15, height: 15 }} />
        ) : (
          <Icon name={color ? 'history_off' : 'history'} size={18} color={color} />
        )}
        {!compact && <span className="tiny">{syncing ? 'Syncing…' : `Updated ${ago(iso)}`}</span>}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Data freshness"
        actions={
          <>
            {onSyncNow && !syncing && (
              <button
                type="button"
                className="btn btn--filled"
                onClick={() => {
                  setOpen(false);
                  onSyncNow();
                }}
              >
                <Icon name="sync" size={18} />
                Sync now
              </button>
            )}
            <button type="button" className="btn btn--text" onClick={() => setOpen(false)}>
              Close
            </button>
          </>
        }
      >
        <p style={{ whiteSpace: 'pre-line' }}>Last scraped from LCR:{'\n\n'}{fmtDateTime(iso)}</p>
        {syncing ? (
          <div className="row" style={{ marginTop: 18 }}>
            <span className="spinner" aria-hidden="true" />
            <span className="small">Sync in progress — fresh data in a few minutes.</span>
          </div>
        ) : (
          onSyncNow && (
            <p className="small muted" style={{ marginTop: 16 }}>
              Run a fresh scrape now using your stake's saved sync credential.
            </p>
          )
        )}
      </Modal>
    </>
  );
}

// ---- Org filter bar ---------------------------------------------------------------------------

export function OrgFilterBar({
  selected,
  onToggle,
  onClear,
}: {
  selected: Set<OrgBucket>;
  onToggle: (b: OrgBucket) => void;
  onClear: () => void;
}) {
  const all = selected.size === ORG_BUCKETS.length;
  return (
    <div className="wrap" style={{ justifyContent: 'center' }}>
      {ORG_BUCKETS.map((b) => {
        const i = orgInfo(b);
        const sel = selected.has(b);
        return (
          <button
            key={b}
            type="button"
            className="chip"
            aria-pressed={sel}
            aria-label={`${i.short} — ${i.label}`}
            title={`${i.short} — ${i.label}`}
            onClick={() => onToggle(b)}
            style={{
              background: hexA(i.color, sel ? 0.22 : 0.06),
              borderColor: hexA(i.color, sel ? 0.9 : 0.35),
              color: sel ? i.color : hexA(i.color, 0.6),
              fontWeight: sel ? 700 : 500,
            }}
          >
            {/* #8c/#8.1c: compact WML/RS/EQ shorthand (full name in the tooltip), not the long label. */}
            <Icon name={i.icon as IconName} size={16} color={i.color} />
            {i.short}
          </button>
        );
      })}
      {!all && (
        <button type="button" className="chip" onClick={onClear} style={{ border: 'none', background: 'var(--surface-container-highest)' }}>
          <Icon name="filter_off" size={16} />
          Clear filters
        </button>
      )}
    </div>
  );
}

// ---- Member row + list layouts ----------------------------------------------------------------

interface MemberRowProps {
  m: Member;
  chips?: boolean;
  showUnit?: boolean;
  showResp?: boolean;
  showAttendance?: boolean;
  elapsedBaptism?: boolean;
  dateField?: string;
  /** Accent for the unit pill (from the same per-unit palette as the filter chips). */
  unitColor?: string;
}

/** Long-press detector for a clickable surface: fires `onLongPress` after ~500ms held, and marks the
 *  next click as consumed so it doesn't ALSO trigger the normal click action. Pointer-events based so
 *  it works for both touch (mobile) and mouse (desktop). */
function useLongPress(onLongPress: () => void, ms = 500) {
  const timer = useRef<number | null>(null);
  const fired = useRef(false);
  const clear = () => {
    if (timer.current != null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  };
  return {
    onPointerDown: () => {
      fired.current = false;
      clear();
      timer.current = window.setTimeout(() => {
        fired.current = true;
        onLongPress();
      }, ms);
    },
    onPointerUp: clear,
    /** Returns true (and resets) when the just-finished press was a long-press → suppress the click. */
    consumeClick: () => {
      const was = fired.current;
      fired.current = false;
      return was;
    },
  };
}

/** Small gender chip (M = blue, F = pink) shown on member rows. */
function GenderTag({ sex }: { sex: string }) {
  if (sex !== 'M' && sex !== 'F') return null;
  const color = sex === 'M' ? '#1565C0' : '#AD1457';
  return (
    <span
      aria-label={sex === 'M' ? 'Male' : 'Female'}
      title={sex === 'M' ? 'Male' : 'Female'}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        minWidth: 16, height: 16, padding: '0 4px', borderRadius: 8, fontSize: 10, fontWeight: 800,
        background: hexA(color, 0.14), color,
      }}
    >
      {sex}
    </span>
  );
}

/** One member row (avatar + name + a single metadata line + optional GH chips + unit pill). The
 *  metadata line reads `gender · age · baptised-ago · org` separated by a faint divider; the unit
 *  (when shown) is a colored pill BELOW it (one placement only — no right/bottom duplication). */
export function MemberRow({ m, chips = false, showUnit = false, showResp = false, showAttendance = false, elapsedBaptism = true, dateField = 'baptism_date', unitColor }: MemberRowProps) {
  const navigate = useNavigate();
  const name = String(m['name'] ?? '—');
  const sex = String(m['sex'] ?? '').toUpperCase().slice(0, 1); // 'M' / 'F' / ''
  const date = parseMemberDate(m[dateField]);
  const age = ageOf(m);
  const isBaptism = dateField === 'baptism_date';
  const unit = String(m['unit_name'] ?? '');
  const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
  // Long-press a row → open the member detail straight into NOTE EDIT (no separate Edit button); a
  // normal tap/click opens the detail. The press timer fires the edit path and suppresses the click.
  const press = useLongPress(() => id && navigate(`/person/${encodeURIComponent(id)}?editNote=1`));

  // The date segment for the metadata line: elapsed "X ago" for a baptism (#8.1a), else the date.
  const dateSeg: ReactNode = date
    ? isBaptism
      ? (elapsedBaptism
          ? (baptismElapsed(date) ? `${baptismElapsed(date)} ago` : fmtMonthDayYear(date))
          : `${fmtMonthDayYear(date)}${baptismElapsed(date) ? ` (${baptismElapsed(date)})` : ''}`)
      : fmtLong(date)
    : null;

  // Build the single metadata line: gender · age · baptised-ago · org-badge, joined by a faint sep.
  const segs: ReactNode[] = [];
  if (sex) segs.push(<GenderTag key="g" sex={sex} />);
  if (age) segs.push(<span key="a">{age}</span>);
  if (dateSeg) {
    segs.push(
      <span key="d" className="row" style={{ gap: 3, alignItems: 'center' }}>
        <Icon name={isBaptism ? 'water_drop' : 'event'} size={15} color={isBaptism ? '#29b6f6' : 'var(--on-surface-variant)'} />
        {dateSeg}
      </span>,
    );
  }
  if (showResp) segs.push(<OrgBadge key="o" member={m} />);

  return (
    <button
      type="button"
      className="member-row"
      onClick={() => { if (!press.consumeClick() && id) navigate(`/person/${encodeURIComponent(id)}`); }}
      onPointerDown={press.onPointerDown}
      onPointerUp={press.onPointerUp}
      onPointerLeave={press.onPointerUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <Avatar name={name} photoUrl={m['photo_url'] as string | undefined} size={44} />
      <span className="member-row__main">
        <span className="member-row__name">{name}</span>
        {segs.length > 0 && (
          <span className="member-row__meta">
            {segs.map((s, i) => (
              <span key={i} className="row" style={{ gap: 4, alignItems: 'center' }}>
                {i > 0 && <span className="member-row__sep" aria-hidden="true">|</span>}
                {s}
              </span>
            ))}
          </span>
        )}
        {/* #1e: a sacrament-attendance pill on its own line (only when asked + data exists). */}
        {showAttendance && (
          <span style={{ display: 'block', marginTop: 4 }}>
            <AttendancePill member={m} />
          </span>
        )}
        <NoteLine uuid={id} />
        {chips && (
          <span style={{ display: 'block', marginTop: 6 }}>
            <GoldenHourChips member={m} size={22} highlightNext />
          </span>
        )}
        {/* The unit as a colored pill below the metadata (one placement; uses the filter palette). */}
        {showUnit && unit && (
          <span
            className="unit-pill"
            style={{
              background: hexA(unitColor ?? '#607D8B', 0.14),
              borderColor: hexA(unitColor ?? '#607D8B', 0.4),
              color: unitColor ?? 'var(--on-surface-variant)',
            }}
          >
            <Icon name="groups" size={13} color={unitColor ?? 'var(--on-surface-variant)'} /> {unit}
          </span>
        )}
      </span>
      <Icon name="chevron_right" size={18} />
    </button>
  );
}

/** The member's note THREAD under a list row — the latest entries, each with a relative timestamp
 *  (newest first; "+N more" when there are extras). Tapping the row opens the detail thread editor.
 *  Hidden when the "show notes" preference is off (item 9). */
export function NoteLine({ uuid }: { uuid: string }) {
  const { threads, showNotes } = useDashboard();
  const entries = uuid ? threads[uuid] : undefined;
  if (!entries || entries.length === 0 || !showNotes) return null;
  const shown = entries.slice(0, 2);
  return (
    <span className="stack tiny" style={{ gap: 3, marginTop: 4, color: 'var(--on-surface-variant)', minWidth: 0 }}>
      {shown.map((e, i) => (
        <span key={i} className="row" style={{ gap: 4, alignItems: 'flex-start', minWidth: 0 }}>
          <Icon name="note" size={13} color="var(--primary)" />
          <span style={{ minWidth: 0 }}>
            <span style={{ whiteSpace: 'pre-wrap', fontStyle: 'italic' }}>{e.body}</span>
            <span className="muted" style={{ marginLeft: 6 }}>· {ago(e.created_at)}</span>
          </span>
        </span>
      ))}
      {entries.length > shown.length && (
        <span className="muted" style={{ marginLeft: 17 }}>+{entries.length - shown.length} more</span>
      )}
    </span>
  );
}

function groupByUnit(rows: Member[], dateField: string, ascending: boolean): Array<[string, Member[]]> {
  const by = new Map<string, Member[]>();
  for (const m of rows) {
    const u = String(m['unit_name'] ?? '—');
    if (!by.has(u)) by.set(u, []);
    by.get(u)!.push(m);
  }
  for (const list of by.values()) {
    list.sort((a, b) => {
      const da = parseMemberDate(a[dateField]);
      const db = parseMemberDate(b[dateField]);
      if (da == null) return 1;
      if (db == null) return -1;
      return ascending ? da.getTime() - db.getTime() : db.getTime() - da.getTime();
    });
  }
  return [...by.keys()].sort().map((k) => [k, by.get(k)!] as [string, Member[]]);
}

/** Stable DOM id for a unit's card so a "jump to unit" link can scroll to it (#25). */
export function unitDomId(unit: string): string {
  return `unit-${unit.replace(/[^a-zA-Z0-9]+/g, '-').toLowerCase()}`;
}

/** Smooth-scroll to a unit's card and flash it ("hey, you scrolled here") — #25. Respects
 *  prefers-reduced-motion (snaps instead of smooth-scrolls). No-op if the card isn't on screen. */
export function scrollToUnit(unit: string) {
  const el = document.getElementById(unitDomId(unit));
  if (!el) return;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  el.classList.remove('card--flash');
  void el.offsetWidth; // reflow so re-adding the class restarts the animation
  el.classList.add('card--flash');
  window.setTimeout(() => el.classList.remove('card--flash'), 1300);
}

/** Cards grouped by unit, laid out in 1/2/3 columns by tier. Mirrors `_UnitGrid`. */
export function UnitGrid({
  rows,
  tier,
  chips,
  dateField = 'baptism_date',
  ascending = false,
  elapsedBaptism = false,
  showResp = false,
}: {
  rows: Member[];
  tier: Tier;
  chips: boolean;
  dateField?: string;
  ascending?: boolean;
  elapsedBaptism?: boolean;
  showResp?: boolean;
}) {
  const groups = groupByUnit(rows, dateField, ascending);
  const cards = groups.map(([unit, list]) => (
    <SectionCard key={unit} id={unitDomId(unit)} title={unit} trailing={<CountBadge n={list.length} />}>
      <div className="stack">
        {list.map((m, i) => (
          <MemberRow key={i} m={m} chips={chips} dateField={dateField} elapsedBaptism={elapsedBaptism} showResp={showResp} />
        ))}
      </div>
    </SectionCard>
  ));
  return <Columns cols={colsFor(tier)}>{cards}</Columns>;
}

/** Flat list sorted by date; unit shown as right-side metadata. Mirrors `_DateList`. */
export function DateList({
  rows,
  chips,
  dateField = 'baptism_date',
  ascending = false,
  elapsedBaptism = false,
  showResp = false,
}: {
  rows: Member[];
  chips: boolean;
  dateField?: string;
  ascending?: boolean;
  elapsedBaptism?: boolean;
  showResp?: boolean;
}) {
  const sorted = [...rows].sort((a, b) => {
    const da = parseMemberDate(a[dateField]);
    const db = parseMemberDate(b[dateField]);
    if (da == null) return 1;
    if (db == null) return -1;
    return ascending ? da.getTime() - db.getTime() : db.getTime() - da.getTime();
  });
  const colors = assignUnitColors(rows);
  return (
    <Columns cols={1}>
      {[
        <SectionCard key="bydate" title="By date">
          <div className="stack">
            {sorted.map((m, i) => (
              <MemberRow key={i} m={m} chips={chips} showUnit dateField={dateField} elapsedBaptism={elapsedBaptism} showResp={showResp} unitColor={colors.get(String(m['unit_name'] ?? '—'))} />
            ))}
          </div>
        </SectionCard>,
      ]}
    </Columns>
  );
}

/** Note one-liner for org responsibility, shown when exactly one org is selected. */
export function orgNoteFor(selected: Set<OrgBucket>): string | null {
  if (selected.size === 1) return orgResponsibilityNote([...selected][0]);
  return null;
}
