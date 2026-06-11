// Scenario 4 — the state-aware Sync settings sheet: which actions each credential state offers.
//   none            → "Set up daily sync" only
//   active provider → "Sync my stake now" + "Revoke my sync access" (no Re-authorize)
//   stale provider  → "Needs re-authorization" + lastError + Re-authorize + Revoke (NO Sync now)
//   revoked         → "Revoked" + Re-authorize only (no Revoke / Sync now — the 2026-06-10 fix)
//   active viewer   → status only, zero actions
// Re-authorize opens the in-app ReauthDialog over the dashboard — never a bounce to /login.

import { test, expect } from '@playwright/test';
import { openDashboard, pickMenuItem, enrollmentStatus, UNIT_NUMBER } from './support';

async function openSyncSettings(page: import('@playwright/test').Page) {
  await pickMenuItem(page, 'Sync settings');
  const sheet = page.getByRole('dialog', { name: 'Sync settings' });
  await expect(sheet).toBeVisible();
  return sheet;
}

test.describe('sync settings sheet', () => {
  test('no credential → "Set up daily sync" and nothing else', async ({ page }) => {
    await openDashboard(page, {
      broker: { 'GET /auth/enrollment-status': { json: enrollmentStatus({}, { state: 'none', complete: false }) } },
    });
    const sheet = await openSyncSettings(page);

    await expect(sheet.getByText(`No sync credential for stake ${UNIT_NUMBER}`)).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Set up daily sync' })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Sync my stake now' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Revoke my sync access' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Re-authorize daily sync' })).not.toBeVisible();
  });

  test('active provider → Sync now + Revoke, no Re-authorize', async ({ page }) => {
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': { json: enrollmentStatus({}, { state: 'active', is_provider: true }) },
      },
    });
    const sheet = await openSyncSettings(page);

    await expect(sheet.getByText('Active', { exact: true })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Sync my stake now' })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Revoke my sync access' })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Wipe stake data' })).toBeVisible(); // provider-only
    await expect(sheet.getByRole('button', { name: 'Re-authorize daily sync' })).not.toBeVisible();
  });

  test('stale provider → "Needs re-authorization" + last error + Re-authorize + Revoke, NO Sync now', async ({ page }) => {
    const lastError = 'SSO did not complete — the saved session expired upstream.';
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus({}, { state: 'stale', is_provider: true, last_error: lastError }),
        },
      },
    });
    const sheet = await openSyncSettings(page);

    await expect(sheet.getByText('Needs re-authorization')).toBeVisible();
    await expect(sheet.getByText(`Last sync error: ${lastError}`)).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Re-authorize daily sync' })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Revoke my sync access' })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Sync my stake now' })).not.toBeVisible();
  });

  test('revoked → "Revoked" + Re-authorize only (no Revoke, no Sync now)', async ({ page }) => {
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': { json: enrollmentStatus({}, { state: 'revoked', is_provider: true }) },
      },
    });
    const sheet = await openSyncSettings(page);

    await expect(sheet.getByText('Revoked', { exact: true })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Re-authorize daily sync' })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Revoke my sync access' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Sync my stake now' })).not.toBeVisible();
  });

  test('active NON-provider → status only, zero actions', async ({ page }) => {
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': { json: enrollmentStatus({}, { state: 'active', is_provider: false }) },
      },
    });
    const sheet = await openSyncSettings(page);

    await expect(sheet.getByText('Active', { exact: true })).toBeVisible();
    await expect(sheet.getByText('Provided by')).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Sync my stake now' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Revoke my sync access' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Re-authorize daily sync' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Set up daily sync' })).not.toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Wipe stake data' })).not.toBeVisible();
  });

  test('Re-authorize opens the ReauthDialog over the dashboard, never the login screen', async ({ page }) => {
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus({}, { state: 'stale', is_provider: true, last_error: 'session expired' }),
        },
      },
    });
    const sheet = await openSyncSettings(page);
    await sheet.getByRole('button', { name: 'Re-authorize daily sync' }).click();

    const reauth = page.getByRole('dialog', { name: 'Re-authorize daily sync' });
    await expect(reauth).toBeVisible();
    await expect(reauth.getByLabel('Church username')).toBeVisible();
    // Still on the dashboard route — the signed-in user was NOT bounced to /login.
    await expect(page).toHaveURL(/\/baptisms$/);
  });
});
