// Best-effort client error telemetry → broker `/log` (mirrors apps/viewer/lib/error_reporter.dart).
// Sends only the error type, a truncated message, and a route hint — NEVER member data. No-op
// without a broker URL. Sentry (when a DSN is set) is initialized separately in main.tsx.

import { brokerUrl } from './config';

// CLIENT-04: a thrown Supabase/Postgrest/render error can embed member data (emails, names, tokens
// in URLs) in its `.message`. Strip the obvious PII patterns before anything leaves the device —
// the goal is a diagnosable error class, not raw content.
export function scrub(s: string): string {
  return s
    .replace(/[\w.+-]+@[\w.-]+\.\w+/g, '<email>')
    .replace(/https?:\/\/\S+/g, '<url>')
    .replace(/\b\d{6,}\b/g, '<num>')
    .slice(0, 300);
}

export function reportError(error: unknown, where?: string): void {
  if (!brokerUrl) return;
  const msg = error instanceof Error ? error.message : String(error);
  const type = error instanceof Error ? error.name : typeof error;
  // telemetry must never throw / block
  void fetch(`${brokerUrl}/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level: 'error',
      event: 'client.error',
      surface: 'web',
      message: scrub(msg),
      context: { type, ...(where ? { where } : {}) },
    }),
  }).catch(() => {});
}

/** Install global handlers that report uncaught errors + promise rejections to the broker. */
export function installErrorReporting(): void {
  window.addEventListener('error', (e) => reportError(e.error ?? e.message, 'window'));
  window.addEventListener('unhandledrejection', (e) => reportError(e.reason, 'promise'));
}
