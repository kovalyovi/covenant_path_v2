import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite + React. No backend: the app reads Supabase (RLS-scoped) and the auth broker directly,
// exactly like the Flutter app (CORS-free). Config comes from VITE_* env at build time.
// (Vitest config lives in vitest.config.ts so the production build doesn't type-check test fields.)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    // Recharts is a large vendor lib; it's already lazy (only the KPIs tab pulls it via React.lazy),
    // so its standalone on-demand chunk is fine — lift the warning above its minified size.
    chunkSizeWarningLimit: 600,
    // Keep the charts library + Supabase in their own chunks so the initial bundle stays lean.
    rollupOptions: {
      output: {
        manualChunks: {
          recharts: ['recharts'],
          supabase: ['@supabase/supabase-js'],
        },
      },
    },
  },
});
