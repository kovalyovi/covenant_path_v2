// Scenario 1 — login surface messages: form rendering, server error details shown verbatim via
// role=alert (and NEVER a session), the N2 no-access block, and the cold-broker "waking up" status.

import { test, expect } from '@playwright/test';
import { openLogin, submitChurchLogin, expectOnDashboard, brokerLogin } from './support';
import { kNoAccessMessage } from '../src/lib/disclaimer';

test.describe('login messages', () => {
  test('church mode renders with both sign-in methods and the credential fields', async ({ page }) => {
    await openLogin(page);

    const method = page.getByRole('group', { name: 'Sign-in method' });
    await expect(method.getByRole('button', { name: 'Church account' })).toHaveAttribute('aria-pressed', 'true');
    await expect(method.getByRole('button', { name: 'Email code' })).toBeVisible();

    await expect(page.getByText('Sign in with your Church account (same as LCR).')).toBeVisible();
    await expect(page.getByLabel('Church username')).toBeVisible();
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  });

  test('bad credentials show the broker detail in role=alert and stay on the login screen', async ({ page }) => {
    const detail = 'That username or password is incorrect. Please try again.';
    const { supabase } = await openLogin(page, {
      broker: { 'POST /auth/password': { status: 401, json: { detail } } },
    });

    await submitChurchLogin(page, 'leader.example', 'wrong-password');

    await expect(page.getByRole('alert')).toHaveText(detail);
    await expect(page).toHaveURL(/\/login$/);
    // No session was minted: the app never called Supabase verify.
    expect(supabase.callsTo('/auth/v1/verify')).toHaveLength(0);
  });

  test('an LCR-outage 503 detail is rendered verbatim', async ({ page }) => {
    const detail =
      'Church systems (LCR) are temporarily unavailable right now — your password was correct, ' +
      'but sign-in could not be completed. Please try again in a few minutes.';
    await openLogin(page, {
      broker: { 'POST /auth/password': { status: 503, json: { detail } } },
    });

    await submitChurchLogin(page);

    await expect(page.getByRole('alert')).toHaveText(detail);
    await expect(page).toHaveURL(/\/login$/);
  });

  test('authorized:false blocks the login with the no-access message (N2)', async ({ page }) => {
    const { supabase } = await openLogin(page, {
      broker: {
        'POST /auth/password': {
          json: brokerLogin({ authorized: false, stored: false }),
        },
      },
    });

    await submitChurchLogin(page);

    await expect(page.getByRole('alert')).toHaveText(kNoAccessMessage);
    await expect(page).toHaveURL(/\/login$/);
    // Blocked BEFORE a session exists — verifyOtp must never have been called.
    expect(supabase.callsTo('/auth/v1/verify')).toHaveLength(0);
  });

  test('a cold broker (health fails twice) shows the waking-up status, then sign-in completes', async ({ page }) => {
    await openLogin(page, {
      broker: {
        // First two /health pings fail like a sleeping Render container; third succeeds.
        'GET /health': ({ call }) => (call <= 2 ? 'abort' : { json: { ok: true } }),
      },
    });

    await submitChurchLogin(page);

    await expect(page.getByRole('status')).toContainText('Waking up the sign-in service', {
      timeout: 20_000,
    });
    // Once warm, the login proceeds to the dashboard.
    await expectOnDashboard(page);
  });
});
