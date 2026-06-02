// Table tab — every covenant-path field, color-coded like the master sheet. React port of
// table_view.dart: 3-state sort on text columns (asc → desc → none), per-column Google-Sheets-style
// value filters (uncheck a value to hide its rows), color-coded Yes/No/N-A + recommend + gender +
// friends-count cells (#3). Investigators excluded (N7). The whole page scrolls; the table scrolls
// horizontally inside it.

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDashboard } from '../../hooks/useDashboard';
import type { Member } from '../../lib/member';
import { isInvestigator } from '../../lib/member';
import { Icon } from '../../components/Icon';
import { Modal } from '../../components/Modal';
import { Button } from '../../components/ui';
import { MemberListSkeleton } from '../../components/Skeletons';
import { EmptyState } from '../../components/EmptyState';

type Kind = 'text' | 'gender' | 'friends' | 'yesno' | 'recommend';

interface Col {
  header: string;
  key: string;
  kind: Kind;
}

// (header, member key, kind). 'text' columns also sort; every column filters by value.
const COLS: Col[] = [
  { header: 'Member', key: 'name', kind: 'text' },
  { header: 'Sex', key: 'sex', kind: 'gender' },
  { header: 'Unit', key: 'unit_name', kind: 'text' },
  { header: 'Baptism', key: 'baptism_date', kind: 'text' },
  { header: 'Member for', key: 'membership_duration', kind: 'text' },
  { header: 'Friends', key: 'friends', kind: 'friends' },
  { header: 'Aaronic', key: 'aaronic_priesthood', kind: 'yesno' },
  { header: 'Melch.', key: 'melchizedek_priesthood', kind: 'yesno' },
  { header: 'Calling', key: 'calling', kind: 'yesno' },
  { header: 'Has min.', key: 'ministering_brothers_sisters', kind: 'yesno' },
  { header: 'Gives min.', key: 'ministering_assignment', kind: 'yesno' },
  { header: 'Recommend', key: 'temple_recommend', kind: 'recommend' },
  { header: 'Patriarchal', key: 'patriarchal_blessing', kind: 'yesno' },
  { header: 'Endowed', key: 'living_ordinance', kind: 'yesno' },
];

/** Display value — friends shows the recorded count when present; strips redundant "Member for ". */
function display(m: Member, key: string): string {
  if (key === 'friends') {
    const c = m['friends_count'];
    if (c != null && String(c).length > 0) return String(c);
    return String(m['friends'] ?? '');
  }
  const v = String(m[key] ?? '');
  return key === 'membership_duration' ? v.replace(/^Member for\s*/i, '') : v;
}

const GREEN = '#c8e6c9';
const RED = '#ffcdd2';
const GREY = '#e0e0e0';
const AMBER = '#ffe082';

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
  if (d.loading) return <MemberListSkeleton />;
  if (d.error) {
    return (
      <div className="center-col" style={{ minHeight: '50vh' }}>
        <p style={{ textAlign: 'center', whiteSpace: 'pre-line' }}>Could not load data:{'\n'}{d.error}</p>
      </div>
    );
  }
  if (d.members.length === 0) return <EmptyState enrollStatus={d.enrollStatus} />;
  return <TableBody members={d.members} />;
}

