// Scenario 7 — member-facing views across every fixture value-variant: the Table tab must render
// fully-populated, all-null, and empty-list members without crashing; row click opens the person
// detail; the detail shows milestone chips, falls back to flat fields when `details` is null, and
// the notes section reads + writes rest/v1/member_comments.

import { test, expect } from '@playwright/test';
import { openDashboard, AVERY_UUID, BLANK_UUID } from './support';

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
    await expect(page.getByText('Friends', { exact: true })).toBeVisible();
    await expect(page.getByText('Aaronic Priesthood', { exact: true })).toBeVisible();
    // Rich-details sections render.
    await expect(page.getByText('Sacrament Attendance')).toBeVisible();
    // Attendance is the last-8-weeks window (3 fixture records, 2 attended) — never a whole-history
    // "missed of N" count.
    await expect(page.getByText(/Attended\s*2\s*of\s*3/)).toBeVisible();
    await expect(page.getByText('Casey Sample')).toBeVisible(); // friend name from details
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

  test('notes render mocked comments and posting calls rest/v1/member_comments', async ({ page }) => {
    const { supabase } = await openDashboard(page, { path: `/person/${AVERY_UUID}` });

    // The seeded note (from the member_comments fixture) renders with its author.
    await expect(page.getByText('Welcomed at sacrament meeting.')).toBeVisible();
    await expect(page.getByText(/Jamie Clerksample/).first()).toBeVisible();

    // Post a new note.
    const noteBox = page.getByPlaceholder('Add a note…');
    await noteBox.fill('Follow up next week.');
    await page.getByRole('button', { name: 'Post note' }).click();

    // A successful post clears the input (the deterministic "request finished" signal — getByText
    // alone would match the textarea's own value while the POST is still in flight).
    await expect(noteBox).toHaveValue('');
    // Read-after-write: the mock appended the row, the reload renders it as a comment paragraph.
    await expect(page.locator('p', { hasText: 'Follow up next week.' })).toBeVisible();

    const posts = supabase.callsTo('/rest/v1/member_comments').filter((c) => c.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toMatchObject({
      member_person_uuid: AVERY_UUID,
      body: 'Follow up next week.',
      author_email: 'leader@example.test',
    });
  });
});
