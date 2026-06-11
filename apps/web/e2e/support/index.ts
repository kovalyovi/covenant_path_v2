// Shared e2e plumbing: one import for specs. Each test wires FRESH routes (no cross-test state):
// call openDashboard()/openLogin() at the top of every test.

import { expect, type Page } from '@playwright/test';
import {
  mockBroker, mockSupabase, type BrokerOverrides, type Recorder, type SupabaseFixtures,
} from './mocks';
import { seedSession } from './session';

export * from './fixtures';
export * from './mocks';
export * from './session';

export interface DashboardHandles {
  supabase: Recorder;
  broker: Recorder;
}

/**
 * Signed-in dashboard: seeds a Supabase session, mocks both network edges, and lands on `path`
 * (default the / -> /baptisms redirect). Pass fixture/override deltas per scenario.
 */
export async function openDashboard(
  page: Page,
  opts: { supabase?: SupabaseFixtures; broker?: BrokerOverrides; path?: string } = {},
): Promise<DashboardHandles> {
  await seedSession(page);
  const supabase = await mockSupabase(page, opts.supabase);
  const broker = await mockBroker(page, opts.broker);
  await page.goto(opts.path ?? '/');
  return { supabase, broker };
}

/** Signed-out login screen with both edges mocked (login completions need Supabase verify + the
 *  post-login dashboard data). */
export async function openLogin(
  page: Page,
  opts: { supabase?: SupabaseFixtures; broker?: BrokerOverrides } = {},
): Promise<DashboardHandles> {
  const supabase = await mockSupabase(page, opts.supabase);
  const broker = await mockBroker(page, opts.broker);
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Covenant Path' })).toBeVisible();
  return { supabase, broker };
}

/** Fill the Church-account form and submit (step 1 of the church flow). */
export async function submitChurchLogin(
  page: Page,
  username = 'leader.example',
  password = 'correct-horse',
): Promise<void> {
  await page.getByLabel('Church username').fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}

/** Open the app-bar "…" menu and pick an item by its label. */
export async function pickMenuItem(page: Page, label: string): Promise<void> {
  await page.getByRole('button', { name: 'Menu' }).click();
  await page.getByRole('menuitem', { name: label }).click();
}

/** The dashboard is considered loaded once the URL settled on a tab. */
export async function expectOnDashboard(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/baptisms$/, { timeout: 30_000 });
}
