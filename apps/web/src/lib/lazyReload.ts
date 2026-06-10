// Recovers from "Failed to fetch dynamically imported module": a tab opened before a deploy still
// runs the old index.html, whose lazy routes point at previous-build hashed chunks that Cloudflare
// Pages no longer serves. The only cure is loading the new index.html, so on a failed chunk import
// we reload the page once — a sessionStorage guard stops a reload loop when the network itself is
// down (the second failure falls through to the route errorElement instead).

const RELOAD_FLAG = 'cp-stale-chunk-reload';

function flagSet(): boolean {
  try {
    return sessionStorage.getItem(RELOAD_FLAG) != null;
  } catch {
    return true; // storage unavailable → never auto-reload (can't guard against a loop)
  }
}

function setFlag(): void {
  try {
    sessionStorage.setItem(RELOAD_FLAG, String(Date.now()));
  } catch {
    /* ignore */
  }
}

export function clearStaleChunkFlag(): void {
  try {
    sessionStorage.removeItem(RELOAD_FLAG);
  } catch {
    /* ignore */
  }
}

/** Reloads the page once per session to pick up a fresh build. Returns false if already tried. */
export function reloadOnceForStaleChunk(): boolean {
  if (flagSet()) return false;
  setFlag();
  window.location.reload();
  return true;
}

/** Wraps a dynamic-import factory for React.lazy: a fetch failure triggers one page reload. */
export function lazyWithReload<T>(factory: () => Promise<T>): () => Promise<T> {
  return async () => {
    try {
      const mod = await factory();
      clearStaleChunkFlag(); // healthy import → re-arm the guard for the next deploy
      return mod;
    } catch (err) {
      if (reloadOnceForStaleChunk()) {
        return new Promise<T>(() => {}); // hold the Suspense spinner while the reload lands
      }
      throw err;
    }
  };
}
