// Regression for the Baptisms by-unit double-show (2026-06-18): in the by-unit grouping each unit
// SectionCard shows its missionaries once at the top (UnitMissionaryStrip), so the per-person card must
// NOT also render its own "Missionaries" section. The by-date view (nested=false) keeps the per-person
// strip. We assert the per-card "Missionaries" heading is present by default and absent when nested.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// BaptismPersonCard pulls in useDashboard (notes + missionaries) → supabase; stub the edges so the
// pure card renders without a real Supabase client (same pattern as the other component tests).
vi.mock('../lib/supabase', () => ({ supabase: {}, currentAccessToken: async () => 'token' }));
vi.mock('../hooks/useDashboard', () => ({ useDashboard: () => ({ missionaries: {}, notes: {} }) }));

import { BaptismPersonCard } from '../pages/tabs/BaptismsTab';
import type { Member } from '../lib/member';

const member = { person_uuid: 'u1', name: 'Jane Doe', unit_name: 'Maple Ward' } as unknown as Member;
const item = { m: member, date: new Date(2030, 0, 1) };

function renderCard(nested: boolean) {
  return render(
    <MemoryRouter>
      <BaptismPersonCard item={item} today={new Date(2029, 0, 1)} overdue={false} nested={nested} />
    </MemoryRouter>,
  );
}

describe('BaptismPersonCard missionary section', () => {
  it('shows the per-person Missionaries section in the by-date view (nested=false)', () => {
    renderCard(false);
    expect(screen.getByText('Missionaries')).toBeInTheDocument();
  });

  it('hides the per-person Missionaries section in the by-unit view (nested=true)', () => {
    renderCard(true);
    expect(screen.queryByText('Missionaries')).toBeNull();
  });
});
