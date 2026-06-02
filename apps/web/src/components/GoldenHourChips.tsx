// Row of small circle chips for one member (the iOS Golden Hour pattern). Filled = done. With
// `highlightNext`, the first not-yet-complete milestone gets an amber ring as the suggested next
// step. `labeled` renders full-text pills (person detail) instead of compact circles (lists).
// Mirrors GoldenHourChips in apps/viewer/lib/golden_hour.dart.

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
  return (
    <div className={labeled ? 'gh-chips labeled' : 'gh-chips'}>
      {list.map((ms, i) =>
        labeled ? (
          <LabeledChip key={ms.abbr} ms={ms} done={ms.complete(member)} isNext={i === nextIdx} />
        ) : (
          <CircleChip key={ms.abbr} ms={ms} done={ms.complete(member)} isNext={i === nextIdx} size={size} />
        ),
      )}
    </div>
  );
}

function LabeledChip({ ms, done, isNext }: { ms: Milestone; done: boolean; isNext: boolean }) {
  const c = done ? GREEN : isNext ? AMBER : GREY;
  return (
    <span
      className="gh-chip gh-chip--labeled"
      style={{
        color: c,
        borderColor: c,
        borderWidth: isNext ? 1.6 : 1,
        background: done ? hexA(GREEN, 0.12) : isNext ? hexA(AMBER, 0.12) : undefined,
      }}
    >
      <Icon name={done ? 'check_circle' : isNext ? 'arrow_forward' : 'circle_outline'} size={15} />
      {ms.label}
    </span>
  );
}

function CircleChip({ ms, done, isNext, size }: { ms: Milestone; done: boolean; isNext: boolean; size: number }) {
  const border = done ? GREEN : isNext ? AMBER : GREY;
  const tip = `${ms.label}: ${done ? 'done' : isNext ? 'next step' : 'not yet'}`;
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
