// Two completion-ring visuals (#8d), each PAIRED with a numeric label (the ring is decoration, the
// number is the truth) + an accessible aria-label so they're not signalled by shape/color alone:
//   • FilledRing    — a donut filled to `value` (0..1): "% of items complete"
//   • SectionedRing — N equal arcs (one per person); the first `filled` arcs are solid: how many people
//     are fully complete (a distinct treatment from the continuous FilledRing so the two never confuse)
import { status } from '../theme/tokens';

const SIZE = 46; // ≥ the ~36px min where a ring is still legible; below this show only the number
const STROKE = 6;
const R = (SIZE - STROKE) / 2;
const CX = SIZE / 2;
const CIRC = 2 * Math.PI * R;

function Labels({ label, sublabel }: { label?: string; sublabel?: string }) {
  if (!label && !sublabel) return null;
  return (
    <span className="stack" style={{ gap: 0 }}>
      {label && <span className="small" style={{ fontWeight: 600 }}>{label}</span>}
      {sublabel && <span className="tiny muted">{sublabel}</span>}
    </span>
  );
}

/** A donut filled to `value` (0..1) with the percentage in the centre — "% of items complete". */
export function FilledRing({ value, color = status.success, label, sublabel }: {
  value: number; color?: string; label?: string; sublabel?: string;
}) {
  const pct = Math.max(0, Math.min(1, value));
  return (
    <div className="row" style={{ gap: 8, alignItems: 'center' }}>
      <svg width={SIZE} height={SIZE} role="img" aria-label={`${Math.round(pct * 100)} percent ${sublabel ?? 'complete'}`}>
        <circle cx={CX} cy={CX} r={R} fill="none" stroke="var(--outline-variant)" strokeWidth={STROKE} />
        <circle
          cx={CX} cy={CX} r={R} fill="none" stroke={color} strokeWidth={STROKE} strokeLinecap="round"
          strokeDasharray={`${CIRC * pct} ${CIRC}`} transform={`rotate(-90 ${CX} ${CX})`}
        />
        <text x={CX} y={CX} textAnchor="middle" dominantBaseline="central" fontSize="12" fontWeight="700" fill="currentColor">
          {Math.round(pct * 100)}%
        </text>
      </svg>
      <Labels label={label} sublabel={sublabel} />
    </div>
  );
}

function arcPath(startDeg: number, sweepDeg: number): string {
  const a0 = ((startDeg - 90) * Math.PI) / 180;
  const a1 = ((startDeg + sweepDeg - 90) * Math.PI) / 180;
  const x0 = CX + R * Math.cos(a0);
  const y0 = CX + R * Math.sin(a0);
  const x1 = CX + R * Math.cos(a1);
  const y1 = CX + R * Math.sin(a1);
  const large = sweepDeg > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${R} ${R} 0 ${large} 1 ${x1} ${y1}`;
}

/** N equal arcs (one per person); the first `filled` are solid — "X of N people fully complete". */
export function SectionedRing({ total, filled, color = status.info, label, sublabel }: {
  total: number; filled: number; color?: string; label?: string; sublabel?: string;
}) {
  const n = Math.max(1, total);
  const gap = n > 1 ? Math.min(8, 120 / n) : 0; // degrees between arcs (shrinks as the count grows)
  const seg = 360 / n;
  const arcs = Array.from({ length: n }, (_, i) => ({
    i, start: i * seg + gap / 2, sweep: seg - gap, on: i < filled,
  }));
  return (
    <div className="row" style={{ gap: 8, alignItems: 'center' }}>
      <svg width={SIZE} height={SIZE} role="img" aria-label={`${filled} of ${total} people fully complete`}>
        {arcs.map((a) => (
          <path
            key={a.i} d={arcPath(a.start, a.sweep)} fill="none"
            stroke={a.on ? color : 'var(--outline-variant)'} strokeWidth={STROKE} strokeLinecap={n > 1 ? 'butt' : 'round'}
          />
        ))}
        <text x={CX} y={CX} textAnchor="middle" dominantBaseline="central" fontSize="11" fontWeight="700" fill="currentColor">
          {filled}/{total}
        </text>
      </svg>
      <Labels label={label} sublabel={sublabel} />
    </div>
  );
}
