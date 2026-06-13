// Regression for the 2026-06-10 report: "Status says Revoked, but the sheet offers 'Revoke my
// sync access' (and 'Sync now') and no way to re-enroll." The sheet's actions must follow the
// credential STATE: revoked/stale → "Re-authorize daily sync" (no Sync now; Revoke only while
// there's a live credential to revoke), active provider → Sync now + Revoke, none → set-up CTA.

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('../lib/config', () => ({ brokerUrl: 'https://broker.test' }));
vi.mock('../lib/supabase', () => ({ currentAccessToken: async () => 'token' }));

import { SyncSettingsSheet } from '../components/SyncSettingsSheet';
import { ToastProvider } from '../components/Toast';
import { broker, type CredentialInfo, type EnrollmentStatus } from '../lib/broker';

// The schedule + Drive subsections fetch on mount; pin them to "not eligible" so the test renders
// deterministically with no pending promises.
Object.assign(broker, {
  getSchedule: vi.fn().mockResolvedValue({ eligible: false }),
  googleDriveStatus: vi.fn().mockResolvedValue({ eligible: false }),
});

function status(cred: Partial<CredentialInfo>): EnrollmentStatus {
  return {
    stakeName: 'Test Stake',
    stakeId: 'stake-1',
    unitNumber: 503991,
    lastSyncedAt: null,
    memberCount: 42,
    hasData: true,
    patriarchalPending: 0,
    noRole: false,
    credential: {
      state: 'active',
      complete: true,
      isProvider: true,
      principalName: 'Test Leader',
      enrolledAt: null,
      lastError: null,
      ...cred,
    },
  };
}

function renderSheet(s: EnrollmentStatus) {
  const onReauth = vi.fn();
  const onClose = vi.fn();
  render(
    <ToastProvider>
      <SyncSettingsSheet
        open
        onClose={onClose}
        initial={s}
        onLoaded={() => {}}
        onRevoke={() => {}}
        onSyncNow={() => {}}
        onReauth={onReauth}
      />
    </ToastProvider>,
  );
  return { onReauth, onClose };
}

const reauthBtn = () => screen.queryByRole('button', { name: /re-authorize daily sync/i });
const syncNowBtn = () => screen.queryByRole('button', { name: /sync my stake now/i });
const revokeBtn = () => screen.queryByRole('button', { name: /revoke my sync access/i });

describe('SyncSettingsSheet credential states', () => {
  it('revoked: shows Re-authorize, hides Sync now and Revoke', () => {
    const { onReauth, onClose } = renderSheet(status({ state: 'revoked' }));
    expect(screen.getByText('Revoked')).toBeTruthy();
    expect(reauthBtn()).toBeTruthy();
    expect(syncNowBtn()).toBeNull();
    expect(revokeBtn()).toBeNull();
    fireEvent.click(reauthBtn()!);
    expect(onReauth).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('stale: shows Re-authorize + Revoke (still a live credential), hides Sync now', () => {
    renderSheet(status({ state: 'stale', lastError: 'SSO did not complete' }));
    expect(screen.getByText('Needs re-authorization')).toBeTruthy();
    expect(screen.getByText(/SSO did not complete/)).toBeTruthy();
    expect(reauthBtn()).toBeTruthy();
    expect(syncNowBtn()).toBeNull();
    expect(revokeBtn()).toBeTruthy();
  });

  it('active provider: shows Sync now + Revoke, no Re-authorize', () => {
    renderSheet(status({ state: 'active' }));
    expect(screen.getByText('Active')).toBeTruthy();
    expect(reauthBtn()).toBeNull();
    expect(syncNowBtn()).toBeTruthy();
    expect(revokeBtn()).toBeTruthy();
  });

  it('active non-provider: status only, no action buttons', () => {
    renderSheet(status({ state: 'active', isProvider: false }));
    expect(reauthBtn()).toBeNull();
    expect(syncNowBtn()).toBeNull();
    expect(revokeBtn()).toBeNull();
  });

  it('no credential: offers the set-up CTA', () => {
    const { onReauth } = renderSheet(status({ state: 'none', isProvider: false }));
    const setup = screen.getByRole('button', { name: /set up daily sync/i });
    fireEvent.click(setup);
    expect(onReauth).toHaveBeenCalledTimes(1);
  });
});
