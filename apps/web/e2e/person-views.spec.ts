// Scenario 7 — member-facing views across every fixture value-variant: the Table tab must render
// fully-populated, all-null, and empty-list members without crashing; row click opens the person
// detail; the detail shows milestone chips, falls back to flat fields when `details` is null, and
// the notes section reads + writes rest/v1/member_comments.

import { test, expect } from '@playwright/test';
import { openDashboard, AVERY_UUID, BLANK_UUID, JORDAN_UUID, STAKE_ID } from './support';

test.describe('person views', () => {
  test('the table renders every member variant (and excludes investigators)', async ({ page }) => {
    await openDashboard(page, { path: '/table' });

    const table = page.getByRole('table');
    await expect(table).toBeVisible();
    await expect(page.getByText('3 members')).toBeVisible(); // 4 fixtures − 1 investigator
    await expect(table.getByText('Avery Example')).toBeVisible();
    await expect(table.getByText('Riley Example')).toBeVisible();
    await expect(table.getByText('Blank Sample')).toBeVisible(); // the all-null member renders fine
    await expect(table.getByText('Jordan Sample')).not.toBeVisible(); // investigators excluded (N7)
  });

  test('clicking a row opens the person detail with milestone chips', async ({ page }) => {
    await openDashboard(page, { path: '/table' });

    await page.getByRole('table').getByText('Avery Example').click();

    await expect(page).toHaveURL(new RegExp(`/person/${AVERY_UUID}$`));
    await expect(page.getByRole('heading', { name: 'Avery Example' }).first()).toBeVisible();
    await expect(page.getByText('Covenant Path', { exact: true })).toBeVisible();
    // Labeled milestone chips from the shared logic (Friends/Calling/… for an adult male convert).
    // The chips are buttons (each carries a hover/click tooltip explaining the step).
    await expect(page.getByRole('button', { name: /Friends/ }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /Aaronic Priesthood/ }).first()).toBeVisible();
    // Rich-details sections render.
    await expect(page.getByText('Sacrament Attendance')).toBeVisible();
    // Attendance is the last-8-weeks window (3 fixture records, 2 attended) — never a whole-history
    // "missed of N" count.
    await expect(page.getByText(/Attended\s*2\s*of\s*3/)).toBeVisible();
    await expect(page.getByText('Casey Sample')).toBeVisible(); // friend name from details
  });

  test('clicking a Golden Hour chip shows a tooltip explaining the step', async ({ page }) => {
    await openDashboard(page, { path: `/person/${AVERY_UUID}` });

    // The labeled chips are buttons; clicking one pins its explanation tooltip (role=tooltip).
    const friendsChip = page.getByRole('button', { name: /Friends/ }).first();
    await friendsChip.click();
    await expect(page.getByText(/at least one friend in the ward/)).toBeVisible();
  });

  test('principles taught render as bordered dots with a click tooltip', async ({ page }) => {
    await openDashboard(page, { path: `/person/${AVERY_UUID}` });

    await expect(page.getByText('Principles Taught')).toBeVisible();
    await expect(page.getByText('The Restoration')).toBeVisible(); // the lesson label
    // each principle is a bordered circle button; clicking one shows what it is.
    const dot = page.getByRole('button', { name: /The First Vision/ });
    await dot.click();
    await expect(page.getByText(/member was present/)).toBeVisible();
  });

  test('the completion ring reflects eligible-only milestone progress', async ({ page }) => {
    // Riley: 6 applicable milestones (F, C, M, MA, FN, FT), 2 complete (F + M) → 33%.
    await openDashboard(page, { path: '/person/e2e-person-riley' });

    await expect(page.getByLabel('Covenant Path 33 percent complete')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Riley Example' }).first()).toBeVisible();
  });

  test('a member with null details falls back to the flat-field status sections', async ({ page }) => {
    await openDashboard(page, { path: `/person/${BLANK_UUID}` });

    await expect(page.getByRole('heading', { name: 'Blank Sample' }).first()).toBeVisible();
    // StatusSections work from flat fields; with unknown age the endowment gate shows N/A — no crash.
    await expect(page.getByText('Endowment', { exact: true })).toBeVisible();
    await expect(page.getByText('N/A', { exact: true })).toBeVisible();
    // Rich-details-only sections are absent for a null subtree.
    await expect(page.getByText('Attended Sacrament Meeting')).not.toBeVisible();
  });

  test('single note: legacy thread folds in, editing saves to member_notes', async ({ page }) => {
    const { supabase } = await openDashboard(page, { path: `/person/${AVERY_UUID}` });

    // The legacy member_comments thread is FOLDED into the single note (so nothing is lost).
    await expect(page.getByText(/Welcomed at sacrament meeting\./)).toBeVisible();

    // No separate "Edit" button — tap the note surface to edit, replace the text, save.
    await page.getByRole('button', { name: /Edit note/ }).click();
    const noteBox = page.getByPlaceholder('Write a note about this member…');
    await noteBox.fill('One consolidated note.');
    await page.getByRole('button', { name: 'Save' }).click();

    // Read-after-write: the saved single note renders in full.
    await expect(page.getByText('One consolidated note.')).toBeVisible();

    // It was upserted to member_notes (the single-field table), NOT appended to the thread.
    await expect.poll(() =>
      supabase.callsTo('/rest/v1/member_notes').filter((c) => c.method === 'POST').length,
    ).toBe(1);
    const posts = supabase.callsTo('/rest/v1/member_notes').filter((c) => c.method === 'POST');
    expect(posts[0].body).toMatchObject({
      member_person_uuid: AVERY_UUID,
      note: 'One consolidated note.',
    });
  });

  test('long-press a member row opens the note straight into edit', async ({ page }) => {
    await openDashboard(page, { path: '/golden-hour' });

    // A long-press (pointer held ~600ms) on a member row fires the edit path on the press timer and
    // navigates to the detail with the note open — the row unmounts, so no pointerup is needed.
    const row = page.locator('.member-row', { hasText: 'Avery Example' }).first();
    await expect(row).toBeVisible();
    await row.dispatchEvent('pointerdown');

    await expect(page).toHaveURL(/editNote=1/);
    await expect(page.getByPlaceholder('Write a note about this member…')).toBeVisible();
  });
});

