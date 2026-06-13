// Row of small circle chips for one member (the iOS Golden Hour pattern). Filled = done. With
// `highlightNext`, the first not-yet-complete milestone gets an amber ring as the suggested next
// step. `labeled` renders full-text pills (person detail) instead of compact circles (lists).
// On the detail view each labeled chip is interactive: hover OR click/tap shows a tooltip explaining
// what that Golden Hour step means (sourced from the single milestone definition's `description`).
// Mirrors GoldenHourChips in apps/viewer/lib/golden_hour.dart.

import { useEffect, useId, useRef, useState } from 'react';
import type { Member } from '../lib/member';
import { milestonesFor, type Milestone } from '../logic/milestones';
import { hexA } from '../theme/tokens';
import { Icon } from './Icon';

const GREEN = '#43a047';
const AMBER = '#ffa000';
const GREY = '#9e9e9e';

interface Props {
  member: Member;
  size?: number;
  highlightNext?: boolean;
  labeled?: boolean;
}

export function GoldenHourChips({ member, size = 24, highlightNext = false, labeled = false }: Props) {
  const list = milestonesFor(member);
  const nextIdx = highlightNext ? list.findIndex((ms) => !ms.complete(member)) : -1;
  // One open tooltip at a time (clicking another chip moves it). Only used in `labeled` mode.
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className={labeled ? 'gh-chips labeled' : 'gh-chips'}>
      {list.map((ms, i) =>
        labeled ? (
          <LabeledChip
            key={ms.abbr}
            ms={ms}
            done={ms.complete(member)}
            isNext={i === nextIdx}
            open={open === ms.abbr}
            onToggle={() => setOpen((cur) => (cur === ms.abbr ? null : ms.abbr))}
            onClose={() => setOpen((cur) => (cur === ms.abbr ? null : cur))}
          />
        ) : (
          <CircleChip key={ms.abbr} ms={ms} done={ms.complete(member)} isNext={i === nextIdx} size={size} />
        ),
      )}
    </div>
  );
}

function LabeledChip({
  ms, done, isNext, open, onToggle, onClose,
}: {
  ms: Milestone; done: boolean; isNext: boolean;
  open: boolean; onToggle: () => void; onClose: () => void;
}) {
  const c = done ? GREEN : isNext ? AMBER : GREY;
  const tipId = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const status = done ? 'Completed' : isNext ? 'Suggested next step' : 'Not yet';

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
        title={`${ms.label} — ${status}. ${ms.description}`}
        onClick={onToggle}
        style={{
          color: c,
          borderColor: c,
          borderWidth: isNext ? 1.6 : 1,
          background: done ? hexA(GREEN, 0.12) : isNext ? hexA(AMBER, 0.12) : undefined,
        }}
      >
        <Icon name={done ? 'check_circle' : isNext ? 'arrow_forward' : 'circle_outline'} size={15} />
        {ms.label}
      </button>
      {/* Hover tooltip (CSS) + click/tap tooltip (open state) share one bubble. */}
      <span
        id={tipId}
        role="tooltip"
        className={`gh-tip${open ? ' gh-tip--open' : ''}`}
      >
        <b>{ms.label}</b> · {status}
        <span className="gh-tip__body">{ms.description}</span>
      </span>
    </span>
  );
}

function CircleChip({ ms, done, isNext, size }: { ms: Milestone; done: boolean; isNext: boolean; size: number }) {
  const border = done ? GREEN : isNext ? AMBER : GREY;
  const state = done ? 'done' : isNext ? 'next step' : 'not yet';
  const tip = `${ms.label}: ${state}. ${ms.description}`;
  return (
    <span
      className="gh-chip"
      title={tip}
      aria-label={tip}
      role="img"
      style={{
        width: size,
        height: size,
        borderColor: border,
        borderWidth: isNext ? 2 : 1.2,
        background: done ? GREEN : isNext ? hexA(AMBER, 0.15) : 'transparent',
        color: done ? '#fff' : isNext ? AMBER : 'var(--on-surface-variant)',
        fontSize: ms.abbr.length >= 2 ? 8.5 : 11,
      }}
    >
      {ms.abbr}
    </span>
  );
}
