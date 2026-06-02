// App configuration — read from Vite env at build/run time so no secrets are committed.
// The anon/publishable Supabase key is safe on clients (Postgres RLS does the access gating);
// the broker URL gates which login modes show. Mirrors apps/viewer/lib/config.dart.

export const supabaseUrl = import.meta.env.VITE_SUPABASE_URL ?? '';
export const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY ?? '';

/** Church-login auth broker (backend/auth_broker). Empty => only Email-code login is shown. */
export const brokerUrl = (import.meta.env.VITE_BROKER_URL ?? '').replace(/\/$/, '');

/** Sentry DSN (a DSN is not a secret — it's designed to live on the client). Empty => skip init. */
export const sentryDsn = import.meta.env.VITE_SENTRY_DSN ?? '';

/** True only when the minimum config (Supabase) is present. */
export const hasSupabaseConfig = supabaseUrl.length > 0 && supabaseAnonKey.length > 0;
