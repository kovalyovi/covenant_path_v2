// Shared dashboard building blocks — the React equivalents of the Flutter `_Page`, `_SectionTitle`,
// `_BigHeader`, `_SyncingBanner`, the freshness chip, `_MemberRow`, `_UnitGrid`, `_DateList`,
// `_OrgFilterBar`, and the small notes/pills. The tab views compose these so the layouts match.

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Member } from '../lib/member';
import {
  ageOf, responsibleParty, orgInfo, orgResponsibilityNote, type OrgBucket, ORG_BUCKETS,
} from '../logic/milestones';
import {
  parseMemberDate, fmtLong, fmtMonthDayYear, baptismElapsed, ago, staleness, fmtDateTime,
} from '../logic/dates';
import { hexA } from '../theme/tokens';
import { Icon, type IconName } from './Icon';
import { Avatar, CountBadge, Segmented, SectionCard } from './ui';
import { GoldenHourChips } from './GoldenHourChips';
import { Modal } from './Modal';
import type { Tier } from '../hooks/useTier';
import { colsFor, useTier } from '../hooks/useTier';
import { useDashboard } from '../hooks/useDashboard';

// ---- Page scaffold ----------------------------------------------------------------------------

export function PageScaffold({ tier, header, children }: { tier: Tier; header: ReactNode; children: ReactNode }) {
  return (
    <div className={tier === 'mobile' ? 'page__inner page__inner--mobile' : 'page__inner'}>
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
            onClick={() => onToggle(b)}
            style={{
              background: hexA(i.color, sel ? 0.22 : 0.06),
              borderColor: hexA(i.color, sel ? 0.9 : 0.35),
              color: sel ? i.color : hexA(i.color, 0.6),
              fontWeight: sel ? 700 : 500,
            }}
          >
            <Icon name={i.icon as IconName} size={16} color={i.color} />
            {i.label}
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
  dateField?: string;
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

/** One member row (avatar + name + date/responsibility + optional GH chips). Mirrors `_MemberRow`. */
export function MemberRow({ m, chips = false, showUnit = false, showResp = false, dateField = 'baptism_date' }: MemberRowProps) {
  const navigate = useNavigate();
  const tier = useTier();
  const isMobile = tier === 'mobile';
  const name = String(m['name'] ?? '—');
  const date = parseMemberDate(m[dateField]);
  const age = ageOf(m);
  const isBaptism = dateField === 'baptism_date';
  const resp = chips || showResp ? responsibleParty(m) : null;
  const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
  // Long-press a row → open the member detail straight into NOTE EDIT (no separate Edit button); a
  // normal tap/click opens the detail. The press timer fires the edit path and suppresses the click.
  const press = useLongPress(() => id && navigate(`/person/${encodeURIComponent(id)}?editNote=1`));

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
        {/* #12: on a phone the name takes the whole first row and age drops below it (not a cramped
            second column); inline on wider screens. */}
        <span className="row" style={{ gap: 6 }}>
          <span className="member-row__name">{name}</span>
          {!isMobile && age && <span className="muted tiny">· {age}</span>}
        </span>
        {isMobile && age && <span className="muted tiny">{age}</span>}
        {date && (
          <span className="row small" style={{ gap: 4, marginTop: 2 }}>
            <Icon name={isBaptism ? 'water_drop' : 'event'} size={13} color={isBaptism ? '#29b6f6' : 'var(--on-surface-variant)'} />
            <span className="muted">
              {isBaptism
                ? `${fmtMonthDayYear(date)}${baptismElapsed(date) ? ` (${baptismElapsed(date)})` : ''}`
                : fmtLong(date)}
            </span>
          </span>
        )}
        {resp && (
          <span className="row small" style={{ gap: 4, marginTop: 4, color: resp.color }}>
            <Icon name={resp.icon as IconName} size={13} color={resp.color} />
            {resp.label}
          </span>
        )}
        <NoteLine uuid={id} />
        {chips && (
          <span style={{ display: 'block', marginTop: 6 }}>
            <GoldenHourChips member={m} size={22} highlightNext />
          </span>
        )}
      </span>
      {showUnit ? (
        <span className="muted tiny" style={{ width: 130, textAlign: 'right' }}>
          {String(m['unit_name'] ?? '')}
        </span>
      ) : (
        <Icon name="chevron_right" size={18} />
      )}
    </button>
  );
}

/** The single leader note under a list row, shown IN FULL — shared by every member list so notes
 *  travel with people in Golden Hour, Needs, by-date lists, and the baptisms timeline. Hidden when the
 *  "show notes" preference is off (item 9). */
export function NoteLine({ uuid }: { uuid: string }) {
  const { notes, showNotes } = useDashboard();
  const n = uuid ? notes[uuid] : undefined;
  if (!n || !showNotes) return null;
  return (
    <span className="row tiny" style={{ gap: 4, marginTop: 4, color: 'var(--on-surface-variant)', minWidth: 0, alignItems: 'flex-start' }}>
      <Icon name="note" size={13} color="var(--primary)" />
      {/* full note (multi-line preserved), never truncated */}
      <span style={{ whiteSpace: 'pre-wrap', fontStyle: 'italic', minWidth: 0 }}>{n.text}</span>
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

/** Cards grouped by unit, laid out in 1/2/3 columns by tier. Mirrors `_UnitGrid`. */
export function UnitGrid({
  rows,
  tier,
  chips,
  dateField = 'baptism_date',
  ascending = false,
}: {
  rows: Member[];
  tier: Tier;
  chips: boolean;
  dateField?: string;
  ascending?: boolean;
}) {
  const groups = groupByUnit(rows, dateField, ascending);
  const cards = groups.map(([unit, list]) => (
    <SectionCard key={unit} title={unit} trailing={<CountBadge n={list.length} />}>
      <div className="stack">
        {list.map((m, i) => (
          <MemberRow key={i} m={m} chips={chips} dateField={dateField} />
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
}: {
  rows: Member[];
  chips: boolean;
  dateField?: string;
  ascending?: boolean;
}) {
  const sorted = [...rows].sort((a, b) => {
    const da = parseMemberDate(a[dateField]);
    const db = parseMemberDate(b[dateField]);
    if (da == null) return 1;
    if (db == null) return -1;
    return ascending ? da.getTime() - db.getTime() : db.getTime() - da.getTime();
  });
  return (
    <Columns cols={1}>
      {[
        <SectionCard key="bydate" title="By date">
          <div className="stack">
            {sorted.map((m, i) => (
              <MemberRow key={i} m={m} chips={chips} showUnit dateField={dateField} />
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
