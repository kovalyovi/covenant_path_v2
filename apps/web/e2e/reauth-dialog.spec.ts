// Scenario 5 — the in-app Church re-authorization dialog (enroll=true is the whole point):
// success toasts + closes; a stored:false result KEEPS the dialog open with the server's reason
// (the 2026-06-10 "toasted success that never happened" fix); MFA works inside the dialog.

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import {
  openDashboard, enrollmentStatus, brokerLogin, brokerMfa, MFA_FACTORS,
  type BrokerOverrides, type DashboardHandles,
} from './support';

const STALE_PROVIDER = {
  'GET /auth/enrollment-status': {
    json: enrollmentStatus({}, { state: 'stale', is_provider: true, last_error: 'session expired' }),
  },
} satisfies BrokerOverrides;

/** Open the dialog via the stale banner's Re-authorize action. */
async function openReauth(page: Page, broker: BrokerOverrides): Promise<DashboardHandles> {
  const handles = await openDashboard(page, { broker: { ...STALE_PROVIDER, ...broker } });
  await page.getByRole('button', { name: 'Re-authorize', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Re-authorize daily sync' })).toBeVisible();
  return handles;
}

function reauthDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Re-authorize daily sync' });
}

test.describe('reauth dialog', () => {
  test('successful enroll toasts "Daily sync authorized" and closes the dialog', async ({ page }) => {
    const { broker } = await openReauth(page, {
      'POST /auth/web/start': { json: brokerLogin({ authorized: true, stored: true }) },
    });

    const dialog = reauthDialog(page);
    await dialog.getByLabel('Church username').fill('leader.example');
    await dialog.getByLabel('Password', { exact: true }).fill('correct-horse');
    await dialog.getByRole('button', { name: 'Authorize', exact: true }).click();

    await expect(page.getByText('Daily sync authorized — your stake will refresh within minutes.')).toBeVisible();
    await expect(dialog).not.toBeVisible();
    await expect(page).toHaveURL(/\/baptisms$/); // stayed in the app the whole time

    // Password lane → the one-MFA credential-capture flow (mints the 45-day sync token).
    const logins = broker.callsTo('/auth/web/start');
    expect(logins).toHaveLength(1);
    expect(logins[0].body).toMatchObject({ enroll: true }); // this dialog IS the consent
  });

  test('stored:false keeps the dialog open and shows "could not be set up — <error>"', async ({ page }) => {
    const enrollError = 'LCR returned 502 on the access check.';
    await openReauth(page, {
      'POST /auth/web/start': { json: brokerLogin({ authorized: true, stored: false, error: enrollError }) },
    });

    const dialog = reauthDialog(page);
    await dialog.getByLabel('Church username').fill('leader.example');
    await dialog.getByLabel('Password', { exact: true }).fill('correct-horse');
    await dialog.getByRole('button', { name: 'Authorize', exact: true }).click();

    const alert = dialog.getByRole('alert');
    await expect(alert).toContainText('the daily sync could not be set up');
    await expect(alert).toContainText(enrollError);
    await expect(dialog).toBeVisible(); // STAYS open — no success toast for a failure
    await expect(page.getByText('Daily sync authorized — your stake will refresh within minutes.')).not.toBeVisible();
  });


  test('the MFA path inside the dialog completes the enroll', async ({ page }) => {
    const { broker } = await openReauth(page, {
      'POST /auth/web/start': { json: brokerMfa() },
      'POST /auth/web/select': { json: { status: 'code_sent' } },
      'POST /auth/web/verify': { json: brokerLogin({ authorized: true, stored: true }) },
    });

    const dialog = reauthDialog(page);
    await dialog.getByLabel('Church username').fill('leader.example');
    await dialog.getByLabel('Password', { exact: true }).fill('correct-horse');
    await dialog.getByRole('button', { name: 'Authorize', exact: true }).click();

    // Factor picker renders INSIDE the dialog.
    await expect(dialog.getByText('Choose how to receive your verification code:')).toBeVisible();
    await dialog.getByRole('button', { name: MFA_FACTORS[0].label }).click();
    await expect(
      dialog.getByText(new RegExp(`A new code was just sent via ${MFA_FACTORS[0].label}`)),
    ).toBeVisible();

    // The 6th digit auto-submits (useOtpAutoSubmit) — clicking Verify would race the auto-fire.
    await dialog.getByLabel('Verification code').fill('123456');

    await expect(page.getByText('Daily sync authorized — your stake will refresh within minutes.')).toBeVisible();
    await expect(dialog).not.toBeVisible();

    const verifies = broker.callsTo('/auth/web/verify');
    expect(verifies).toHaveLength(1);
    expect(verifies[0].body).toMatchObject({ code: '123456', enroll: true });
  });
});
