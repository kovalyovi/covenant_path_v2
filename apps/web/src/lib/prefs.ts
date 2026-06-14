// Local device preference: the notes show/hide toggle on member lists. (Filter/sort/view state now
// lives in the URL query string — see hooks/usePersistentState — so there is no longer a global
// "remember my filters" switch; this is the one genuine device preference that remains.)
//
// Pure + framework-free so it unit-tests and can be reused by any view/hook.

const SHOW_NOTES_KEY = 'cp.pref.showNotes';

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

/** Notes show/hide on member lists. Default SHOW (true); persisted on this device. */
export function getShowNotes(): boolean {
  const v = safeGet(SHOW_NOTES_KEY);
  return v == null ? true : v === '1';
}

export function setShowNotes(on: boolean): void {
  safeSet(SHOW_NOTES_KEY, on ? '1' : '0');
}
