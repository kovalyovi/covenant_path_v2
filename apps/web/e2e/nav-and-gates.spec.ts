// Scenario 8 — navigation + access gates: the 5 tabs route via the side rail, the freshness chip
// reflects a stale last-synced date, and a viewer whose RLS scope returns nothing sees the scoped
// empty message — never someone else's data.

import { test, expect } from '@playwright/test';
import { openDashboard, enrollmentStatus, stakeRow, daysAgoIso } from './support';

test.describe('navigation and gates', () => {
  test('all five tabs navigate via the rail', async ({ page }) => {
    await openDashboard(page);
    const rail = page.getByRole('navigation', { name: 'Primary' });

    await expect(page).toHaveURL(/\/baptisms$/);
    await expect(page.getByText('Upcoming Baptisms')).toBeVisible();
    await expect(page.getByText('Jordan Sample')).toBeVisible(); // the goal-date investigator

    await rail.getByRole('link', { name: 'Golden Hour' }).click();
    await expect(page).toHaveURL(/\/golden-hour$/);
    await expect(page.getByText('Recently Baptized')).toBeVisible();

    await rail.getByRole('link', { name: 'Needs' }).click();
    await expect(page).toHaveURL(/\/needs$/);
    await expect(page.getByText('Action Needed')).toBeVisible();

    await rail.getByRole('link', { name: 'KPIs' }).click();
    await expect(page).toHaveURL(/\/kpis$/);
    await expect(page.getByText("From this stake's covenant-path data")).toBeVisible();

    await rail.getByRole('link', { name: 'Table' }).click();
    await expect(page).toHaveURL(/\/table$/);
    await expect(page.getByRole('table')).toBeVisible();

    await rail.getByRole('link', { name: 'Baptisms' }).click();
    await expect(page).toHaveURL(/\/baptisms$/);
  });

  test('the freshness chip reflects a stale last-synced date', async ({ page }) => {
    await openDashboard(page, {
      supabase: { stakes: [stakeRow({ last_synced_at: daysAgoIso(10) })] },
    });

    const chip = page.getByRole('button', { name: /^Updated 10d ago$/ });
    await expect(chip).toBeVisible();

    // The chip opens the freshness dialog, which offers Sync now (broker is configured).
    await chip.click();
    const dialog = page.getByRole('dialog', { name: 'Data freshness' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Last scraped from LCR:')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Sync now' })).toBeVisible();
    await dialog.getByRole('button', { name: 'Close' }).first().click(); // title × + footer Close share the name
  });

  test('a viewer with no role sees the scoped empty message, not member data', async ({ page }) => {
    await openDashboard(page, {
      supabase: { stakes: [], members: [], comments: [] }, // RLS returns nothing for this login
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus({ status: 'no_role', member_count: 4, has_data: true }),
        },
      },
    });

    await expect(page.getByRole('heading', { name: 'No access with your current calling' })).toBeVisible();
    await expect(page.getByText("your current calling doesn't grant access")).toBeVisible();
    // Zero member data leaks into the view.
    await expect(page.getByText('Avery Example')).not.toBeVisible();
    await expect(page.getByText('Jordan Sample')).not.toBeVisible();
  });
});
