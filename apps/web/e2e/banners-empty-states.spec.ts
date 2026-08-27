// Scenario 6 — dashboard banners + empty states:
//   • StaleBanner variants (revoked / stale-non-provider "take it over") and their re-enroll action
//   • the live SyncingBanner with the elapsed counter (driven by stakes.sync_state = 'running')
//   • EmptyState variants: no-role-but-known-stake / no credential / first sync running

import { test, expect } from '@playwright/test';
import { openDashboard, enrollmentStatus, stakeRow, STAKE_NAME } from './support';

test.describe('banners', () => {
  test('a revoked credential shows the paused banner and Re-enroll opens the ReauthDialog', async ({ page }) => {
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': { json: enrollmentStatus({}, { state: 'revoked', is_provider: false }) },
      },
    });

    const banner = page.getByRole('status').filter({ hasText: 'Sync paused' });
    await expect(banner).toContainText('Sync paused — credential revoked. Re-enroll to resume daily updates.');

    await banner.getByRole('button', { name: 'Re-enroll' }).click();
    await expect(page.getByRole('dialog', { name: 'Re-authorize daily sync' })).toBeVisible();
    await expect(page).toHaveURL(/\/baptisms$/); // in-app modal, not a login bounce
  });

  test('a stale NON-provider credential offers to take the sync over', async ({ page }) => {
    await openDashboard(page, {
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus({}, { state: 'stale', is_provider: false, last_error: 'session expired' }),
        },
      },
    });

    const banner = page.getByRole('status').filter({ hasText: 'daily sync has failed' });
    await expect(banner).toContainText('The leader who set it up needs to re-authorize');
    await expect(banner).toContainText('take it over');
    await expect(banner.getByRole('button', { name: 'Authorize on my account' })).toBeVisible();
  });

  test('a running sync shows the live banner with an elapsed counter', async ({ page }) => {
    const startedAt = new Date(Date.now() - 90_000).toISOString(); // 1m 30s ago
    await openDashboard(page, {
      supabase: { stakes: [stakeRow({ sync_state: 'running', sync_started_at: startedAt })] },
    });

    const banner = page.getByRole('status').filter({ hasText: 'Syncing your stake from LCR' });
    await expect(banner).toContainText('fresh data in a few minutes');
    await expect(banner).toContainText(/\b1m \d+s elapsed/);
  });
});

test.describe('empty states', () => {
  test('no role in a KNOWN stake explains access ended — not a setup prompt', async ({ page }) => {
    await openDashboard(page, {
      supabase: { stakes: [], members: [], comments: [] },
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus(
            { status: 'no_role', member_count: 42, has_data: true },
            { state: 'active', is_provider: false },
          ),
        },
      },
    });

    await expect(page.getByRole('heading', { name: 'No access with your current calling' })).toBeVisible();
    await expect(page.getByText(`${STAKE_NAME} is synced with Covenant Path`)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Authorize stake sync' })).not.toBeVisible();
  });

  test('an unlinked sign-in (no role, no stake) offers BOTH paths in: invite or Church login', async ({ page }) => {
    // The pure email-code viewer whose address was never bound to a role — RLS returns nothing and the
    // broker can't name a stake. Don't show a blank dashboard or a misleading "wrong email" line: name
    // the two true ways in (a leader invites them, OR one Church login binds their calling), and keep
    // the Church-account action for a leader (also opens the dialog).
    await openDashboard(page, {
      supabase: { stakes: [], members: [], comments: [] },
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus(
            { status: 'no_role', stake_name: null, unit_number: null, member_count: 0, has_data: false },
            { state: 'none', complete: false, principal_name: null },
          ),
        },
      },
    });

    await expect(page.getByRole('heading', { name: 'Link your stake access' })).toBeVisible();
    await expect(page.getByText(/ask a stake leader to invite you/i)).toBeVisible();
    await expect(page.getByText(/sign in with your Church account/i)).toBeVisible();
    const cta = page.getByRole('button', { name: 'Sign in with Church account' });
    await expect(cta).toBeVisible();

    await cta.click();
    await expect(page.getByRole('dialog', { name: 'Re-authorize daily sync' })).toBeVisible();
  });

  test('a scope-less leader can claim access; the link goes to the address ON RECORD', async ({ page }) => {
    // Item 1b (0065). A leader signed in with a different address gets a self-service route in. The
    // copy must be explicit that the confirmation goes to the address already on record — that is the
    // security property, and hiding it would make the flow feel like a dead end.
    await openDashboard(page, {
      supabase: { stakes: [], members: [], comments: [] },
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus(
            { status: 'no_role', stake_name: null, unit_number: null, member_count: 0, has_data: false },
            { state: 'none', complete: false, principal_name: null },
          ),
        },
        'POST /claim/start': { json: { status: 'sent', hint: 're•••••@g•••.com' } },
      },
    });

    await page.getByRole('button', { name: /did I sign in with a different email/i }).click();
    const send = page.getByRole('button', { name: 'Send confirmation link' });
    await expect(send).toBeDisabled();                       // gated until both names are real
    await page.getByPlaceholder('First name').fill('Reed');
    await page.getByPlaceholder('Last name').fill('Hunsaker');
    await expect(send).toBeEnabled();
    await send.click();

    await expect(page.getByText(/address on record/i)).toBeVisible();
    await expect(page.getByText('re•••••@g•••.com')).toBeVisible();
  });

  test('an unmatched claim never confirms whether that leader exists', async ({ page }) => {
    await openDashboard(page, {
      supabase: { stakes: [], members: [], comments: [] },
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus(
            { status: 'no_role', stake_name: null, unit_number: null, member_count: 0, has_data: false },
            { state: 'none', complete: false, principal_name: null },
          ),
        },
        'POST /claim/start': { json: { status: 'no_match' } },
      },
    });

    await page.getByRole('button', { name: /did I sign in with a different email/i }).click();
    await page.getByPlaceholder('First name').fill('Nosuch');
    await page.getByPlaceholder('Last name').fill('Person');
    await page.getByRole('button', { name: 'Send confirmation link' }).click();

    await expect(page.getByText(/couldn.t match that name/i)).toBeVisible();
    // Nothing about whether the name exists, and no masked address to probe with.
    await expect(page.getByText(/•••/)).not.toBeVisible();
  });

  test('an active credential with no data yet shows the first-sync-running state', async ({ page }) => {
    await openDashboard(page, {
      supabase: { stakes: [], members: [], comments: [] },
      broker: {
        'GET /auth/enrollment-status': {
          json: enrollmentStatus(
            { member_count: 0, has_data: false, last_synced_at: null },
            { state: 'active', is_provider: true },
          ),
        },
      },
    });

    await expect(page.getByRole('heading', { name: 'Setting up your stake…' })).toBeVisible();
    await expect(page.getByText('the first sync is running')).toBeVisible();
  });
});
