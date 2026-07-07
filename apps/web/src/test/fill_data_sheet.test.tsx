// Fill-data side sheet (2026-07-06): a ⚠ "not available" cell opens this sheet, which shows the
// per-field missing counts (GET /auth/profile-refresh/status), fills off the stored session when
// it can (POST /auth/profile-refresh → started), routes to the ReauthDialog when it can't
// (needs_reauth), and reloads members exactly once when a running fill completes.

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

vi.mock('../lib/config', () => ({ brokerUrl: 'https://broker.test' }));
vi.mock('../lib/supabase', () => ({ currentAccessToken: async () => 'token', supabase: {} }));

const profileRefreshStatus = vi.fn();
const profileRefreshStart = vi.fn();
vi.mock('../lib/broker', () => ({
  broker: {
    available: true,
    profileRefreshStatus: (...a: unknown[]) => profileRefreshStatus(...a),
    profileRefreshStart: (...a: unknown[]) => profileRefreshStart(...a),
  },
}));

import '../i18n';
import { FillDataSheet } from '../components/FillDataSheet';
import type { EnrollmentStatus } from '../lib/broker';

function enrollStatus(over: Partial<EnrollmentStatus> = {}): EnrollmentStatus {
  return {
    memberCount: 76,
    hasData: true,
    patriarchalPending: 76,
    noRole: false,
    viewerIsStakeLeader: true,
    credential: { state: 'active', complete: true, isProvider: true, canRefreshPatriarchal: true },
    ...over,
  } as EnrollmentStatus;
}

const idleStatus = {
  running: false,
  progress: null,
  members_with_gaps: 59,
  missing: { patriarchal_blessing: 76, calling: 59 },
  can_refresh: true,
  last_refresh: null,
};

afterEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe('FillDataSheet', () => {
  it('a non-stake-leader sees the ask-your-leader explanation and no status call', () => {
    render(
      <FillDataSheet
        open
        onClose={() => {}}
        onReauth={() => {}}
        enrollStatus={enrollStatus({ viewerIsStakeLeader: false })}
        onFilled={() => {}}
      />,
    );
    expect(screen.getByText(/need a stake leader/i)).toBeInTheDocument();
    expect(profileRefreshStatus).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /fill missing data now/i })).toBeNull();
  });

  it('a stake leader sees the per-field missing counts and the fill action', async () => {
    profileRefreshStatus.mockResolvedValue(idleStatus);
    render(
      <FillDataSheet open onClose={() => {}} onReauth={() => {}} enrollStatus={enrollStatus()} onFilled={() => {}} />,
    );
    expect(await screen.findByText('Patriarchal blessing')).toBeInTheDocument();
    expect(screen.getByText('76')).toBeInTheDocument();
    expect(screen.getByText('Calling')).toBeInTheDocument();
    expect(screen.getByText('59')).toBeInTheDocument();
    expect(screen.getByText(/members with at least one missing field: 59/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /fill missing data now/i })).toBeEnabled();
  });

  it('needs_reauth routes to the re-auth dialog', async () => {
    profileRefreshStatus.mockResolvedValue(idleStatus);
    profileRefreshStart.mockResolvedValue({ status: 'needs_reauth', reason: 'session_expired' });
    const onReauth = vi.fn();
    render(
      <FillDataSheet open onClose={() => {}} onReauth={onReauth} enrollStatus={enrollStatus()} onFilled={() => {}} />,
    );
    fireEvent.click(await screen.findByRole('button', { name: /fill missing data now/i }));
    expect(await screen.findByText(/session has expired/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /re-authorize & fill/i }));
    expect(onReauth).toHaveBeenCalledTimes(1);
  });

  it('a running fill shows progress, and completion reloads members exactly once', async () => {
    vi.useFakeTimers();
    profileRefreshStatus
      .mockResolvedValueOnce({
        ...idleStatus, running: true,
        progress: { state: 'running', total: 59, done: 12, filled: 9 },
      })
      .mockResolvedValue({
        running: false,
        progress: { state: 'done', total: 59, done: 59, filled: 55 },
        members_with_gaps: 4, missing: { patriarchal_blessing: 4 }, can_refresh: true,
        last_refresh: null,
      });
    const onFilled = vi.fn();
    render(
      <FillDataSheet open onClose={() => {}} onReauth={() => {}} enrollStatus={enrollStatus()} onFilled={onFilled} />,
    );
    // initial load: running
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText(/checked 12 of 59 members — 9 updated/i)).toBeInTheDocument();
    // next poll: done → onFilled fired once, done banner shown
    await act(async () => { vi.advanceTimersByTime(2600); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(onFilled).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/done — 55 of 59 members updated/i)).toBeInTheDocument();
    // further polls do NOT re-fire the reload
    await act(async () => { vi.advanceTimersByTime(2600); await Promise.resolve(); });
    await act(async () => { await Promise.resolve(); });
    expect(onFilled).toHaveBeenCalledTimes(1);
  });

  it('the enrolled account lacking profile access shows the no-access explanation, not the button', async () => {
    profileRefreshStatus.mockResolvedValue({ ...idleStatus, can_refresh: false });
    render(
      <FillDataSheet
        open
        onClose={() => {}}
        onReauth={() => {}}
        enrollStatus={enrollStatus({
          credential: {
            state: 'active', complete: false, isProvider: true, canRefreshPatriarchal: false,
          } as EnrollmentStatus['credential'],
        })}
        onFilled={() => {}}
      />,
    );
    expect(await screen.findByText(/doesn’t have access to member profiles/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /fill missing data now/i })).toBeNull();
  });
});
