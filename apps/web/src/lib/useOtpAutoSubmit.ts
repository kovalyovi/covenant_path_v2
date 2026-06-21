import { useEffect, useRef } from 'react';

/** Every one-time code we accept is 6 digits — Okta MFA (SMS/email/authenticator) AND the Supabase
 *  email sign-in code. So "is the code complete?" is simply "are there 6 digits?". */
export const OTP_LENGTH = 6;

/**
 * Auto-submit a one-time code the moment it's complete — covering BOTH:
 *   • PASTE — pasting into the field fires onChange, so the value jumps straight to full length here, and
 *   • typing the final digit.
 * so the leader never has to also reach for "Verify". Guards: never fires while a verify is in flight
 * (`busy`), and never fires twice for the same completed code (the `fired` ref, reset whenever the field
 * drops below full length — e.g. after a wrong code is cleared, or the user edits a digit).
 *
 * `code` MUST be the digit-only value (callers sanitize on input), so `code.length === OTP_LENGTH` is an
 * exact completeness test.
 */
export function useOtpAutoSubmit(code: string, busy: boolean, submit: () => void): void {
  const fired = useRef(false);
  useEffect(() => {
    if (code.length !== OTP_LENGTH) {
      fired.current = false; // back below full length → re-arm for the next complete code
      return;
    }
    if (busy || fired.current) return;
    fired.current = true;
    submit();
  }, [code, busy, submit]);
}
