// Scenario 2 — the Church-login MFA steps: factor picker (2 factors), code entry, a wrong-code
// error, the happy path through to the dashboard, and the single-factor auto-select shortcut.

import { test, expect } from '@playwright/test';
import {
  openLogin, submitChurchLogin, expectOnDashboard, brokerLogin, brokerMfa, MFA_FACTORS,
} from './support';

test.describe('login MFA', () => {
  test('two factors show a picker; choosing one reveals the code field', async ({ page }) => {
    const { broker } = await openLogin(page, {
      broker: { 'POST /auth/password': { json: brokerMfa() } },
    });

    await submitChurchLogin(page);

    await expect(page.getByText('Choose how to receive your verification code:')).toBeVisible();
    const sms = page.getByRole('button', { name: MFA_FACTORS[0].label });
    await expect(sms).toBeVisible();
    await expect(page.getByRole('button', { name: MFA_FACTORS[1].label })).toBeVisible();

    await sms.click();

    await expect(page.getByText(`Enter the code sent via ${MFA_FACTORS[0].label}.`)).toBeVisible();
    await expect(page.getByLabel('Verification code')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Verify & sign in' })).toBeVisible();

    const selects = broker.callsTo('/auth/mfa/select');
    expect(selects).toHaveLength(1);
    expect(selects[0].body).toMatchObject({ login_id: 'e2e-login-1', factor_id: MFA_FACTORS[0].id });
  });

  test('a wrong code shows the broker error and stays on the code step', async ({ page }) => {
    const detail = 'That code did not work — codes expire quickly. Request a fresh one and try again.';
    await openLogin(page, {
      broker: {
        'POST /auth/password': { json: brokerMfa() },
        'POST /auth/mfa/verify': { status: 401, json: { detail } },
      },
    });

    await submitChurchLogin(page);
    await page.getByRole('button', { name: MFA_FACTORS[0].label }).click();
    await page.getByLabel('Verification code').fill('000000');
    await page.getByRole('button', { name: 'Verify & sign in' }).click();

    await expect(page.getByRole('alert')).toHaveText(detail);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByLabel('Verification code')).toBeVisible();
  });

  test('the correct code completes sign-in to the dashboard', async ({ page }) => {
    const { broker } = await openLogin(page, {
      broker: {
        'POST /auth/password': { json: brokerMfa() },
        'POST /auth/mfa/verify': { json: brokerLogin() },
      },
    });

    await submitChurchLogin(page);
    await page.getByRole('button', { name: MFA_FACTORS[0].label }).click();
    await page.getByLabel('Verification code').fill('123456');
    await page.getByRole('button', { name: 'Verify & sign in' }).click();

    await expectOnDashboard(page);
    const verifies = broker.callsTo('/auth/mfa/verify');
    expect(verifies).toHaveLength(1);
    expect(verifies[0].body).toMatchObject({ login_id: 'e2e-login-1', code: '123456', enroll: false });
  });

  test('a single factor auto-selects and goes straight to code entry', async ({ page }) => {
    const only = [MFA_FACTORS[0]];
    const { broker } = await openLogin(page, {
      broker: { 'POST /auth/password': { json: brokerMfa(only) } },
    });

    await submitChurchLogin(page);

    // No picker — the lone factor was auto-selected and its code prompt is already showing.
    await expect(page.getByText(`Enter the code sent via ${only[0].label}.`)).toBeVisible();
    await expect(page.getByText('Choose how to receive your verification code:')).not.toBeVisible();
    expect(broker.callsTo('/auth/mfa/select')).toHaveLength(1);
  });
});
