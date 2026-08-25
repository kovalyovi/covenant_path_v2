// FULLSTACK lane (Phase B, live): real browser → real web app → REAL auth broker → mock LCR/Okta
// → the dedicated TEST Supabase project. NO page.route() mocks — session minting, the enroll RPC,
// login_audit and RLS are actual Postgres. Personas come from tests/mock_lcr (their auth/me emails
// equal the seeded rls.* accounts; see tests/seed.py). Run:
//   E2E_FULLSTACK=1 npx playwright test --project=fullstack
// playwright.config.ts boots the whole stack (python -m tests.fullstack_stack + vite) itself.

import { test, expect, type Page } from '@playwright/test';
import { submitChurchLogin, pickMenuItem, expectOnDashboard } from '../support';
import { deleteTestCredential, latestAudit, svcDelete, svcRows, testCredential } from './env';

// Stateful lane (one shared test project + one credential slot) — run in order, one at a time.
test.describe.configure({ mode: 'serial' });

const WARD1_MEMBERS = ['Avery Example', 'Finley Mocksen', 'Harper Testworth'];
const WARD2_MEMBERS = ['Jordan Fakely', 'Kit Specimen'];
const NOTE_MARKER = 'fullstack-e2e: follow up with the Examples';

/** Auto-answer native dialogs: the post-login enroll offer is a window.confirm; a failed
 *  consented enroll is a window.alert. Collect messages so failures are diagnosable. */
function answerDialogs(page: Page, acceptConfirm: boolean): string[] {
  const seen: string[] = [];
  page.on('dialog', (d) => {
    seen.push(`${d.type()}: ${d.message()}`);
    if (d.type() === 'confirm') void (acceptConfirm ? d.accept() : d.dismiss());
    else void d.accept();
  });
  return seen;
}

test.beforeAll(async () => {
  await deleteTestCredential(); // deterministic enroll offers
  await svcDelete(`member_comments?body=like.${encodeURIComponent('fullstack-e2e:%')}`);
  await svcDelete(`member_notes?note=like.${encodeURIComponent('fullstack-e2e:%')}`);
});

test.afterAll(async () => {
  await deleteTestCredential();
  await svcDelete(`member_comments?body=like.${encodeURIComponent('fullstack-e2e:%')}`);
  await svcDelete(`member_notes?note=like.${encodeURIComponent('fullstack-e2e:%')}`);
});

test('stake president signs in through the real broker and sees ALL seeded members (live RLS)', async ({ page }) => {
  answerDialogs(page, false); // decline the "set up daily sync?" offer
  await page.goto('/login');
  await submitChurchLogin(page, 'president.complete', 'pw-president');
  await expectOnDashboard(page);

  await page.goto('/table');
  for (const name of [...WARD1_MEMBERS, ...WARD2_MEMBERS]) {
    await expect(page.getByText(name)).toBeVisible();
  }

  // The broker audited the login in the REAL login_audit table.
  await expect
    .poll(async () => (await latestAudit('rls.president@example.org'))?.authorized ?? null, {
      timeout: 15_000,
    })
    .toBe('allowed');
});

test('ward leader sees ONLY their ward (live RLS scoping)', async ({ page }) => {
  answerDialogs(page, false);
  await page.goto('/login');
  await submitChurchLogin(page, 'wardleader.partial', 'pw-ward');
  await expectOnDashboard(page);

  await page.goto('/table');
  for (const name of WARD1_MEMBERS) await expect(page.getByText(name)).toBeVisible();
  for (const name of WARD2_MEMBERS) await expect(page.getByText(name)).toHaveCount(0);
});

test('a no-calling member is blocked at login with the no-access message', async ({ page }) => {
  answerDialogs(page, false);
  await page.goto('/login');
  await submitChurchLogin(page, 'member.nocalling', 'pw-member');

  await expect(page.getByRole('alert')).toContainText("doesn't have access to Covenant Path");
  await expect(page).toHaveURL(/\/login$/);

  await expect
    .poll(async () => (await latestAudit('rls.norole@example.org'))?.authorized ?? null, {
      timeout: 15_000,
    })
    .toBe('blocked');
});

test('enroll → revoke → re-enroll, end to end in the browser against real Postgres', async ({ page }) => {
  test.setTimeout(180_000); // three Church sign-ins + an access-scrape eval each

  // 1. Sign in and ACCEPT the enroll offer → the broker stores a real credential row.
  const dialogs = answerDialogs(page, true);
  await page.goto('/login');
  await submitChurchLogin(page, 'president.complete', 'pw-president');
  await expectOnDashboard(page);
  expect(dialogs.join('\n')).toContain('confirm:'); // the offer actually appeared

  await expect
    .poll(async () => (await testCredential())?.revoked ?? null, { timeout: 30_000 })
    .toBe(false);

  // 2. Sync settings shows the ACTIVE provider state; revoke from the UI.
  await pickMenuItem(page, 'Sync settings');
  await expect(page.getByText('Active', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Revoke my sync access' }).click();
  const confirm = page.getByRole('dialog', { name: 'Revoke sync access?' });
  await expect(confirm).toBeVisible();
  await confirm.getByRole('button', { name: /^Revoke/ }).click();

  await expect
    .poll(async () => (await testCredential())?.revoked ?? null, { timeout: 20_000 })
    .toBe(true);

  // 3. The revoked banner offers Re-enroll → the in-app ReauthDialog (never the login screen).
  const banner = page.getByText('Sync paused — credential revoked', { exact: false });
  await expect(banner).toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: 'Re-enroll' }).click();
  const reauth = page.getByRole('dialog', { name: 'Re-authorize daily sync' });
  await expect(reauth).toBeVisible();
  await reauth.getByLabel('Church username').fill('president.complete');
  await reauth.getByLabel('Password', { exact: true }).fill('pw-president');
  await reauth.getByRole('button', { name: 'Authorize', exact: true }).click();

  // The 2026-06-10 regression loop, closed: the row is un-revoked by the real RPC.
  await expect(page.getByText('Daily sync authorized', { exact: false })).toBeVisible({
    timeout: 60_000,
  });
  await expect
    .poll(async () => (await testCredential())?.revoked ?? null, { timeout: 20_000 })
    .toBe(false);
  await expect(page).not.toHaveURL(/\/login/);
});

test('note round-trip lands in the real member_comments thread', async ({ page }) => {
  answerDialogs(page, false);
  await page.goto('/login');
  await submitChurchLogin(page, 'president.complete', 'pw-president');
  await expectOnDashboard(page);

  await page.goto('/table');
  await page.getByText('Avery Example').first().click();

  // Notes are a THREAD (migration 0054): the add box is always present — type into it and press
  // "Add note". Each entry is a member_comments row, not the single member_notes field.
  const noteBox = page.getByPlaceholder('Add a note…');
  await expect(noteBox).toBeVisible({ timeout: 20_000 });
  await noteBox.fill(NOTE_MARKER);
  await page.getByRole('button', { name: 'Add note', exact: true }).click();

  // Read-after-write: the entry renders in the thread and the add box clears for the next one.
  await expect(page.getByText(NOTE_MARKER)).toBeVisible({ timeout: 20_000 });
  await expect(noteBox).toHaveValue('');

  // It landed in the REAL member_comments thread, attributed to the signed-in leader.
  const rows = await svcRows<{ body: string; author_email: string }>(
    `member_comments?select=body,author_email&body=like.${encodeURIComponent('fullstack-e2e:%')}`,
  );
  expect(rows.length).toBe(1);
  expect(rows[0].author_email).toBe('rls.president@example.org');
});
