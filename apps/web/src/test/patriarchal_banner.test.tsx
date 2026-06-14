// Patriarchal blessing is the ONE covenant-path field absent from the daily Member Tools sync — it
// only refills from the per-member LCR profile read during a sync with a LIVE session (i.e. a re-auth).
// The banner offers the credential provider (whose calling can read it) a one-tap re-authorize, and
// the broker exposes can_refresh_patriarchal + patriarchal_pending to gate it.

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

// dashboard.tsx pulls in NotesSection → useDashboard → supabase; stub the edges (same as the other
// component tests) so importing the pure banner doesn't spin up a real Supabase client.
vi.mock('../lib/config', () => ({ brokerUrl: 'https://broker.test' }));
vi.mock('../lib/supabase', () => ({ currentAccessToken: async () => 'token', supabase: {} }));

import { PatriarchalBanner } from '../components/dashboard';

describe('PatriarchalBanner', () => {
  it('names the count (pluralized) and calls onRefresh when tapped', () => {
    const onRefresh = vi.fn();
    render(<PatriarchalBanner pending={3} onRefresh={onRefresh} />);
    expect(screen.getByText(/3 members are missing profile details/)).toBeInTheDocument();
    expect(screen.getByText(/daily Church sync can’t pull/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('uses the singular for one member', () => {
    render(<PatriarchalBanner pending={1} onRefresh={() => {}} />);
    expect(screen.getByText(/1 member is missing profile details/)).toBeInTheDocument();
  });
});
