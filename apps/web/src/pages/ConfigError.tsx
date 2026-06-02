// Shown when the Supabase config is missing — the web equivalent of the Flutter `_ConfigError`.

export function ConfigError() {
  return (
    <div className="center-col" style={{ minHeight: '100vh' }}>
      <h1 style={{ fontSize: '1.2rem' }}>Missing Supabase configuration</h1>
      <p className="muted" style={{ maxWidth: 480 }}>
        Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in a{' '}
        <code>.env</code> file (see <code>.env.example</code>), then rebuild. The anon/publishable
        key is safe on clients — Postgres RLS does the access gating.
      </p>
    </div>
  );
}
