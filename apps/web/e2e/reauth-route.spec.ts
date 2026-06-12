// Piece 3: the /reauth deep link (from the day-40 expiry email) opens the one-MFA credential-capture
// dialog over the dashboard. An authed leader landing on /reauth sees the dialog and ends on a tab.
import { test, expect } from '@playwright/test';
import { openDashboard } from './support';

test.describe('reauth deep link', () => {
  test('/reauth opens the re-authorize dialog and lands on the dashboard', async ({ page }) => {
    await openDashboard(page, { path: '/reauth' });
    // The dialog (the one-MFA enroll flow) opens…
    await expect(page.getByRole('dialog', { name: 'Re-authorize daily sync' })).toBeVisible();
    // …over the dashboard (the route bounced to a tab, not stuck on /reauth).
    await expect(page).toHaveURL(/\/baptisms$/);
  });
});
