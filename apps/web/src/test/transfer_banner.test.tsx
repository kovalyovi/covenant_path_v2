// The Baptisms "next transfer" banner: shows the countdown when a transfer is scheduled ahead, renders
// nothing for a non-leader with no schedule, and offers stake leaders a "Set transfer dates" entry.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { TransferDate } from '../logic/transfers';

let transferDates: TransferDate[] = [];
let viewerIsStakeLeader = false;

vi.mock('../hooks/useDashboard', () => ({
  useDashboard: () => ({
    transferDates,
    enrollStatus: { viewerIsStakeLeader },
    upsertTransferDate: async () => {},
    deleteTransferDate: async () => {},
  }),
}));

import { NextTransferBanner } from '../components/TransferDates';

const SCHEDULE: TransferDate[] = [
  { id: 'a', transfer_id: 't-2026-07-23', transfer_date: '2026-07-23' },
  { id: 'b', transfer_id: 't-2026-09-03', transfer_date: '2026-09-03' },
];

describe('NextTransferBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 6, 20)); // Mon Jul 20 2026
    transferDates = [];
    viewerIsStakeLeader = false;
  });
  afterEach(() => vi.useRealTimers());

  it('shows the countdown to the next upcoming transfer', () => {
    transferDates = SCHEDULE;
    render(<NextTransferBanner />);
    expect(screen.getByText(/Next transfer is/)).toBeTruthy();
    expect(screen.getByText(/in 3 days/)).toBeTruthy();
    expect(screen.getByText(/July 23, 2026/)).toBeTruthy();
  });

  it('renders nothing for a non-leader when no schedule is set', () => {
    const { container } = render(<NextTransferBanner />);
    expect(container.firstChild).toBeNull();
  });

  it('offers a stake leader a way to set the first dates when none exist', () => {
    viewerIsStakeLeader = true;
    render(<NextTransferBanner />);
    expect(screen.getByText(/No transfer dates set yet/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Set transfer dates/ })).toBeTruthy();
  });
});
