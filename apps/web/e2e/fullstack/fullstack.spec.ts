// Phase B skeleton — the FULLSTACK lane: the real auth broker (backend/auth_broker) wired to a
// mock LCR + a disposable test Supabase, with NO page.route() mocks. Collected only under the
// `fullstack` Playwright project, which materializes when E2E_FULLSTACK=1 (playwright.config.ts).
//
// To wire this lane up, Phase B still needs:
//   1. A docker/devstack recipe that starts: supabase (or a seeded Postgres+gotrue+postgrest),
//      the broker (uvicorn backend.auth_broker) pointed at a mock-LCR server, and the web app
//      built with VITE_* pointing at those.
//   2. Seed data: migrations applied + a fixture stake (Testvale North Stake / 999001) + roles.
//   3. Replacing the placeholder below with real sign-in → dashboard assertions.

import { test, expect } from '@playwright/test';

test.describe('fullstack (Phase B)', () => {
  test.skip(process.env.E2E_FULLSTACK !== '1', 'Phase B: set E2E_FULLSTACK=1 once the real-backend stack exists');

  test('placeholder — real-stack smoke', async ({ page }) => {
    // TODO(Phase B): sign in through the REAL broker (mock-LCR credentials), assert the RLS-scoped
    // dashboard renders seeded Testvale data end-to-end.
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: 'Covenant Path' })).toBeVisible();
  });
});
