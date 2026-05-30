// Supabase connection — passed at build/run time via --dart-define so no secrets are
// committed. The anon/publishable key is safe on clients (RLS does the gating).
//
//   flutter run --dart-define=SUPABASE_URL=https://<ref>.supabase.co \
//               --dart-define=SUPABASE_ANON_KEY=sb_publishable_...
const supabaseUrl = String.fromEnvironment('SUPABASE_URL', defaultValue: '');
const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY', defaultValue: '');

// Church-login auth broker (backend/auth_broker). Empty => only Email-code login is shown.
//   --dart-define=BROKER_URL=https://broker.membercovenantpath.org
const brokerUrl = String.fromEnvironment('BROKER_URL', defaultValue: '');

// Sentry crash/error reporting (#53). A Sentry DSN is not a secret — it's designed to live in the
// client — so it defaults to ours and is overridable per build. Empty => Sentry init is skipped.
//   --dart-define=SENTRY_DSN=
const sentryDsn = String.fromEnvironment('SENTRY_DSN',
    defaultValue: 'https://accbd77aff53cb49eba21ed7756ddfb4@o4511481035489280.ingest.us.sentry.io/4511481040470016');
