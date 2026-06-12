// Source-naming copy for the MFA code step (2026-06-11): with several methods enrolled, the
// common failure is a right-looking code from the WRONG source — an authenticator-app code typed
// into a text challenge, or an earlier text's code. The prompt names exactly which code belongs
// in the box (the label is Okta's own masked destination, e.g. "+1 XXX-XX34"), the warning heads
// off the authenticator mix-up, and the no-code hint surfaces the stale-number escape hatch.
// Mirrored in Swift (MfaCopy.swift) and Kotlin (MfaCopy.kt) — change all three together.

import type { BrokerFactor } from './broker';

export interface MfaPrompt {
  prompt: string;
  warning?: string;
  noCodeHint?: string;
}

export function mfaPrompt(f: BrokerFactor): MfaPrompt {
  const method = (f.method || '').toLowerCase();
  // Shape B's generic placeholder — we don't know the factor, keep the generic copy.
  if (f.id === 'pending') {
    return { prompt: `A code was just sent via ${f.label}. Wait for the new one to arrive, then enter it here.` };
  }
  if (method === 'sms' || method === 'voice') {
    const channel = method === 'voice' ? 'call' : 'text';
    return {
      prompt: `A new code was just sent via ${f.label}. Enter the 6-digit code from that newest ${channel}.`,
      warning: "Don't enter a code from an authenticator app or an older text here.",
      noCodeHint:
        `No ${channel} after 30 seconds? The number on file may be out of date — update it at ` +
        'churchofjesuschrist.org, or choose a different method.',
    };
  }
  if (method === 'email') {
    return {
      prompt: `A new code was just sent via ${f.label}. Enter the code from the newest email — it can take a minute to arrive.`,
    };
  }
  if (method === 'otp' || method === 'totp') {
    return { prompt: `Enter the current code shown in ${f.label}.` };
  }
  return { prompt: `A code was just sent via ${f.label}. Wait for the new one to arrive, then enter it here.` };
}

// Passwordless (primary-factor) email codes are sent by Church USERNAME: Okta's enumeration
// prevention gives an unknown identifier a realistic phantom flow — select accepted, "code sent",
// nothing ever arrives, every code "invalid" (probe-proven 2026-06-12; it stranded Ken Packer and
// the operator). The org doesn't match the email address, so an email-shaped identifier gets this
// warning instead of a silent dead-end. Mirrored in MfaCopy.swift / MfaCopy.kt.
export function otpUsernameHint(identifier: string): string | null {
  if (!identifier.includes('@')) return null;
  return (
    'That looks like an email address. Codes are sent by Church USERNAME — if it isn\'t also ' +
    'your username, no code will arrive. Use the username you sign in with at churchofjesuschrist.org.'
  );
}
