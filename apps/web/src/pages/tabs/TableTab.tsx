// Table tab — every covenant-path field, color-coded like the master sheet. React port of
// table_view.dart: 3-state sort on text columns (asc → desc → none), per-column Google-Sheets-style
// value filters (uncheck a value to hide its rows), color-coded Yes/No/N-A + recommend + gender +
// friends-count cells (#3). Investigators excluded (N7). The whole page scrolls; the table scrolls
// horizontally inside it.

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePersistentState } from '../../hooks/usePersistentState';
import { useDashboard } from '../../hooks/useDashboard';
import type { Member } from '../../lib/member';
import { isInvestigator, displayFieldValue } from '../../lib/member';
import { endowmentDisplay, templeExperienceDisplay, ageYears } from '../../logic/milestones';
import { isDataIssue } from '../../logic/fieldDisplay';
import { parseMemberDate, tenure } from '../../logic/dates';
import { cell } from '../../theme/tokens';
import { Icon } from '../../components/Icon';
import { Modal } from '../../components/Modal';
import { Button } from '../../components/ui';
import { SkeletonBox } from '../../components/Skeletons';
import { EmptyState } from '../../components/EmptyState';

type Kind = 'text' | 'gender' | 'friends' | 'yesno' | 'recommend';

interface Col {
  header: string;
  key: string;
  kind: Kind;
}

// (header, member key, kind). 'text' columns also sort; every column filters by value.
// Exported so a unit test can pin the "every enumerable tracked field is filterable" contract.
export const COLS: Col[] = [
  { header: 'Member', key: 'name', kind: 'text' },
  { header: 'Sex', key: 'sex', kind: 'gender' },
  { header: 'Age', key: 'age', kind: 'text' },
  { header: 'Unit', key: 'unit_name', kind: 'text' },
  { header: 'Baptism', key: 'baptism_date', kind: 'text' },
  { header: 'Member for', key: 'membership_duration', kind: 'text' },
  { header: 'Friends', key: 'friends', kind: 'friends' },
  { header: 'Aaronic', key: 'aaronic_priesthood', kind: 'yesno' },
  { header: 'Melchizedek', key: 'melchizedek_priesthood', kind: 'yesno' },
  { header: 'Calling', key: 'calling', kind: 'yesno' },
  { header: 'Ministers assigned', key: 'ministering_brothers_sisters', kind: 'yesno' },
  { header: 'Ministering others', key: 'ministering_assignment', kind: 'yesno' },
  { header: 'Temple recommend', key: 'temple_recommend', kind: 'recommend' },
  { header: 'Patriarchal blessing', key: 'patriarchal_blessing', kind: 'yesno' },
  { header: 'Endowed', key: 'living_ordinance', kind: 'yesno' },
  { header: 'First temple visit', key: 'first_temple_visit', kind: 'yesno' },
  { header: 'Family name', key: 'family_name_prepared', kind: 'yesno' },
];

/** When the table is scrolled right, the frozen name shrinks to "Lastinitial, First" (e.g.
 *  "Kovaliov, Ilya" → "K, Ilya") so the frozen column reclaims width. Names are stored "Last, First". */
function abbreviateName(n: string): string {
  const i = n.indexOf(',');
  if (i <= 0) return n;
  const last = n.slice(0, i).trim();
  const first = n.slice(i + 1).trim();
  return first ? `${last.charAt(0)}, ${first}` : n;
}

// The sentinel-able covenant-path columns: a backend sentinel here ('needs-profile-api' / 'blocked:…')
// must show as friendly text to leaders and only raw to admins (handled via displayFieldValue).
const SENTINEL_COLS = new Set([
  'baptism_date', 'aaronic_priesthood', 'melchizedek_priesthood', 'calling',
  'ministering_brothers_sisters', 'ministering_assignment', 'temple_recommend',
  'patriarchal_blessing',
]);

/** Display value — friends shows the recorded count when present; strips redundant "Member for ".
 *  Sentinel-able columns map to friendly text for non-admins (raw for admins) so the techy
 *  'needs-profile-api' / 'blocked: …' placeholders never leak to a regular leader's table. */