test.describe('manual members (item 11)', () => {
  test('add a person being taught, then it appears in the Being Taught view', async ({ page }) => {
    const { supabase } = await openDashboard(page, { path: '/golden-hour' });

    // Switch to the Being Taught section, open the add dialog, fill, save.
    await page.getByRole('button', { name: /Being Taught/ }).first().click();
    await page.getByRole('button', { name: 'Add a person being taught' }).click();
    await page.getByPlaceholder('Given Surname').fill('Pat Newcomer');
    await page.getByPlaceholder(/want to remember/).fill('Met at a service project.');
    await page.getByRole('button', { name: 'Add', exact: true }).click();

    // It was inserted into manual_members and renders as a card.
    await expect.poll(() =>
      supabase.callsTo('/rest/v1/manual_members').filter((c) => c.method === 'POST').length,
    ).toBe(1);
    await expect(page.getByText('Pat Newcomer', { exact: true })).toBeVisible();
  });

  test('a manual member matching a synced record offers Merge (notes preserved)', async ({ page }) => {
    // A manual member with the SAME name as the synced investigator "Jordan Sample" in the same unit.
    const { supabase } = await openDashboard(page, {
      path: '/golden-hour',
      supabase: {
        manualMembers: [{
          id: 'mm-jordan', stake_id: STAKE_ID, unit_name: 'Testvale 2nd Ward',
          name: 'Sample, Jordan', custom_notes: 'Loves family history.', merged_at: null,
        }],
      },
    });

    await page.getByRole('button', { name: /Being Taught/ }).first().click();
    // The suggestion + Merge button appear because the names match within the unit.
    await expect(page.getByText(/matching record arrived/)).toBeVisible();
    await page.getByRole('button', { name: 'Merge', exact: true }).click();

    // Merge: the manual row is marked merged (PATCH) AND the preserved note is upserted to the real
    // member's single note (member_notes POST keyed to Jordan's uuid).
    await expect.poll(() =>
      supabase.callsTo('/rest/v1/manual_members').filter((c) => c.method === 'PATCH').length,
    ).toBe(1);
    const noteUpserts = supabase.callsTo('/rest/v1/member_notes').filter((c) => c.method === 'POST');
    expect(noteUpserts.length).toBe(1);
    expect(noteUpserts[0].body).toMatchObject({
      member_person_uuid: JORDAN_UUID,
      note: 'Loves family history.',
    });
  });
});
