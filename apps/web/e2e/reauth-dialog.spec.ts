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

  test('Email-code mode asks for the USERNAME and warns on an email-shaped identifier (A28)', async ({ page }) => {
    // Regression (2026-06-12, Ken Packer): the field was labeled "Church email", but the Church
    // Okta org only matches the USERNAME — an unknown identifier gets Okta's enumeration-prevention
    // phantom flow ("code sent", nothing ever arrives, every code "invalid"). The field now asks
    // for the username, and an email-shaped identifier gets the warning before AND after the send.
    const { broker } = await openReauth(page, {
      'POST /auth/otp/start': { json: { status: 'code_sent', sent_to: 'Email' } },
    });
    const dialog = reauthDialog(page);
    await dialog.getByRole('button', { name: 'Email code' }).click();

    const identField = dialog.getByLabel('Church username');
    // The saved LCR username is exactly the right autofill for this field now.
    await expect(identField).toHaveAttribute('autocomplete', 'username');

    await identField.fill('leader@example.com');
    await expect(dialog.getByText(/Codes are sent by Church USERNAME/)).toBeVisible();
    await dialog.getByRole('button', { name: 'Send code', exact: true }).click();

    // Wait for the sent-state transition (proves otpStart resolved) BEFORE asserting the recorded
    // call; the warning persists on the code screen, and the typed identifier is POSTed (NOT blank
    // — the 2026-06-11 autofill/empty-state regression stays covered).
    await expect(dialog.getByText(/A code was sent/)).toBeVisible();
    await expect(dialog.getByText(/Codes are sent by Church USERNAME/)).toBeVisible();
    const starts = broker.callsTo('/auth/otp/start');
    expect(starts).toHaveLength(1);
    expect(starts[0].body).toMatchObject({ email: 'leader@example.com', enroll: true });

    // A plain username raises no warning.
    await dialog.getByRole('button', { name: 'Use a different username' }).click();
    await identField.fill('leader.example');
    await expect(dialog.getByText(/Codes are sent by Church USERNAME/)).not.toBeVisible();
  });

  test('a send-burst throttle hint from the broker shows on the code screen', async ({ page }) => {
    // Okta silently pauses email delivery after a burst of code requests (2026-06-12) — the
    // broker counts sends and warns; the dialog must surface that instead of a silent dead-end.
    const hint =
      'Several codes were requested for this account recently — the Church sign-in service may ' +
      'quietly pause email delivery for a while.';
    await openReauth(page, {
      'POST /auth/otp/start': { json: { status: 'code_sent', sent_to: 'Email', throttle_hint: hint } },
    });
    const dialog = reauthDialog(page);
    await dialog.getByRole('button', { name: 'Email code' }).click();
    await dialog.getByLabel('Church username').fill('leader.example');
    await dialog.getByRole('button', { name: 'Send code', exact: true }).click();

    await expect(dialog.getByText(/quietly pause email delivery/)).toBeVisible();
  });

  test('an MFA-enabled account continues past the emailed code to the password step (A29)', async ({ page }) => {
    // Regression (2026-06-12, the operator's account after enabling MFA): the emailed code is
    // ACCEPTED and Okta then demands a DISTINCT factor — the password. Pre-fix the broker
    // classified the continuation as a bad code ("We couldn't verify that code") forever.
    const { broker } = await openReauth(page, {
      'POST /auth/otp/start': { json: { status: 'code_sent', sent_to: 'Email' } },
      'POST /auth/otp/verify': {
        json: {
          status: 'mfa_required',
          login_id: 'L-cont',
          factors: [{ id: 'pw1', label: 'Password', method: 'password' }],
        },
      },
      'POST /auth/mfa/select': { json: { status: 'code_sent' } },
      'POST /auth/mfa/verify': { json: brokerLogin({ authorized: true, stored: true }) },
    });
    const dialog = reauthDialog(page);
    await dialog.getByRole('button', { name: 'Email code' }).click();
    await dialog.getByLabel('Church username').fill('leader.example');
    await dialog.getByRole('button', { name: 'Send code', exact: true }).click();
    await dialog.getByLabel('Verification code').fill('123456');
    await dialog.getByRole('button', { name: 'Verify & authorize' }).click();

    // The single password factor auto-selects and the step renders a PASSWORD box, not a code
    // box — and there's no "Send a new code" (nothing was sent for a password).
    await expect(dialog.getByText(/Your code was accepted/)).toBeVisible();
    const pw = dialog.getByLabel('Password', { exact: true });
    await expect(pw).toHaveAttribute('type', 'password');
    await expect(dialog.getByRole('button', { name: /Send a new code/ })).not.toBeVisible();
    expect(broker.callsTo('/auth/mfa/select')).toHaveLength(1);

    await pw.fill('correct-horse');
    await dialog.getByRole('button', { name: 'Verify & authorize' }).click();

    await expect(page.getByText('Daily sync authorized — your stake will refresh within minutes.')).toBeVisible();
    await expect(dialog).not.toBeVisible();
    // OTP lane → the continuation completes on /auth/mfa/verify (webMode is false for OTP).
    const verifies = broker.callsTo('/auth/mfa/verify');
    expect(verifies).toHaveLength(1);
    expect(verifies[0].body).toMatchObject({ login_id: 'L-cont', code: 'correct-horse', enroll: true });
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

    await dialog.getByLabel('Verification code').fill('123456');
    await dialog.getByRole('button', { name: 'Verify & authorize' }).click();

    await expect(page.getByText('Daily sync authorized — your stake will refresh within minutes.')).toBeVisible();
    await expect(dialog).not.toBeVisible();

    const verifies = broker.callsTo('/auth/web/verify');
    expect(verifies).toHaveLength(1);
    expect(verifies[0].body).toMatchObject({ code: '123456', enroll: true });
  });
});
