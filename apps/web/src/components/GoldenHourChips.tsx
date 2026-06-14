// Row of small chips for one member (the iOS Golden Hour pattern). Each chip carries the milestone's
// 3-way status from `goldenHourRows` — ✓ done / ○ not yet / ⚠ DATA ISSUE (the needs-profile-api
// sentinel or a missing value) — so the chips are the SINGLE covenant-path representation on the detail
// view (the separate "done-text" rows are gone, #10a). With `highlightNext` the first not-done milestone
// gets an amber "next step" ring. `labeled` renders full-text pills (detail) instead of compact circles
// (lists). Each labeled chip is interactive: hover OR click/tap shows a tooltip explaining the step.
// Mirrors GoldenHourChips in the native surfaces.

import { useEffect, useId, useRef, useState } from 'react';
import type { Member } from '../lib/member';
import { goldenHourRows, type Milestone } from '../logic/milestones';
import { hexA } from '../theme/tokens';
import { Icon, type IconName } from './Icon';

const GREEN = '#43a047';
const AMBER = '#ffa000';
const GREY = '#9e9e9e';
const ISSUE = '#f9a825'; // ⚠ data issue — matches the table/detail ⚠ marker (D22)

/** Chip visual state: 'next' is a not-done milestone flagged as the suggested next step. */
type ChipState = 'done' | 'next' | 'not-done' | 'issue';

interface Visual { color: string; icon: IconName; word: string; bg?: string; }

function visual(state: ChipState): Visual {
  switch (state) {
    case 'done': return { color: GREEN, icon: 'check_circle', word: 'Completed', bg: hexA(GREEN, 0.12) };
    case 'next': return { color: AMBER, icon: 'arrow_forward', word: 'Suggested next step', bg: hexA(AMBER, 0.12) };
    case 'issue': return { color: ISSUE, icon: 'warning', word: 'Data issue — value unavailable', bg: hexA(ISSUE, 0.14) };
    case 'not-done': return { color: GREY, icon: 'circle_outline', word: 'Not yet' };
  }
}

interface Props {
  member: Member;
  size?: number;
  highlightNext?: boolean;
  labeled?: boolean;
}

export function GoldenHourChips({ member, size = 24, highlightNext = false, labeled = false }: Props) {
  const rows = goldenHourRows(member); // applicable only (N/A omitted), classified done / not-done / issue
  const nextIdx = highlightNext ? rows.findIndex((r) => r.status !== 'done') : -1;
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className={labeled ? 'gh-chips labeled' : 'gh-chips'}>
      {rows.map((r, i) => {
        // issue ⚠ takes precedence over the "next" highlight; otherwise the first not-done is "next".
        const state: ChipState =
          r.status === 'done' ? 'done'
            : r.status === 'issue' ? 'issue'
              : i === nextIdx ? 'next' : 'not-done';
        return labeled ? (
          <LabeledChip
            key={r.milestone.abbr}
            ms={r.milestone}
            state={state}
            open={open === r.milestone.abbr}
            onToggle={() => setOpen((cur) => (cur === r.milestone.abbr ? null : r.milestone.abbr))}
            onClose={() => setOpen((cur) => (cur === r.milestone.abbr ? null : cur))}
          />
        ) : (
          <CircleChip key={r.milestone.abbr} ms={r.milestone} state={state} size={size} />
        );
      })}
    </div>
  );
}

function LabeledChip({
  ms, state, open, onToggle, onClose,
}: {
  ms: Milestone; state: ChipState;
  open: boolean; onToggle: () => void; onClose: () => void;
}) {
  const v = visual(state);
  const tipId = useId();
  const ref = useRef<HTMLSpanElement>(null);

  // Dismiss an open (click-pinned) tooltip on outside click or Escape.
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  return (
    <span ref={ref} className="gh-chip-wrap">
      <button
        type="button"
        className="gh-chip gh-chip--labeled gh-chip--tip"
        aria-expanded={open}
        aria-describedby={open ? tipId : undefined}
        title={`${ms.label} — ${v.word}. ${ms.description}`}
        onClick={onToggle}
        style={{
          color: v.color,
          borderColor: v.color,
          borderWidth: state === 'next' ? 1.6 : 1,
          background: v.bg,
        }}
      >
        <Icon name={v.icon} size={15} />
        {ms.label}
      </button>
      <span id={tipId} role="tooltip" className={`gh-tip${open ? ' gh-tip--open' : ''}`}>
        <b>{ms.label}</b> · {v.word}
        <span className="gh-tip__body">{ms.description}</span>
      </span>
    </span>
  );
}

function CircleChip({ ms, state, size }: { ms: Milestone; state: ChipState; size: number }) {
  const v = visual(state);
  const tip = `${ms.label}: ${v.word}. ${ms.description}`;
  return (
    <span
      className="gh-chip"
      title={tip}
      aria-label={tip}
      role="img"
      style={{
        width: size,
        height: size,
        borderColor: v.color,
        borderWidth: state === 'next' ? 2 : 1.2,
        background: state === 'done' ? GREEN : v.bg ?? 'transparent',
        color: state === 'done' ? '#fff' : v.color,
        fontSize: ms.abbr.length >= 2 ? 8.5 : 11,
      }}
    >
      {ms.abbr}
    </span>
  );
}
