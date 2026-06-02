import { createClient } from '@supabase/supabase-js';
import { supabaseUrl, supabaseAnonKey } from './config';

// The single Supabase client. Like the Flutter app, the browser reads Supabase directly and RLS
// scopes every row to the signed-in user — the client does no access filtering. Sessions persist
// in localStorage and refresh automatically, so a returning leader stays signed in.
export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

/** Current Supabase access token (Bearer for broker calls), or '' when signed out. */
export async function currentAccessToken(): Promise<string> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? '';
}
