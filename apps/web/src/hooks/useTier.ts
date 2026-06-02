// Responsive tier — three breakpoints (phone / tablet / desktop) drive the layout, mirroring
// `tierFor` in apps/viewer/lib/golden_hour.dart (mobile <600, tablet <1100, desktop otherwise).

import { useEffect, useState } from 'react';

export type Tier = 'mobile' | 'tablet' | 'desktop';

export function tierFor(width: number): Tier {
  return width < 600 ? 'mobile' : width < 1100 ? 'tablet' : 'desktop';
}

/** Columns per tier (mobile 1, tablet 2, desktop 3) — mirrors `_cols`. */
export function colsFor(tier: Tier): number {
  return tier === 'mobile' ? 1 : tier === 'tablet' ? 2 : 3;
}

export function useTier(): Tier {
  const [tier, setTier] = useState<Tier>(() => tierFor(typeof window === 'undefined' ? 1280 : window.innerWidth));
  useEffect(() => {
    function onResize() {
      setTier(tierFor(window.innerWidth));
    }
    window.addEventListener('resize', onResize);
    onResize();
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return tier;
}
