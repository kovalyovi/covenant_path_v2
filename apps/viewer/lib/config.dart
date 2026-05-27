// Supabase connection — passed at build/run time via --dart-define so no secrets are
// committed. The anon/publishable key is safe on clients (RLS does the gating).
//
//   flutter run --dart-define=SUPABASE_URL=https://<ref>.supabase.co \
//               --dart-define=SUPABASE_ANON_KEY=sb_publishable_...
const supabaseUrl = String.fromEnvironment('SUPABASE_URL', defaultValue: '');
const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY', defaultValue: '');
