// Animate a number from its previous value to `target` (ease-out cubic) for KPI stats. Honors
// prefers-reduced-motion (JS-driven, so the global CSS rule doesn't cover it) by snapping instantly.
// Returns the live displayed number; the caller formats + uses tabular-nums to avoid width jitter.

import { useEffect, useRef, useState } from 'react';

export function useCountUp(target: number, durationMs = 600): number {
  const [val, setVal] = useState(target);
  const fromRef = useRef(target);

  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const from = fromRef.current;
    fromRef.current = target;
    if (reduce || from === target || !Number.isFinite(target)) {
      setVal(target);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setVal(from + (target - from) * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return val;
}
