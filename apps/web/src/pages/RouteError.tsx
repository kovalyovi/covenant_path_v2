// Route-level errorElement — replaces React Router's "Unexpected Application Error!" dump with a
// friendly recovery screen. A stale-chunk import error (deploy while a tab was open) auto-reloads
// once via lazyReload; this screen is the fallback when that didn't help (e.g. offline) or for any
// other render/loader error.

import { useEffect } from 'react';
import { useRouteError } from 'react-router-dom';
import { Button } from '../components/ui';
import { reportError } from '../lib/errorReporter';
import { reloadOnceForStaleChunk } from '../lib/lazyReload';

function isStaleChunkError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported/i.test(msg);
}

export function RouteError() {
  const error = useRouteError();

  useEffect(() => {
    if (isStaleChunkError(error) && reloadOnceForStaleChunk()) return;
    reportError(error, 'route-error');
  }, [error]);

  const stale = isStaleChunkError(error);
  return (
    <div className="center-col" style={{ minHeight: '100vh', gap: 12 }}>
      <h1 style={{ fontSize: '1.2rem' }}>{stale ? 'A new version is available' : 'Something went wrong'}</h1>
      <p className="muted" style={{ maxWidth: 480, textAlign: 'center' }}>
        {stale
          ? 'The app was updated while this tab was open. Reload to get the latest version.'
          : 'An unexpected error occurred. Reloading usually fixes it.'}
      </p>
      <Button onClick={() => window.location.reload()}>Reload</Button>
    </div>
  );
}
