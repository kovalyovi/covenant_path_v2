// Scenario D-series (web) — Settings + Admin as URL-landable side sheets over the dashboard.
//   • the "…" menu opens Settings as a side sheet, the URL becomes /settings, and the dashboard stays
//     visible-but-dimmed behind it; Esc / scrim / close returns to the underlying tab + updates the URL.
//   • a DEEP LINK / refresh on /settings lands on the dashboard with the Settings sheet open (not a
//     bare standalone page) — the dashboard nav is present underneath.
//   • the Settings account section shows the signed-in user's stake / unit / calling(s) + the rights
//     each grants (stake-level "all units" vs ward-level "this unit only"), plus an admin badge.
//   • Admin opens as a WIDER side sheet for an admin user, URL = /admin, landable on refresh.

import { test, expect, type Page } from '@playwright/test';
import { openDashboard, STAKE_NAME } from './support';

/** Open the "…" menu and pick an item by its EXACT label ("Settings" vs "Sync settings"). */
async function openMenuItem(page: Page, label: string): Promise<void> {
  await page.getByRole('button', { name: 'Menu' }).click();
  await page.getByRole('menuitem', { name: label, exact: true }).click();
}

const STAKE_LEADER_ROLE = [
  { role: 'stake_leader', calling_name: 'Stake President', unit_id: null, stake_id: 's1', stakes: { name: STAKE_NAME } },
];
const WARD_LEADER_ROLE = [
  { role: 'ward_leader', calling_name: 'Bishop', unit_id: 'u1', stake_id: 's1', units: { name: 'Maple Ward' }, stakes: { name: STAKE_NAME } },
];

test.describe('settings + admin side sheets', () => {
  test('the menu opens Settings as a side sheet over the dashboard (URL = /settings)', async ({ page }) => {
    await openDashboard(page, { supabase: { userRoles: STAKE_LEADER_ROLE } });

    await openMenuItem(page, 'Settings');
    const sheet = page.getByRole('dialog', { name: 'Settings' });
    await expect(sheet).toBeVisible();
    await expect(page).toHaveURL(/\/settings$/);
    // The dashboard nav is still present underneath the sheet (it's an overlay, not a replacement).
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();

    // Esc closes the sheet and returns to the underlying tab — the URL updates back.
    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    await expect(page).toHaveURL(/\/baptisms$/);
  });

  test('closing via the × returns to the dashboard tab', async ({ page }) => {
    await openDashboard(page);
    await openMenuItem(page, 'Settings');
    const sheet = page.getByRole('dialog', { name: 'Settings' });
    await expect(sheet).toBeVisible();

    await sheet.getByRole('button', { name: 'Close' }).first().click();
    await expect(sheet).toBeHidden();
    await expect(page).toHaveURL(/\/baptisms$/);
  });

  test('deep link / refresh on /settings lands on the dashboard with the sheet open', async ({ page }) => {
    await openDashboard(page, { path: '/settings', supabase: { userRoles: STAKE_LEADER_ROLE } });

    // Not a bare standalone page: the dashboard shell (its nav) renders underneath the open sheet.
    await expect(page.getByRole('dialog', { name: 'Settings' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
  });

  test('account section shows a STAKE leader sees all units', async ({ page }) => {
    await openDashboard(page, { path: '/settings', supabase: { userRoles: STAKE_LEADER_ROLE } });
    const sheet = page.getByRole('dialog', { name: 'Settings' });

    await expect(sheet.getByText(STAKE_NAME, { exact: true })).toBeVisible();
    await expect(sheet.getByText(/Stake President — Sees all units in/)).toBeVisible();
  });

  test('account section shows a WARD leader sees their unit only', async ({ page }) => {
    await openDashboard(page, { path: '/settings', supabase: { userRoles: WARD_LEADER_ROLE } });
    const sheet = page.getByRole('dialog', { name: 'Settings' });

    await expect(sheet.getByText(/Bishop — Sees Maple Ward only/)).toBeVisible();
  });

  test('no role → an honest power-user note (not a broken/empty block)', async ({ page }) => {
    await openDashboard(page, { path: '/settings', supabase: { userRoles: [] } });
    const sheet = page.getByRole('dialog', { name: 'Settings' });

    await expect(sheet.getByText(/power user/i)).toBeVisible();
  });

  test('Admin opens as a WIDE side sheet for an admin (URL = /admin), landable on refresh', async ({ page }) => {
    await openDashboard(page, { path: '/admin', supabase: { isAdmin: true } });

    const sheet = page.getByRole('dialog', { name: 'Admin · Ops console' });
    await expect(sheet).toBeVisible();
    // The wide variant is applied (dense tables need the room).
    await expect(sheet).toHaveClass(/dialog--wide/);
    // Still over the dashboard (nav underneath), and URL-landable.
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
    await expect(page).toHaveURL(/\/admin$/);
  });
});