function TableBody({ members }: { members: Member[] }) {
  const navigate = useNavigate();
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortAsc, setSortAsc] = useState(true);
  // per column: the set of values the user UNCHECKED (hidden). Empty/absent = show everything.
  const [excluded, setExcluded] = useState<Record<string, Set<string>>>({});
  const [filterCol, setFilterCol] = useState<Col | null>(null);

  const base = members.filter((m) => !isInvestigator(m));

  function passes(m: Member): boolean {
    for (const [key, set] of Object.entries(excluded)) {
      if (set.has(display(m, key))) return false;
    }
    return true;
  }

  let rows = base.filter(passes);
  if (sortCol != null) {
    const key = COLS[sortCol].key;
    rows = [...rows].sort((a, b) => {
      const c = display(a, key).toLowerCase().localeCompare(display(b, key).toLowerCase());
      return sortAsc ? c : -c;
    });
  }

  function onSort(col: number) {
    if (sortCol === col) {
      if (sortAsc) setSortAsc(false);
      else setSortCol(null);
    } else {
      setSortCol(col);
      setSortAsc(true);
    }
  }

  const activeFilters = Object.keys(excluded).length;
  const isMobile = typeof window !== 'undefined' && window.innerWidth < 600;

  return (
    <div className="page__inner" style={{ paddingTop: 8, paddingBottom: isMobile ? 92 : 12 }}>
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
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              {COLS.map((c, i) => (
                <th key={c.key} scope="col">
                  <Header
                    col={c}
                    sortable={c.kind === 'text'}
                    sortState={sortCol === i ? (sortAsc ? 'asc' : 'desc') : null}
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
                  <td className="muted">{r + 1}</td>
                  {COLS.map((c) => (
                    <Cell key={c.key} value={display(m, c.key)} kind={c.kind} />
                  ))}
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
          onClose={() => setFilterCol(null)}
          onApply={(set) => {
            setExcluded((cur) => {
              const next = { ...cur };
              if (set.size === 0) delete next[filterCol.key];
              else next[filterCol.key] = set;
              return next;
            });
            setFilterCol(null);
          }}
        />
      )}
    </div>
  );
}

function Header({
  col,
  sortable,
  sortState,
  filtered,
  onSort,
  onFilter,
}: {
  col: Col;
  sortable: boolean;
  sortState: 'asc' | 'desc' | null;
  filtered: boolean;
  onSort: () => void;
  onFilter: () => void;
}) {
  return (
    <span className="row" style={{ gap: 2 }}>
      <span>{col.header}</span>
      {sortable && (
        <button
          type="button"
          className="th-btn"
          onClick={(e) => {
            e.stopPropagation();
            onSort();
          }}
          aria-label={`Sort by ${col.header}`}
          title={`Sort by ${col.header}`}
          style={{ opacity: sortState ? 1 : 0.55 }}
        >
          <Icon name={sortState === 'asc' ? 'arrow_up' : sortState === 'desc' ? 'arrow_down' : 'unfold_more'} size={14} />
        </button>
      )}
      <button
        type="button"
        className="th-btn"
        onClick={(e) => {
          e.stopPropagation();
          onFilter();
        }}
        aria-label={`Filter ${col.header}`}
        title={`Filter ${col.header}`}
        style={{ color: filtered ? '#ffe082' : undefined, opacity: filtered ? 1 : 0.7 }}
      >
        <Icon name={filtered ? 'filter' : 'filter_outline'} size={15} />
      </button>
    </span>
  );
}

function Cell({ value, kind }: { value: string; kind: Kind }) {
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
  onClose,
  onApply,
}: {
  col: Col;
  rows: Member[];
  excluded: Set<string>;
  onClose: () => void;
  onApply: (set: Set<string>) => void;
}) {
  const counts = new Map<string, number>();
  for (const m of rows) {
    const v = display(m, col.key);
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  const values = [...counts.keys()].sort();
  const [local, setLocal] = useState<Set<string>>(new Set(excluded));

  return (
    <Modal
      open
      onClose={onClose}
      title={`Filter · ${col.header}`}
      hideClose
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="filled" onClick={() => onApply(new Set(local))}>
            Apply
          </Button>
        </>
      }
    >
      <div className="row" style={{ gap: 8 }}>
        <Button onClick={() => setLocal(new Set())}>Select all</Button>
        <Button onClick={() => setLocal(new Set(values))}>Clear all</Button>
      </div>
      <hr className="divider" style={{ margin: '8px 0' }} />
      <div style={{ maxHeight: '50vh', overflowY: 'auto' }}>
        {values.map((v) => (
          <label key={v} className="list-tile" style={{ padding: '6px 4px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!local.has(v)}
              onChange={(e) => {
                setLocal((cur) => {
                  const next = new Set(cur);
                  if (e.target.checked) next.delete(v);
                  else next.add(v);
                  return next;
                });
              }}
            />
            <span className="list-tile__main" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {v === '' ? '(blank)' : v}
            </span>
            <span className="tiny muted">{counts.get(v)}</span>
          </label>
        ))}
      </div>
    </Modal>
  );
}
