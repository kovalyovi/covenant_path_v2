// A15 — the full passkey ceremony against the REAL broker + REAL test Supabase, using
// Playwright/CDP's virtual authenticator (a fake platform authenticator with resident-key +
// user-verification support, so discoverable passwordless login works headlessly):
//   register: Church sign-in → Settings → "Add a passkey" → attestation verified server-side →
//             a row lands in the real webauthn_credentials table.
//   login:    sign out → "Sign in with a passkey" → assertion verified → broker mints a session
//             for the credential's email → the RLS dashboard loads. No password anywhere.
// The broker runs with WEBAUTHN_RP_ID=localhost / WEBAUTHN_ORIGINS=http://localhost:5198
// (tests/fullstack_stack.py) so the ceremony origin checks match the vite dev server.

import { test, expect, type Page } from '@playwright/test';
import { submitChurchLogin, expectOnDashboard } from '../support';
import { svcDelete, svcRows } from './env';

const EMAIL = 'rls.president@example.org';

async function armVirtualAuthenticator(page: Page): Promise<void> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('WebAuthn.enable');
  await cdp.send('WebAuthn.addVirtualAuthenticator', {
    options: {
      protocol: 'ctap2',
      transport: 'internal',
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
}

test.beforeAll(async () => {
  await svcDelete(`webauthn_credentials?email=eq.${encodeURIComponent(EMAIL)}`);
});

test.afterAll(async () => {
  await svcDelete(`webauthn_credentials?email=eq.${encodeURIComponent(EMAIL)}`);
});

test('register a passkey, sign out, sign back in with it — no password (live ceremony)', async ({ page }) => {
  test.setTimeout(120_000);
  await armVirtualAuthenticator(page);
  page.on('dialog', (d) => void (d.type() === 'confirm' ? d.dismiss() : d.accept()));

  // 1. Get a session the normal way, then bind a passkey from Settings.
  await page.goto('/login');
  await submitChurchLogin(page, 'president.complete', 'pw-president');
  await expectOnDashboard(page);
  await page.goto('/settings');
  await page.getByText('Add a passkey').click();
  await expect(page.getByText('Passkey added', { exact: false })).toBeVisible({ timeout: 20_000 });

  // The attestation really landed in the test project.
  const stored = await svcRows(
    `webauthn_credentials?select=email,credential_id&email=eq.${encodeURIComponent(EMAIL)}`,
  );
  expect(stored.length).toBe(1);

  // 2. Sign out → passwordless login with the discoverable credential.
  await page.getByText('Sign out', { exact: true }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 20_000 });
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click();
  await expectOnDashboard(page);

  // It's a REAL session for the credential's email: the RLS-scoped data renders.
  await page.goto('/table');
  await expect(page.getByText('Avery Example')).toBeVisible();
});
