import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as Sentry from '@sentry/react';
import { onCLS, onINP, onLCP } from 'web-vitals';

import './theme/theme.css';
import './theme/components.css';
import { router } from './router';
import { ThemeProvider } from './hooks/useTheme';
import { ToastProvider } from './components/Toast';
import { sentryDsn, hasSupabaseConfig } from './lib/config';
import { installErrorReporting, reportError } from './lib/errorReporter';
import { reloadOnceForStaleChunk } from './lib/lazyReload';
import { ConfigError } from './pages/ConfigError';

// Sentry auto-captures uncaught errors + performance; our reporter chains on top so the same errors
// also reach the broker /log → Axiom. PII is never sent. No-op when no DSN is configured (#53).
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    tracesSampleRate: 0.2,
    sendDefaultPii: false,
    environment: import.meta.env.PROD ? 'production' : 'debug',
    integrations: [Sentry.browserTracingIntegration()],
  });
}
installErrorReporting();

// Vite fires this when a lazy chunk (or its CSS/deps) fails to load — typically a tab that
// outlived a deploy referencing now-deleted hashed assets. Reload once to pick up the new build;
// if that already happened this session, let the error bubble to the route errorElement.
window.addEventListener('vite:preloadError', (event) => {
  if (reloadOnceForStaleChunk()) event.preventDefault();
});

// Core Web Vitals → broker telemetry (mirrors the Flutter app's perf intent; PII-free).
function reportVital(name: string, value: number) {
  reportError(`web-vital ${name}=${Math.round(value)}`, 'web-vitals');
}
onCLS((m) => reportVital('CLS', m.value * 1000));
onINP((m) => reportVital('INP', m.value));
onLCP((m) => reportVital('LCP', m.value));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
});

const root = createRoot(document.getElementById('root')!);

root.render(
  <StrictMode>
    {hasSupabaseConfig ? (
      <Sentry.ErrorBoundary fallback={<AppCrash />}>
        <ThemeProvider>
          <QueryClientProvider client={queryClient}>
            <ToastProvider>
              <RouterProvider router={router} />
            </ToastProvider>
          </QueryClientProvider>
        </ThemeProvider>
      </Sentry.ErrorBoundary>
    ) : (
      <ThemeProvider>
        <ConfigError />
      </ThemeProvider>
    )}
  </StrictMode>,
);

function AppCrash() {
  return (
    <div className="center-col" style={{ minHeight: '100vh', gap: 12 }}>
      <h1>Something went wrong</h1>
      <p className="muted">An unexpected error occurred. Reloading usually fixes it.</p>
      <button className="btn btn--filled" onClick={() => window.location.reload()}>Reload</button>
    </div>
  );
}
