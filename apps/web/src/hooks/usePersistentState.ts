// View state (filters / sorts / view selections) lives in the URL QUERY STRING — a drop-in useState
// whose value is stored under a query param. Changing a filter PUSHES a history entry, so the browser
// Back button steps through previous filter states. A fresh page load starts clean (DashboardShell
// strips any params at load), so a refresh resets to defaults rather than resurrecting old filters.
//
// Same signature as the old localStorage-backed hook, so every tab adopts query-param state with no
// per-call change. Optional `serialize`/`deserialize` handle non-JSON values (e.g. a Set ↔ array); the
// serialized value is JSON-encoded into the param.

import { useSearchParams } from 'react-router-dom';

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

function decode<T>(raw: string | null, initial: T, c: Codec<T>): T {
  if (raw == null) return initial;
  try {
    return c.deserialize(JSON.parse(raw));
  } catch {
    return initial;
  }
}

export function usePersistentState<T>(
  key: string,
  initial: T,
  codec?: Codec<T>,
): [T, (v: T | ((prev: T) => T)) => void] {
  const c = codec ?? (identityCodec as Codec<T>);
  const [params, setParams] = useSearchParams();
  const value = decode(params.get(key), initial, c);

  const setValue = (v: T | ((prev: T) => T)) => {
    // Push (not replace) so Back returns to the previous filter state. Read the CURRENT value from
    // `prev` inside the updater so functional updates compose correctly even across rapid changes.
    setParams((prev) => {
      const cur = decode(prev.get(key), initial, c);
      const resolved = typeof v === 'function' ? (v as (p: T) => T)(cur) : v;
      const next = new URLSearchParams(prev);
      next.set(key, JSON.stringify(c.serialize(resolved)));
      return next;
    });
  };

  return [value, setValue];
}
