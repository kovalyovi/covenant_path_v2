// Playwright e2e — two mutually exclusive modes:
//
// UI-state lane (default): the app runs against FAKE hosts and every network edge (Supabase
// REST/auth + the auth broker) is mocked per-test with page.route(), so the suite needs zero
// secrets and zero backends. PUBLIC repo: fixtures are fictional (Testvale North Stake, unit
// 999001 — see e2e/support/fixtures.ts).
//
// FULLSTACK lane (E2E_FULLSTACK=1): the config itself boots the real stack — mock LCR/Okta + the
// REAL auth broker via `python -m tests.fullstack_stack`, plus vite pointed at the dedicated TEST
// Supabase project (CP_TEST_* from the repo .env) — and runs only e2e/fullstack/** against live
// RLS. Needs the seeded test project (python -m tests.seed); refuses production by construction
// (the stack runner + env.ts both guard).

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';
import { fullstackEnv } from './e2e/fullstack/env';

const HERE = path.dirname(fileURLToPath(import.meta.url));

const FULLSTACK = process.env.E2E_FULLSTACK === '1';
const PORT = FULLSTACK ? 5198 : 5199;
const BROKER_PORT = 8924; // fixed in tests/fullstack_stack.py

/** Fake-host env the dev server is started with — names match src/lib/config.ts exactly.
 *  Process env beats any local .env file, so a developer's real config can never leak in. */
export const E2E_ENV = {
  VITE_SUPABASE_URL: 'http://supabase.local.test',
  VITE_SUPABASE_ANON_KEY: 'test-anon',
  VITE_BROKER_URL: 'http://broker.local.test',
  VITE_SENTRY_DSN: '',
};

/** Fullstack vite env: the REAL test project + the local real broker. Called only under
 *  E2E_FULLSTACK=1, so the default lane never needs the repo .env. Only the ANON key reaches
 *  the browser. */
function fullstackViteEnv(): Record<string, string> {
  const e = fullstackEnv();
  return {
    VITE_SUPABASE_URL: e.url,
    VITE_SUPABASE_ANON_KEY: e.anon,
    VITE_BROKER_URL: `http://127.0.0.1:${BROKER_PORT}`,
    VITE_SENTRY_DSN: '',
  };
}

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
  projects: FULLSTACK
    ? [
        {
          name: 'fullstack',
          use: { ...devices['Desktop Chrome'] },
          testMatch: '**/fullstack/**/*.spec.ts',
        },
      ]
    : [
        {
          name: 'chromium',
          use: { ...devices['Desktop Chrome'] },
          testIgnore: '**/fullstack/**',
        },
      ],
  webServer: FULLSTACK
    ? [
        {
          // mock identity + mock LCR + the REAL broker (vs the TEST Supabase project).
          command: 'python -m tests.fullstack_stack',
          cwd: path.resolve(HERE, '..', '..'),
          url: `http://127.0.0.1:${BROKER_PORT}/health`,
          reuseExistingServer: true,
          timeout: 180_000,
          stdout: 'pipe',
          stderr: 'pipe',
        },
        {
          command: `npm run dev -- --port ${PORT} --strictPort`,
          url: `http://localhost:${PORT}`,
          reuseExistingServer: true,
          timeout: 90_000,
          env: fullstackViteEnv(),
        },
      ]
    : {
        command: `npm run dev -- --port ${PORT} --strictPort`,
        url: `http://localhost:${PORT}`,
        reuseExistingServer: !process.env.CI,
        timeout: 90_000,
        env: E2E_ENV,
      },
});
