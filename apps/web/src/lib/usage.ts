// Record that the app was opened — the input side of the ops console's Usage panel (migration 0066).
//
// Fire-and-forget by design. `record_app_open` derives unit/stake/calling/role from the caller's own
// user_roles row server-side and stores no email or name, so there is nothing here to get wrong or
// to leak; and it is idempotent for the day, so a reload or a second tab costs one no-op round trip.
// Telemetry must never be able to break or slow an app open, hence: no await at the call site, no
// error surfaced, and a per-tab guard so we do it once per session rather than on every mount.

import { supabase } from './supabase';

const SURFACE = 'web';
const ONCE_KEY = 'cp.usage.recorded';

let recordedThisLoad = false;

/** Call once when the signed-in app mounts. Safe to call repeatedly. */
export function recordAppOpen(): void {
  if (recordedThisLoad) return;
  recordedThisLoad = true;
  try {
    // sessionStorage survives client-side navigation but not a new tab, which is the granularity we
    // want. It can throw (Safari private mode) — that must not stop the call, only the memo.
    if (sessionStorage.getItem(ONCE_KEY) === SURFACE) return;
    sessionStorage.setItem(ONCE_KEY, SURFACE);
  } catch {
    /* no sessionStorage — the in-memory guard above plus the DB's per-day uniqueness is enough */
  }
  void supabase.rpc('record_app_open', { p_surface: SURFACE }).then(
    () => undefined,
    () => undefined, // an older database without 0066 applied simply records nothing
  );
}
