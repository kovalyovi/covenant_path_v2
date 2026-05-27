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
