// Scenario 3 — the POST-login "authorize daily sync?" offer (#8: consent moved off the login form):
// can_enroll:true raises a window.confirm; accepting re-auths with enroll:true, declining must NOT.
// A consented enroll that stored nothing must alert with the server's enrollError (the 2026-06-10
// LCR-outage honesty fix), never a silent fake success.

import { test, expect } from '@playwright/test';
import type { Dialog } from '@playwright/test';
import { openLogin, submitChurchLogin, expectOnDashboard, brokerLogin, STAKE_NAME } from './support';

test.describe('login enroll offer', () => {
  test('accepting the offer re-auths with enroll:true', async ({ page }) => {
    const dialogs: string[] = [];
    page.on('dialog', (d: Dialog) => {
      dialogs.push(d.message());
      void d.accept();
    });

    const { broker } = await openLogin(page, {
      broker: {
        'POST /auth/password': ({ call }) =>
          call === 1
            ? { json: brokerLogin({ authorized: true, stored: false, can_enroll: true, stake: STAKE_NAME }) }
            : { json: brokerLogin({ authorized: true, stored: true }) },
      },
    });

    await submitChurchLogin(page);
    await expectOnDashboard(page);

    expect(dialogs).toHaveLength(1);
    expect(dialogs[0]).toContain(`${STAKE_NAME} isn't set up for daily sync yet.`);
    expect(dialogs[0]).toContain('revocable anytime');

    const logins = broker.callsTo('/auth/password');
    expect(logins).toHaveLength(2);
    expect(logins[0].body).toMatchObject({ enroll: false });
    expect(logins[1].body).toMatchObject({ enroll: true }); // the re-auth carries the consent
  });

  test('declining the offer signs in without a second auth call', async ({ page }) => {
    const dialogs: string[] = [];
    page.on('dialog', (d: Dialog) => {
      dialogs.push(d.message());
      void d.dismiss();
    });

    const { broker } = await openLogin(page, {
      broker: {
        'POST /auth/password': {
          json: brokerLogin({ authorized: true, stored: false, can_enroll: true, stake: STAKE_NAME }),
        },
      },
    });

    await submitChurchLogin(page);
    await expectOnDashboard(page);

    expect(dialogs).toHaveLength(1);
    expect(broker.callsTo('/auth/password')).toHaveLength(1); // no consent → no re-auth
  });

  test('a consented enroll that stored nothing alerts with the enrollError text', async ({ page }) => {
    const enrollError = 'LCR is temporarily unavailable (502 on the access check) — nothing was stored.';
    const dialogs: Array<{ type: string; message: string }> = [];
    page.on('dialog', (d: Dialog) => {
      dialogs.push({ type: d.type(), message: d.message() });
      void d.accept();
    });

    await openLogin(page, {
      broker: {
        'POST /auth/password': ({ call }) =>
          call === 1
            ? { json: brokerLogin({ authorized: true, stored: false, can_enroll: true, stake: STAKE_NAME }) }
            : { json: brokerLogin({ authorized: true, stored: false, error: enrollError }) },
      },
    });

    await submitChurchLogin(page);
    await expectOnDashboard(page); // still signs in — the failure is reported, not fatal

    expect(dialogs.map((d) => d.type)).toEqual(['confirm', 'alert']);
    expect(dialogs[1].message).toContain('the daily sync could NOT be set up');
    expect(dialogs[1].message).toContain(enrollError);
    expect(dialogs[1].message).toContain('Sync settings → Re-authorize');
  });
});