function display(m: Member, key: string, isAdmin: boolean): string {
  // Endowment: N/A for ineligible members (not 18+ AND ~1yr) — gates the raw DB "No" client-side.
  if (key === 'living_ordinance') return displayFieldValue(endowmentDisplay(m), isAdmin, '—');
  // Temple experiences: N/A under 12; falls back to details.templeExperiences pre-resync.
  if (key === 'first_temple_visit' || key === 'family_name_prepared') {
    return displayFieldValue(templeExperienceDisplay(m, key), isAdmin, '—');
  }
  if (key === 'age') {
    const a = ageYears(m);
    return a == null ? '' : String(a);
  }
  if (key === 'friends') {
    const c = m['friends_count'];
    if (c != null && String(c).length > 0) return String(c);
    return String(m['friends'] ?? '');
  }
  // #9e: "Member for" computed fresh from the baptism date — "2 years 3 months" with zero parts
  // dropped (never "0 years"/"0 months"), days only under 2 months. No more stale "Member for …" str.
  if (key === 'membership_duration') return tenure(parseMemberDate(m['baptism_date']));
  if (SENTINEL_COLS.has(key)) return displayFieldValue(m[key], isAdmin, '—');
  return String(m[key] ?? '');
}

// #9d/#9f: every column SORTS; only enumerable categorical columns FILTER (unit, sex, and the
// yes/no/recommend status columns). Genuinely continuous/free-form columns — name, age, baptism,
// member-for, friends-count — stay sort-only, since a per-value filter there is just noise. Sex is
// a small enum (M/F) like the status columns, so "show only sisters" is a useful filter — it gets one.
export const FILTERABLE = new Set([
  'unit_name', 'sex', 'aaronic_priesthood', 'melchizedek_priesthood', 'calling',
  'ministering_brothers_sisters', 'ministering_assignment', 'temple_recommend',
  'patriarchal_blessing', 'living_ordinance', 'first_temple_visit', 'family_name_prepared',
]);

// The covenant-path columns subject to the CLIENT DISPLAY CONTRACT's ⚠ data-issue marker (item 5):
// the sentinel-able covenant fields plus the eligibility-gated endowment/temple-experience ones. A
// data issue = the needs-profile-api sentinel OR null/empty (but NOT N/A — N/A is "not eligible").
const ISSUE_COLS = new Set([
  ...SENTINEL_COLS, 'living_ordinance', 'first_temple_visit', 'family_name_prepared',
]);

/** Whether this cell is a DATA ISSUE (⚠) under the display contract — only for the covenant-path
 *  fields where "missing" is meaningful. Uses the eligibility-gated value so an N/A (not eligible)
 *  is correctly NOT flagged as an issue. */
function issueOf(m: Member, key: string): boolean {
  if (!ISSUE_COLS.has(key)) return false;
  if (key === 'living_ordinance') return isDataIssue(endowmentDisplay(m));
  if (key === 'first_temple_visit' || key === 'family_name_prepared') {
    return isDataIssue(templeExperienceDisplay(m, key));
  }
  return isDataIssue(m[key]);
}

// #6a: table cell fills come from the one shared token set (theme/tokens.cell).
const GREEN = cell.yes;
const RED = cell.no;
const GREY = cell.na;
const AMBER = cell.amber;

function cellColor(v: string, kind: Kind): string | null {
  if (kind === 'friends') {
    const n = Number(v);
    if (Number.isFinite(n) && v.trim() !== '') return n > 0 ? GREEN : RED;
    if (v === 'Yes') return GREEN;
    if (v === 'No') return RED;
    return null;
  }
  if (kind === 'yesno') {
    if (v === 'Yes') return GREEN;
    if (v === 'No') return RED;
    if (v === 'N/A') return GREY;
  } else if (kind === 'recommend') {
    if (v === 'Active') return GREEN;
    if (v === 'Expired') return AMBER;
    if (v === 'No') return RED;
  }
  return null;
}

export function TableTab() {
  const d = useDashboard();
  // Table renders its header/count even when empty, but if there are truly no members and we're not
  // loading, show the same empty state as other tabs (matches `tab != 3` guard + RLS reality).
  if (d.loading) return <TableSkeleton />;
  if (d.error) {
    return (
      <div className="center-col" style={{ minHeight: '50vh' }}>
        <p style={{ textAlign: 'center', whiteSpace: 'pre-line' }}>Could not load data:{'\n'}{d.error}</p>
      </div>
    );
  }
  if (d.members.length === 0) return <EmptyState enrollStatus={d.enrollStatus} />;
  return <TableBody members={d.members} isAdmin={d.isAdmin} />;
}

