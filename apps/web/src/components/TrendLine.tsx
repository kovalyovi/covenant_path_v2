// iOS-style trend line (Recharts) — smooth curve, gradient fill, open dots, always-on value labels,
// sparse x-axis labels, optional faded/dashed previous-window overlay, and bucket tap + hover. The
// visual + interaction model mirrors the Flutter `_Line` (fl_chart). Clicking a point reports its
// bucket index; hovering reports the active index (cleared when the pointer leaves).

import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  LabelList,
} from 'recharts';
import { useId } from 'react';

interface Props {
  values: number[];
  labels: string[];
  color: string;
  prev?: number[];
  onBucketTap?: (i: number) => void;
  onHover?: (i: number | null) => void;
}

interface Row {
  i: number;
  label: string;
  cur: number;
  prev?: number;
}

export function TrendLine({ values, labels, color, prev = [], onBucketTap, onHover }: Props) {
  const gid = useId().replace(/:/g, '');
  if (values.length === 0) {
    return (
      <div className="center-col" style={{ minHeight: 140 }}>
        <span className="muted">No data yet</span>
      </div>
    );
  }
  const data: Row[] = values.map((v, i) => ({
    i,
    label: labels[i] ?? '',
    cur: v,
    prev: prev.length > 0 ? (prev[i] ?? 0) : undefined,
  }));
  const peak = Math.max(...values, ...prev, 0);
  const maxY = peak * 1.35 + 1;
  const step = Math.min(999, Math.max(1, Math.ceil(values.length / 3)));

  return (
    <ResponsiveContainer width="100%" height={170}>
      <ComposedChart
        data={data}
        margin={{ top: 18, right: 8, bottom: 0, left: 8 }}
        onClick={(state) => {
          const idx = state?.activeTooltipIndex;
          if (onBucketTap && idx != null && idx >= 0) onBucketTap(idx);
        }}
        onMouseMove={(state) => {
          const idx = state?.activeTooltipIndex;
          if (onHover) onHover(idx != null && idx >= 0 ? idx : null);
        }}
        onMouseLeave={() => onHover?.(null)}
        style={{ cursor: onBucketTap ? 'pointer' : 'default' }}
      >
        <defs>
          <linearGradient id={`fill-${gid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          interval={0}
          height={22}
          tick={(props: { x: number; y: number; index: number; payload: { value: string } }) => {
            const { x, y, index, payload } = props;
            if (index % step !== 0 && index !== data.length - 1) return <g />;
            return (
              <text x={x} y={y + 12} textAnchor="middle" fontSize={10} fill="var(--on-surface-variant)">
                {payload.value}
              </text>
            );
          }}
        />
        <YAxis domain={[0, maxY]} hide />
        <Area type="monotone" dataKey="cur" stroke="none" fill={`url(#fill-${gid})`} isAnimationActive={false} />
        {prev.length > 0 && (
          <Line
            type="monotone"
            dataKey="prev"
            stroke="#9e9e9e"
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={false}
          />
        )}
        <Line
          type="monotone"
          dataKey="cur"
          stroke={color}
          strokeWidth={3}
          dot={{ r: 3.5, fill: '#fff', stroke: color, strokeWidth: 2 }}
          activeDot={{ r: 5 }}
          isAnimationActive={false}
        >
          <LabelList
            dataKey="cur"
            position="top"
            formatter={(v: number) => (v === Math.round(v) ? String(Math.round(v)) : v.toFixed(0))}
            style={{ fill: color, fontWeight: 700, fontSize: 11 }}
          />
        </Line>
      </ComposedChart>
    </ResponsiveContainer>
  );
}
