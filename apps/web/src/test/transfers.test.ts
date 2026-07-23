// Transfer-schedule logic: next upcoming transfer + countdown, and the per-cycle window used to bucket
// baptisms toward a ward goal.

import { describe, it, expect } from 'vitest';
import { nextTransfer, transferWindow, inTransferWindow, type TransferDate } from '../logic/transfers';

const SCHEDULE: TransferDate[] = [
  { transfer_id: 't-2026-06-11', transfer_date: '2026-06-11' },
  { transfer_id: 't-2026-07-23', transfer_date: '2026-07-23' },
  { transfer_id: 't-2026-09-03', transfer_date: '2026-09-03' },
];

describe('nextTransfer', () => {
  it('returns the soonest transfer on/after today with the day count', () => {
    const n = nextTransfer(SCHEDULE, new Date(2026, 6, 20)); // Jul 20
    expect(n?.transfer_id).toBe('t-2026-07-23');
    expect(n?.daysUntil).toBe(3);
  });

  it('is inclusive of today (0 days)', () => {
    const n = nextTransfer(SCHEDULE, new Date(2026, 6, 23)); // Jul 23 exactly
    expect(n?.transfer_id).toBe('t-2026-07-23');
    expect(n?.daysUntil).toBe(0);
  });

  it('skips past transfers and picks the next future one', () => {
    const n = nextTransfer(SCHEDULE, new Date(2026, 6, 24)); // Jul 24
    expect(n?.transfer_id).toBe('t-2026-09-03');
  });

  it('returns null when nothing is scheduled ahead', () => {
    expect(nextTransfer(SCHEDULE, new Date(2026, 11, 1))).toBeNull();
  });

  it('returns null on an empty schedule and ignores unparseable dates', () => {
    expect(nextTransfer([], new Date(2026, 6, 20))).toBeNull();
    expect(nextTransfer([{ transfer_id: 'x', transfer_date: 'N/A' }], new Date(2026, 6, 20))).toBeNull();
  });

  it('does not require the input to be pre-sorted', () => {
    const shuffled = [SCHEDULE[2], SCHEDULE[0], SCHEDULE[1]];
    expect(nextTransfer(shuffled, new Date(2026, 6, 20))?.transfer_id).toBe('t-2026-07-23');
  });
});

describe('transferWindow / inTransferWindow', () => {
  it('spans from the previous transfer to this one', () => {
    const w = transferWindow(SCHEDULE, 't-2026-07-23');
    expect(w?.start?.getTime()).toBe(new Date(2026, 5, 11).getTime());
    expect(w?.end.getTime()).toBe(new Date(2026, 6, 23).getTime());
  });

  it('has an open (null) start for the earliest cycle', () => {
    const w = transferWindow(SCHEDULE, 't-2026-06-11');
    expect(w?.start).toBeNull();
  });

  it('returns null for an unknown transfer id', () => {
    expect(transferWindow(SCHEDULE, 'nope')).toBeNull();
  });

  it('buckets a baptism to the cycle ENDING on/after its date (exclusive prev, inclusive end)', () => {
    const w = transferWindow(SCHEDULE, 't-2026-07-23')!; // (Jun 11, Jul 23]
    expect(inTransferWindow(new Date(2026, 6, 23), w)).toBe(true); // on the end day -> counts
    expect(inTransferWindow(new Date(2026, 6, 1), w)).toBe(true); // mid-cycle
    expect(inTransferWindow(new Date(2026, 5, 11), w)).toBe(false); // on prev transfer -> prior cycle
    expect(inTransferWindow(new Date(2026, 6, 24), w)).toBe(false); // after end
  });
});