/** Loading glimmer for the Table tab. Renders the EXACT same shell as TableBody — the wrapper, the
 *  count row, and the `data-table` with the REAL column headers (the `<Header>` components, which need
 *  no data) so every column has its final width. Only the body cells are shimmer, each shaped like its
 *  column's real cell (name line / text value / rounded status pill). Because the header and column
 *  geometry are identical, the swap to real rows is seamless — nothing reflows. */
function TableSkeleton({ rows = 14 }: { rows?: number }) {
  return (
    <div className="page__inner page__inner--wide" style={{ paddingTop: 8, paddingBottom: 12 }} aria-hidden="true">
      <div className="row" style={{ padding: '8px 0 4px' }}>
        <SkeletonBox width={96} height={14} />
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col" className="col-num">#</th>
              {COLS.map((c) => (
                <th key={c.key} scope="col" className={c.key === 'name' ? 'col-member' : undefined}>
                  <Header
                    col={c}
                    sortState={null}
                    filterable={FILTERABLE.has(c.key)}
                    filtered={false}
                    onSort={() => {}}
                    onFilter={() => {}}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }, (_, r) => (
              <tr key={r}>
                <td className="muted col-num">{r + 1}</td>
                {COLS.map((c) => {
                  if (c.key === 'name') {
                    return (
                      <td key={c.key} className="col-member">
                        <SkeletonBox width={130} height={13} />
                      </td>
                    );
                  }
                  // yes/no/recommend/gender render a rounded pill in the real table → pill-shaped shimmer.
                  if (c.kind === 'yesno' || c.kind === 'recommend' || c.kind === 'gender') {
                    return (
                      <td key={c.key}>
                        <SkeletonBox width={34} height={20} radius={10} />
                      </td>
                    );
                  }
                  // text / friends → a short value line.
                  return (
                    <td key={c.key}>
                      <SkeletonBox width={Math.min(64, c.header.length * 6)} height={12} />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TableBody({ members, isAdmin }: { members: Member[]; isAdmin: boolean }) {
  const navigate = useNavigate();
  const { notes, showNotes } = useDashboard();
  // Persisted view state in the URL. Sort column + direction MUST be one value: two separate
  // usePersistentState setters in the same click would each write the URL from the same `prev`, so the
  // second clobbers the first (this is exactly why sorting silently did nothing). `filterCol` is the
  // transiently-open panel (not persisted).
  const [sort, setSort] = usePersistentState<{ col: number; asc: boolean } | null>('table.sort', null);
  const sortCol = sort?.col ?? null;
  const sortAsc = sort?.asc ?? true;
  // per column: the set of values the user UNCHECKED (hidden). Empty/absent = show everything.
  const [excluded, setExcluded] = usePersistentState<Record<string, Set<string>>>(
    'table.excluded', {}, {
      serialize: (v) => Object.fromEntries(Object.entries(v).map(([k, s]) => [k, [...s]])),
      deserialize: (raw) => {
        const o = (raw && typeof raw === 'object' ? raw : {}) as Record<string, string[]>;
        return Object.fromEntries(Object.entries(o).map(([k, a]) => [k, new Set(a)]));
      },
    },
  );
  const [filterCol, setFilterCol] = useState<Col | null>(null);
  const [scrolled, setScrolled] = useState(false); // #9a: horizontal-scroll → pin border

  const base = members.filter((m) => !isInvestigator(m));

  function passes(m: Member): boolean {
    for (const [key, set] of Object.entries(excluded)) {
      if (set.has(display(m, key, isAdmin))) return false;
    }
    return true;
  }

  // #9d/#9f: sort EVERY column with a sensible key — age & friends numerically, baptism & member-for by
  // the baptism instant (member-for == tenure ordering), the rest by their displayed text.
  function cmpByCol(a: Member, b: Member, col: Col): number {
    switch (col.key) {
      case 'age':
        return (ageYears(a) ?? -1) - (ageYears(b) ?? -1);
      case 'baptism_date':
      case 'membership_duration': {
        const da = parseMemberDate(a['baptism_date'])?.getTime() ?? -Infinity;
        const db = parseMemberDate(b['baptism_date'])?.getTime() ?? -Infinity;
        return da - db;
      }
      case 'friends': {
        const num = (m: Member) => {
          const c = m['friends_count'];
          if (c != null && String(c).length > 0) return Number(c);
          return m['friends'] === 'Yes' ? 1 : m['friends'] === 'No' ? 0 : -1;
        };
        return num(a) - num(b);
      }
      default:
        return display(a, col.key, isAdmin).toLowerCase()
          .localeCompare(display(b, col.key, isAdmin).toLowerCase());
    }
  }

  let rows = base.filter(passes);
  if (sortCol != null) {
    const col = COLS[sortCol];
    rows = [...rows].sort((a, b) => (sortAsc ? 1 : -1) * cmpByCol(a, b, col));
  }

  // #9g: filters apply IMMEDIATELY (no Apply button) — write the column's excluded set straight through.
  function applyFilter(key: string, set: Set<string>) {
    setExcluded((cur) => {
      const next = { ...cur };
      if (set.size === 0) delete next[key];
      else next[key] = set;
      return next;
    });
  }

  // One setter (asc → desc → off), so the single URL write can't race itself.
  function onSort(col: number) {
    setSort((cur) => {
      if (cur && cur.col === col) return cur.asc ? { col, asc: false } : null;
      return { col, asc: true };
    });
  }

  const activeFilters = Object.keys(excluded).length;

  return (
    <div className="page__inner page__inner--wide" style={{ paddingTop: 8, paddingBottom: 12 }}>
      <div className="row" style={{ padding: '8px 0 4px' }}>
        <span className="small">
          {rows.length} member{rows.length === 1 ? '' : 's'}
          {activeFilters > 0 ? ' (filtered)' : ''}
        </span>
        <span style={{ flex: 1 }} />
        {activeFilters > 0 && (
          <Button icon="filter_off" onClick={() => setExcluded({})}>
            Clear {activeFilters} filter{activeFilters === 1 ? '' : 's'}
          </Button>
        )}
      </div>
      <div
        className={`table-wrap${scrolled ? ' is-scrolled' : ''}`}
        onScroll={(e) => setScrolled((e.target as HTMLDivElement).scrollLeft > 0)}
      >
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col" className="col-num">#</th>
              {COLS.map((c, i) => (
                <th key={c.key} scope="col" className={c.key === 'name' ? 'col-member' : undefined}>
                  <Header
                    col={c}
                    sortState={sortCol === i ? (sortAsc ? 'asc' : 'desc') : null}
                    filterable={FILTERABLE.has(c.key)}
                    filtered={(excluded[c.key]?.size ?? 0) > 0}
                    onSort={() => onSort(i)}
                    onFilter={() => setFilterCol(c)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((m, r) => {
              const id = m['person_uuid'] != null ? String(m['person_uuid']) : '';
              return (
                <tr key={r} onClick={() => id && navigate(`/person/${encodeURIComponent(id)}`)}>
                  <td className="muted col-num">{r + 1}</td>
                  {COLS.map((c) =>
                    c.key === 'name' ? (
                      /* Member cell carries a note marker (hover = newest note) when leaders have
                         left notes on this person. */
                      <td key={c.key} className="col-member">
                        <span className="row" style={{ gap: 4, whiteSpace: 'nowrap' }}>
                          {/* On horizontal scroll, abbreviate to reclaim the frozen column's width. */}
                          {scrolled ? abbreviateName(display(m, c.key, isAdmin)) : display(m, c.key, isAdmin)}
                          {showNotes && notes[id] && (
                            <Icon
                              name="note"
                              size={13}
                              color="var(--primary)"
                              title={notes[id].text}
                            />
                          )}
                        </span>
                      </td>
                    ) : (
                      <Cell key={c.key} value={display(m, c.key, isAdmin)} kind={c.kind} issue={issueOf(m, c.key)} />
                    ),
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {filterCol && (
        <FilterDialog
          col={filterCol}
          rows={base}
          excluded={excluded[filterCol.key] ?? new Set()}
          isAdmin={isAdmin}
          onClose={() => setFilterCol(null)}
          onChange={(set) => applyFilter(filterCol.key, set)}
        />
      )}
    </div>
  );
}

function Header({
  col,
  sortState,
  filterable,
  filtered,
  onSort,
  onFilter,
}: {
  col: Col;
  sortState: 'asc' | 'desc' | null;
  filterable: boolean;
  filtered: boolean;
  onSort: () => void;
  onFilter: () => void;
}) {
  return (
    <span className="row" style={{ gap: 2 }}>
      {/* #9c: the column TITLE itself sorts (every column is sortable now), alongside the arrow. */}
      <button
        type="button"
        className="th-label"
        onClick={(e) => { e.stopPropagation(); onSort(); }}
        aria-label={`Sort by ${col.header}`}
      >
        {col.header}
      </button>
      <button
        type="button"
        className="th-btn"
        onClick={(e) => { e.stopPropagation(); onSort(); }}
        aria-label={`Sort by ${col.header}`}
        title={`Sort by ${col.header}`}
        style={{ opacity: sortState ? 1 : 0.55 }}
      >
        <Icon name={sortState === 'asc' ? 'arrow_up' : sortState === 'desc' ? 'arrow_down' : 'unfold_more'} size={14} />
      </button>
      {filterable && (
        <button
          type="button"
          className="th-btn"
          onClick={(e) => { e.stopPropagation(); onFilter(); }}
          aria-label={`Filter ${col.header}`}
          title={`Filter ${col.header}`}
          style={{ color: filtered ? '#ffe082' : undefined, opacity: filtered ? 1 : 0.7 }}
        >
          <Icon name={filtered ? 'filter' : 'filter_outline'} size={15} />
        </button>
      )}
    </span>
  );
}

function Cell({ value, kind, issue = false }: { value: string; kind: Kind; issue?: boolean }) {
  if (kind === 'gender') {
    if (value !== 'M' && value !== 'F') return <td />;
    const bg = value === 'M' ? '#bbdefb' : '#f8bbd0';
    return (
      <td>
        <span className="cell-pill" style={{ background: bg, fontWeight: 600 }}>
          {value}
        </span>
      </td>
    );
  }
  // A DATA ISSUE (sentinel / missing — never N/A) gets a ⚠ marker before the friendly text, so a
  // leader can see at a glance that the value should be known but isn't (item 5). The raw sentinel
  // string is never shown (display() already mapped it to friendly text).
  if (issue) {
    return (
      <td>
        <span className="row" style={{ gap: 4, whiteSpace: 'nowrap', color: '#b26a00' }}>
          <Icon name="warning" size={13} color="#f9a825" title="Data issue — value unavailable" />
          <span className="tiny">{value || 'Not available'}</span>
        </span>
      </td>
    );
  }
  const color = cellColor(value, kind);
  if (color == null) return <td>{value}</td>;
  return (
    <td>
      <span className="cell-pill" style={{ background: color }}>
        {value}
      </span>
    </td>
  );
}

function FilterDialog({
  col,
  rows,
  excluded,
  isAdmin,
  onClose,
  onChange,
}: {
  col: Col;
  rows: Member[];
  excluded: Set<string>;
  isAdmin: boolean;
  onClose: () => void;
  onChange: (set: Set<string>) => void;
}) {
  const counts = new Map<string, number>();
  for (const m of rows) {
    const v = display(m, col.key, isAdmin);
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  const values = [...counts.keys()].sort();
  const [local, setLocal] = useState<Set<string>>(new Set(excluded));

  // #9g: every change applies immediately (no Apply button) — update local state AND lift it up.
  function set(next: Set<string>) {
    setLocal(next);
    onChange(new Set(next));
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={`Filter · ${col.header}`}
      hideClose
      actions={<Button variant="filled" onClick={onClose}>Done</Button>}
    >
      <div className="row" style={{ gap: 8 }}>
        <Button onClick={() => set(new Set())}>Select all</Button>
        <Button onClick={() => set(new Set(values))}>Clear all</Button>
      </div>
      <hr className="divider" style={{ margin: '8px 0' }} />
      <div style={{ maxHeight: '50vh', overflowY: 'auto' }}>
        {values.map((v) => (
          <label key={v} className="list-tile" style={{ padding: '6px 4px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!local.has(v)}
              onChange={(e) => {
                const next = new Set(local);
                if (e.target.checked) next.delete(v);
                else next.add(v);
                set(next);
              }}
            />
            <span className="list-tile__main" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {v === '' ? '(blank)' : v}
            </span>
            <span className="tiny muted">{counts.get(v)}</span>
          </label>
        ))}
      </div>
      <span aria-live="polite" className="tiny muted" style={{ display: 'block', marginTop: 6 }}>
        {local.size === 0 ? 'Showing all values' : `${local.size} value${local.size === 1 ? '' : 's'} hidden`}
      </span>
    </Modal>
  );
}
