// OTP auto-submit (2026-06-20 ask): a one-time code submits the instant it's complete — whether the
// leader PASTES it (the value jumps to full length) or types the last digit — so they never also have
// to press Verify. Guards: never while a verify is in flight, never twice for the same code.

import { describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { OTP_LENGTH, useOtpAutoSubmit } from '../lib/useOtpAutoSubmit';

function setup(initialCode = '', busy = false) {
  const submit = vi.fn();
  const { rerender } = renderHook(
    ({ code, busy }: { code: string; busy: boolean }) => useOtpAutoSubmit(code, busy, submit),
    { initialProps: { code: initialCode, busy } },
  );
  return { submit, rerender };
}

describe('useOtpAutoSubmit', () => {
  it('OTP length is 6 (Okta MFA + Supabase email)', () => {
    expect(OTP_LENGTH).toBe(6);
  });

  it('submits once the code reaches full length (typed)', () => {
    const { submit, rerender } = setup('12345');
    expect(submit).not.toHaveBeenCalled(); // 5 digits = incomplete
    rerender({ code: '123456', busy: false });
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it('submits on PASTE (value jumps straight to full length)', () => {
    const { submit, rerender } = setup('');
    rerender({ code: '654321', busy: false }); // paste lands the whole code at once
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it('never submits while a verify is in flight (busy)', () => {
    const { submit } = setup('123456', true);
    expect(submit).not.toHaveBeenCalled();
  });

  it('does not double-submit on re-render while the code stays complete', () => {
    const { submit, rerender } = setup('123456');
    expect(submit).toHaveBeenCalledTimes(1);
    rerender({ code: '123456', busy: false }); // an unrelated re-render
    rerender({ code: '123456', busy: true }); // verify started
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it('re-arms after the code is cleared/edited below full length (wrong code retry)', () => {
    const { submit, rerender } = setup('123456');
    expect(submit).toHaveBeenCalledTimes(1);
    rerender({ code: '', busy: false }); // rejected → field cleared
    rerender({ code: '999999', busy: false }); // fresh complete code
    expect(submit).toHaveBeenCalledTimes(2);
  });
});
