// Playwright e2e — UI-state lane (Phase A): the app runs against FAKE hosts and every network
// edge (Supabase REST/auth + the auth broker) is mocked per-test with page.route(), so the suite
// needs zero secrets and zero backends. PUBLIC repo: fixtures are fictional (Testvale North Stake,
// unit 999001 — see e2e/support/fixtures.ts). The `fullstack` project is the Phase B skeleton:
// it only materializes under E2E_FULLSTACK=1 and will point at the real broker + mock-LCR +
// test-Supabase stack.

import { defineConfig, devices } from '@playwright/test';

const PORT = 5199;

/** Fake-host env the dev server is started with — names match src/lib/config.ts exactly.
 *  Process env beats any local .env file, so a developer's real config can never leak in. */
export const E2E_ENV = {
  VITE_SUPABASE_URL: 'http://supabase.local.test',
  VITE_SUPABASE_ANON_KEY: 'test-anon',
  VITE_BROKER_URL: 'http://broker.local.test',
  VITE_SENTRY_DSN: '',
};

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Dev-server on-demand transforms (first hit on a lazy chunk) can take a few seconds; generous
  // expect timeout absorbs that without papering over real hangs.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
      testIgnore: '**/fullstack/**',
    },
    // Phase B: real auth_broker + mock LCR + test Supabase. Skeleton only — opt in explicitly.
    ...(process.env.E2E_FULLSTACK === '1'
      ? [
          {
            name: 'fullstack',
            use: { ...devices['Desktop Chrome'] },
            testMatch: '**/fullstack/**/*.spec.ts',
          },
        ]
      : []),
  ],
  webServer: {
    command: `npm run dev -- --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 90_000,
    env: E2E_ENV,
  },
});
