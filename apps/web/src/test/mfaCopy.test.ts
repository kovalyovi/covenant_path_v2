// Source-naming MFA copy (2026-06-11): the prompt must say WHICH code belongs in the box —
// a right-looking code from the wrong source (authenticator app vs fresh text) was the
// failure that locked a stake leader out twice. Mirrored logic in Swift/Kotlin.

import { describe, expect, it } from 'vitest';
import { mfaPrompt, otpUsernameHint } from '../lib/mfaCopy';

describe('mfaPrompt', () => {
  it('names the text source, warns off authenticator codes, and offers the stale-number hint', () => {
    const tips = mfaPrompt({ id: 'f1', label: 'Text message to •••1234', method: 'sms' });
    expect(tips.prompt).toContain('A new code was just sent via Text message to •••1234');
    expect(tips.prompt).toContain('newest text');
    expect(tips.warning).toContain('authenticator app');
    expect(tips.noCodeHint).toContain('churchofjesuschrist.org');
  });

  it('voice variant says call, not text', () => {
    const tips = mfaPrompt({ id: 'f1', label: 'Phone', method: 'voice' });
    expect(tips.prompt).toContain('newest call');
    expect(tips.noCodeHint).toContain('No call after 30 seconds?');
  });

  it('email factor points at the newest email and allows for delivery delay', () => {
    const tips = mfaPrompt({ id: 'f2', label: 'Email', method: 'email' });
    expect(tips.prompt).toContain('newest email');
    expect(tips.warning).toBeUndefined();
  });

  it('authenticator factor asks for the code currently showing', () => {
    const tips = mfaPrompt({ id: 'f3', label: 'Google Authenticator', method: 'otp' });
    expect(tips.prompt).toBe('Enter the current code shown in Google Authenticator.');
    expect(tips.noCodeHint).toBeUndefined();
  });

  it('password continuation says the code was accepted and asks for the password', () => {
    // 2026-06-12: an MFA-enabled account's emailed code is ACCEPTED, then Okta wants the
    // password — the copy must make clear this is progress, not a rejected code.
    const tips = mfaPrompt({ id: 'pw1', label: 'Password', method: 'password' });
    expect(tips.prompt).toContain('code was accepted');
    expect(tips.prompt).toContain('Church Account password');
    expect(tips.warning).toBeUndefined();
  });

  it("shape B's generic pending factor keeps the generic copy (method otp must not mislead)", () => {
    const tips = mfaPrompt({ id: 'pending', label: 'your verification method', method: 'otp' });
    expect(tips.prompt).toContain('A code was just sent via your verification method');
    expect(tips.warning).toBeUndefined();
  });
});

describe('otpUsernameHint', () => {
  // 2026-06-12 (Ken Packer): Okta only matches the Church USERNAME — an email identifier gets
  // the enumeration-prevention phantom flow and the code never arrives. Email-shaped input
  // must warn; a username must not.
  it('warns when the identifier looks like an email address', () => {
    const hint = otpUsernameHint('leader@example.com');
    expect(hint).toContain('Church USERNAME');
    expect(hint).toContain('churchofjesuschrist.org');
  });

  it('stays quiet for a plain username (and while empty)', () => {
    expect(otpUsernameHint('leader.example')).toBeNull();
    expect(otpUsernameHint('')).toBeNull();
  });
});
