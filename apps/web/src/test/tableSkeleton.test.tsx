// Glimmer parity (2026-06-21): the Table tab's loading skeleton must be the SAME shape as the real
// table — the `data-table` shell with the real column headers — so data swaps in with no reflow.
// Pre-fix it rendered MemberListSkeleton (avatar rows, no <table>), which then "jumped" into a table.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../lib/supabase', () => ({ supabase: {}, currentAccessToken: async () => 'token' }));
vi.mock('../hooks/useDashboard', () => ({
  useDashboard: () => ({
    loading: true,
    error: null,
    members: [],
    isAdmin: false,
    enrollStatus: null,
    notes: {},
    showNotes: false,
  }),
}));

import { TableTab } from '../pages/tabs/TableTab';

describe('Table tab loading glimmer', () => {
  it('renders the real table shell (data-table + column headers), not an avatar-list skeleton', () => {
    const { container } = render(
      <MemoryRouter>
        <TableTab />
      </MemoryRouter>,
    );
    // The glimmer reuses the real <table class="data-table"> so columns are pre-sized — fails pre-fix.
    expect(container.querySelector('table.data-table')).not.toBeNull();
    // The real column headers are rendered (they need no data), anchoring every column's width.
    expect(screen.getByText('Melchizedek')).toBeInTheDocument();
    expect(screen.getByText('Patriarchal blessing')).toBeInTheDocument();
    // It is a glimmer, not real data — shimmer boxes are present and no member rows exist yet.
    expect(container.querySelector('.skeleton')).not.toBeNull();
  });
});
