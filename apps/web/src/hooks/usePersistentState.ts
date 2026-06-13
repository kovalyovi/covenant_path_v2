// Persisted view state (item 9): a drop-in useState that remembers its value in localStorage under a
// namespaced key — but ONLY while the global "remember my filters & view preferences" switch is on
// (lib/prefs). When the switch is off, it behaves like a plain useState (resets each session) and
// nothing is written. Used for every table/view filter, sort, and view selection.
//
// Optional `serialize`/`deserialize` handle non-JSON values (e.g. a Set ↔ array).

import { useEffect, useRef, useState } from 'react';
import { getRemember, loadViewPref, saveViewPref } from '../lib/prefs';

interface Codec<T> {
  serialize: (v: T) => unknown;
  deserialize: (raw: unknown) => T;
}

const identityCodec: Codec<unknown> = {
  serialize: (v) => v,
  deserialize: (raw) => raw,
};

/** A Set<string> ↔ string[] codec (filters/org buckets are Sets). */
export const setCodec: Codec<Set<string>> = {
  serialize: (v) => [...v],
  deserialize: (raw) => new Set(Array.isArray(raw) ? (raw as string[]) : []),
};

export function usePersistentState<T>(
  key: string,
  initial: T,
  codec?: Codec<T>,
): [T, (v: T | ((prev: T) => T)) => void] {
  const c = (codec ?? (identityCodec as Codec<T>));
  const [state, setState] = useState<T>(() => {
    if (!getRemember()) return initial;
    const raw = loadViewPref<unknown>(key, undefined);
    if (raw === undefined) return initial;
    try {
      return c.deserialize(raw);
    } catch {
      return initial;
    }
  });

  // Persist on change (no-op when remember is off, enforced inside saveViewPref). Skip the very first
  // run so we don't immediately re-write the value we just read.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    saveViewPref(key, c.serialize(state));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, state]);

  return [state, setState];
}
