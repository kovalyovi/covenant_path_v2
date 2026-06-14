// The Golden Hour completion display (item 4, user-chosen layout): ONE ROW PER ITEM with a status
// icon — ✓ done / ○ not done / ⚠ data issue. N/A items are OMITTED (not eligible). This verifies the
// rendered DOM: N/A rows absent, a ⚠ icon for a data-issue field, and a ✓ for a done one.

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GoldenHourRows } from '../components/GoldenHourRows';
import type { Member } from '../lib/member';

const thisYear = new Date().getFullYear();

function member(over: Partial<Record<string, string>> = {}): Member {
  return {
    friends: 'No', calling: 'No', ministering_brothers_sisters: 'No', ministering_assignment: 'No',
    baptism_date: '1 Jan 2000', temple_recommend: 'No', patriarchal_blessing: 'No',
    living_ordinance: 'No', aaronic_priesthood: 'N/A', melchizedek_priesthood: 'N/A',
    family_name_prepared: 'No', first_temple_visit: 'No', sex: 'F', birth_date: `1 Jan ${thisYear - 30}`,
    ...over,
  };
}

describe('GoldenHourRows rendering', () => {
  it('OMITS N/A milestones (a woman has no priesthood rows)', () => {
    render(<GoldenHourRows member={member({ sex: 'F' })} />);
    expect(screen.queryByText('Aaronic Priesthood')).not.toBeInTheDocument();
    expect(screen.queryByText('Melchizedek Priesthood')).not.toBeInTheDocument();
    // it never renders a literal "N/A" row
    expect(screen.queryByText('N/A')).not.toBeInTheDocument();
  });

  it('shows a ✓ "Done" status for a completed milestone', () => {
    render(<GoldenHourRows member={member({ friends: 'Yes' })} />);
    const row = screen.getByText('Friends').closest('li')!;
    expect(row).toHaveClass('gh-row--done');
    expect(row.textContent).toContain('Done');
  });

  it('shows a ⚠ "Needs data" issue row for a sentinel value (distinct from not-done)', () => {
    render(<GoldenHourRows member={member({ calling: 'needs-profile-api' })} />);
    const row = screen.getByText('Calling').closest('li')!;
    expect(row).toHaveClass('gh-row--issue');
    expect(row.textContent).toContain('Needs data');
    // and the raw sentinel string is never shown
    expect(screen.queryByText(/needs-profile-api/)).not.toBeInTheDocument();
  });

  it('shows ○ "Not yet" for an honest recorded "No"', () => {
    render(<GoldenHourRows member={member({ calling: 'No' })} />);
    const row = screen.getByText('Calling').closest('li')!;
    expect(row).toHaveClass('gh-row--not-done');
    expect(row.textContent).toContain('Not yet');
  });
});
