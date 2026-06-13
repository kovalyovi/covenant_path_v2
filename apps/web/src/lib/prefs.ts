// Local-only user preferences (item 9): table/view filters, sorts, view selections, the notes
// show/hide toggle, and the GLOBAL "remember my filters & view preferences" switch that governs all
// of them. Persistence is localStorage ONLY (no server) and is GATED by the global switch — when it's
// off, nothing is persisted and per-view state resets each session.
//
// Pure + framework-free so it unit-tests and can be reused by any view/hook.

const PREFIX = 'cp.pref.';
const REMEMBER_KEY = `${PREFIX}remember`;
const SHOW_NOTES_KEY = `${PREFIX}showNotes`;

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable / quota — preferences are best-effort */
  }
}

function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/** The global "remember my filters & view preferences" switch. Default ON (true) — the user opted
 *  into a tool that remembers their working state; they can turn it off in Settings. */
export function getRemember(): boolean {
  const v = safeGet(REMEMBER_KEY);
  return v == null ? true : v === '1';
}

export function setRemember(on: boolean): void {
  safeSet(REMEMBER_KEY, on ? '1' : '0');
  if (!on) clearViewPrefs(); // turning it off forgets everything persisted so far (privacy + reset)
}

/** Notes show/hide on the main screen. Default SHOW (true). Persisted only when `remember` is on;
 *  otherwise it lives for the session in memory (the caller keeps the React state). */
export function getShowNotes(): boolean {
  if (!getRemember()) return true; // not remembered → default each session
  const v = safeGet(SHOW_NOTES_KEY);
  return v == null ? true : v === '1';
}

export function setShowNotes(on: boolean): void {
  if (!getRemember()) return; // not persisted while remember is off
  safeSet(SHOW_NOTES_KEY, on ? '1' : '0');
}

/** Persist a JSON-serializable view-pref value under a namespaced key — a no-op when remember is off. */
export function saveViewPref(key: string, value: unknown): void {
  if (!getRemember()) return;
  try {
    safeSet(`${PREFIX}view.${key}`, JSON.stringify(value));
  } catch {
    /* non-serializable — skip */
  }
}

/** Read a persisted view-pref value (parsed), or `fallback` when absent / remember is off / invalid. */
export function loadViewPref<T>(key: string, fallback: T): T {
  if (!getRemember()) return fallback;
  const raw = safeGet(`${PREFIX}view.${key}`);
  if (raw == null) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** Forget all persisted view prefs + the notes toggle (keeps the remember switch itself). */
export function clearViewPrefs(): void {
  try {
    const toRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(PREFIX) && k !== REMEMBER_KEY) toRemove.push(k);
    }
    toRemove.forEach(safeRemove);
  } catch {
    /* ignore */
  }
}
