// Scenario 2 — the Church-login MFA steps: factor picker (2 factors), code entry, a wrong-code
// error, the happy path through to the dashboard, and the single-factor auto-select shortcut.
// Hardened after 2026-06-11 (a stake leader stranded at MFA): stale input must never survive a
// factor switch or a failed verify, Verify gates on a complete code, resend has a cooldown, and
// alternate sign-in routes hide mid-MFA.

import { test, expect } from '@playwright/test';
import {
  openLogin, submitChurchLogin, expectOnDashboard, brokerLogin, brokerMfa, MFA_FACTORS,
} from './support';

const codeSentText = (label: string) => new RegExp(`A code was just sent via ${label}`);

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

    await expect(page.getByText(codeSentText(MFA_FACTORS[0].label))).toBeVisible();
    await expect(page.getByLabel('Verification code')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Verify & sign in' })).toBeVisible();

    const selects = broker.callsTo('/auth/mfa/select');
    expect(selects).toHaveLength(1);
    expect(selects[0].body).toMatchObject({ login_id: 'e2e-login-1', factor_id: MFA_FACTORS[0].id });
  });

  test('a wrong code shows the broker error, stays on the code step, and clears the input', async ({ page }) => {
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
    // The rejected code must be retyped fresh — a stale value resubmitted against a new challenge
    // is the exact 2026-06-11 failure.
    await expect(page.getByLabel('Verification code')).toHaveValue('');
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
    await expect(page.getByText(codeSentText(only[0].label))).toBeVisible();
    await expect(page.getByText('Choose how to receive your verification code:')).not.toBeVisible();
    expect(broker.callsTo('/auth/mfa/select')).toHaveLength(1);
  });

  test('switching factors clears the typed code', async ({ page }) => {
    await openLogin(page, {
      broker: { 'POST /auth/password': { json: brokerMfa() } },
    });

    await submitChurchLogin(page);
    await page.getByRole('button', { name: MFA_FACTORS[0].label }).click();
    await page.getByLabel('Verification code').fill('123456');

    await page.getByRole('button', { name: 'Choose a different method' }).click();
    await page.getByRole('button', { name: MFA_FACTORS[1].label }).click();

    // Input typed for the OLD factor must never ride into the new challenge.
    await expect(page.getByLabel('Verification code')).toHaveValue('');
  });

  test('Verify is gated on a complete code and the input strips non-digits', async ({ page }) => {
    await openLogin(page, {
      broker: { 'POST /auth/password': { json: brokerMfa() } },
    });

    await submitChurchLogin(page);
    await page.getByRole('button', { name: MFA_FACTORS[0].label }).click();

    const verify = page.getByRole('button', { name: 'Verify & sign in' });
    await expect(verify).toBeDisabled();
    await page.getByLabel('Verification code').fill('123');
    await expect(verify).toBeDisabled();
    // "123 4-56" pasted from a text → digits only.
    await page.getByLabel('Verification code').fill('123 4-56');
    await expect(page.getByLabel('Verification code')).toHaveValue('123456');
    await expect(verify).toBeEnabled();
  });

  test('resend starts on cooldown and the MFA steps hide alternate sign-in routes', async ({ page }) => {
    await openLogin(page, {
      broker: { 'POST /auth/password': { json: brokerMfa() } },
    });

    // Pre-MFA: the method switch is there.
    await expect(page.getByRole('button', { name: 'Email code' })).toBeVisible();

    await submitChurchLogin(page);

    // Mid-MFA (factor picker): one flow at a time — no mode switch, no passkey button
    // (2026-06-11: a member clicked "Sign in with a passkey" mid-MFA and silently dead-ended).
    await expect(page.getByRole('button', { name: 'Email code' })).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in with a passkey' })).not.toBeVisible();
    await expect(page.getByRole('button', { name: 'Start over' })).toBeVisible();

    await page.getByRole('button', { name: MFA_FACTORS[0].label }).click();

    // Fresh send → resend is cooling down with a visible countdown.
    await expect(page.getByRole('button', { name: /Send a new code \(\d+s\)/ })).toBeDisabled();

    // "Start over" is the no-dead-end escape back to the password step.
    await page.getByRole('button', { name: 'Start over' }).click();
    await expect(page.getByLabel('Church username')).toBeVisible();
  });
});
