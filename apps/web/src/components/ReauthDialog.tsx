// In-app Church re-authorization (feedback: "hit re-authorize and was pushed back to the login
// screen — should be an extra modal"). Opens over the dashboard, runs the Church sign-in WITH sync
// consent (enroll=true, MFA-aware), and keeps the user in the app: on success the broker stores the
// fresh credential (0038 refresh rules) and we just reload enrollment status + toast. Used by the
// stale/revoked banner, the EmptyState set-up-sync CTA, and Sync settings.

import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { broker, BrokerError, mfaRequired, type BrokerFactor, type BrokerResult } from '../lib/broker';
import { mfaPrompt, otpUsernameHint } from '../lib/mfaCopy';
import { kNoAccessMessage } from '../lib/disclaimer';
import { useDashboard } from '../hooks/useDashboard';
import { useToast } from './Toast';
import { Modal } from './Modal';
import { Button, Segmented } from './ui';

type ReauthMode = 'password' | 'otp';

export function ReauthDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const d = useDashboard();
  const toast = useToast();
  const [mode, setMode] = useState<ReauthMode>('password');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [loginId, setLoginId] = useState<string | null>(null);
  const [factors, setFactors] = useState<BrokerFactor[]>([]);
  const [factorSent, setFactorSent] = useState<BrokerFactor | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [otpSent, setOtpSent] = useState(false);
  // Broker advisory after a send burst: Okta quietly pauses email delivery (2026-06-12).
  const [throttleHint, setThrottleHint] = useState<string | null>(null);
  // Same MFA-input hygiene as LoginPage (2026-06-11): codes never survive a factor switch or a
  // failed verify, and resend cools down so the member waits for the FRESH code.
  const [resendIn, setResendIn] = useState(0);
  useEffect(() => {
    if (resendIn <= 0) return;
    const t = window.setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => window.clearTimeout(t);
  }, [resendIn]);

  function resetAll() {
    setLoginId(null);
    setFactors([]);
    setFactorSent(null);
    setMfaCode('');
    setOtpCode('');
    setOtpSent(false);
    setThrottleHint(null);
    setResendIn(0);
    setError(null);
    setStatus(null);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    const stage = window.setTimeout(
      () => setStatus('Authorizing — checking what your calling can access (up to a minute)…'),
      5000,
    );
    try {
      await action();
    } catch (e) {
      setError(e instanceof BrokerError || e instanceof Error ? e.message : String(e));
    } finally {
      window.clearTimeout(stage);
      setStatus(null);
      setBusy(false);
    }
  }

  async function finish(r: BrokerResult) {
    if (r.authorized === false) {
      setError(kNoAccessMessage);
      return;
    }
    // Adopt the freshly-minted session (same user — keeps them signed in, never the login screen).
    if (r.email && r.otp) {
      await supabase.auth.verifyOtp({ email: r.email, token: r.otp, type: 'email' });
    }
    // The whole point of this dialog is storing the credential (enroll=true). If the broker's eval
    // failed (e.g. LCR outage — the 2026-06-10 "couldn't do sync for his stake" report), nothing was
    // stored: say so and keep the dialog open instead of toasting a success that didn't happen.
    if (!r.stored) {
      setError(
        'Your sign-in worked, but the daily sync could not be set up' +
          (r.enrollError ? ` — ${r.enrollError}` : '.') +
          ' Please try again (Sync settings → Re-authorize).',
      );
      return;
    }
    toast.show({ message: 'Daily sync authorized — your stake will refresh within minutes.' });
    void d.reloadEnrollStatus();
    resetAll();
    setUsername('');
    setPassword('');
    onClose();
  }

  // Enter (or re-enter) the MFA factor step — used by the password lane AND by the passwordless
  // lane's continuation: an MFA-enabled account's emailed code is ACCEPTED and Okta then demands
  // a DISTINCT factor (for Church accounts that's the password — 2026-06-12, the operator's own
  // account after enabling MFA: every correct code read as "couldn't verify").
  async function enterMfa(r: BrokerResult) {
    setOtpSent(false);
    setOtpCode('');
    setLoginId(r.loginId ?? null);
    setFactors(r.factors);
    setFactorSent(null);
    setMfaCode('');
    if (r.factors.length === 1 && r.loginId) {
      await broker.selectFactor(r.loginId, r.factors[0].id);
      setFactorSent(r.factors[0]);
      setResendIn(30);
    }
  }

  const signIn = () =>
    run(async () => {
      const r = await broker.password(username.trim(), password, true); // enroll=true: this IS the consent
      if (mfaRequired(r)) {
        await enterMfa(r);
        return;
      }
      await finish(r);
    });

  const startOtp = () =>
    run(async () => {
      const body = await broker.otpStart(email.trim(), true); // enroll=true
      setThrottleHint(typeof body['throttle_hint'] === 'string' ? (body['throttle_hint'] as string) : null);
      setOtpSent(true);
      setOtpCode('');
      setResendIn(30);
    });

  const verifyOtp = () =>
    run(async () => {
      try {
        const r = await broker.otpVerify(email.trim(), otpCode.trim(), true);
        if (mfaRequired(r)) {
          await enterMfa(r); // code ACCEPTED — the account's MFA owes one more factor
          return;
        }
        await finish(r);
      } catch (e) {
        setOtpCode(''); // a rejected code must be retyped fresh
        throw e;
      }
    });

  const pickFactor = (f: BrokerFactor) =>
    run(async () => {
      await broker.selectFactor(loginId!, f.id);
      setFactorSent(f);
      setMfaCode('');
      setResendIn(30);
    });

  const verify = () =>
    run(async () => {
      try {
        const r = await broker.verifyMfa(loginId!, mfaCode.trim(), true);
        if (mfaRequired(r)) {
          await enterMfa(r); // chained continuation (rare): yet another factor owed
          return;
        }
        await finish(r);
      } catch (e) {
        setMfaCode(''); // a rejected code must be retyped fresh
        throw e;
      }
    });

  return (
    <Modal
      open={open}
      onClose={() => {
        if (!busy) {
          resetAll();
          onClose();
        }
      }}
      title="Re-authorize daily sync"
      hideClose
      bodyClassName="form-stack"
      actions={
        <>
          <Button onClick={() => { resetAll(); onClose(); }} disabled={busy}>
            Cancel
          </Button>
          {otpSent ? (
            <Button variant="filled" onClick={verifyOtp} disabled={busy || otpCode.length < 6} loading={busy}>
              Verify & authorize
            </Button>
          ) : factorSent ? (
            <Button
              variant="filled"
              onClick={verify}
              // A password isn't a 6-digit code — gate it on non-empty only.
              disabled={busy || (factorSent.method === 'password' ? mfaCode.length === 0 : mfaCode.length < 6)}
              loading={busy}
            >
              Verify & authorize
            </Button>
          ) : loginId == null && mode === 'password' ? (
            <Button variant="filled" onClick={signIn} disabled={busy || !username.trim() || !password} loading={busy}>
              Authorize
            </Button>
          ) : loginId == null && mode === 'otp' ? (
            <Button variant="filled" onClick={startOtp} disabled={busy || !email.trim()} loading={busy}>
              Send code
            </Button>
          ) : null}
        </>
      }
    >
      {otpSent ? (
        <>
          <p>A code was sent to the email address on your Church Account. Enter it here.</p>
          {otpUsernameHint(email) && (
            <p className="tiny" style={{ color: 'var(--primary)' }}>{otpUsernameHint(email)}</p>
          )}
          {throttleHint && (
            <p className="tiny" style={{ color: 'var(--primary)' }}>{throttleHint}</p>
          )}
          <label className="field">
            <span>Verification code</span>
            <input
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
            />
          </label>
          <Button
            onClick={startOtp}
            disabled={busy || resendIn > 0}
            type="button"
          >
            {resendIn > 0 ? `Send a new code (${resendIn}s)` : 'Send a new code'}
          </Button>
          <Button
            onClick={() => { setOtpSent(false); setOtpCode(''); setResendIn(0); }}
            disabled={busy}
            type="button"
          >
            Use a different username
          </Button>
        </>
      ) : factorSent ? (
        <>
          <p>{mfaPrompt(factorSent).prompt}</p>
          {mfaPrompt(factorSent).warning && (
            <p className="tiny" style={{ color: 'var(--primary)' }}>
              {mfaPrompt(factorSent).warning}
            </p>
          )}
          {factorSent.method === 'password' ? (
            /* Passwordless-lane MFA continuation: the next factor is the PASSWORD (a distinct
               factor type from the emailed code) — a digits-only code box can't take it. */
            <label className="field">
              <span>Password</span>
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
              />
            </label>
          ) : (
            <label className="field">
              <span>Verification code</span>
              <input
                className="input"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
              />
            </label>
          )}
          {factorSent.method !== 'password' && (
            <Button
              onClick={() => pickFactor(factorSent)}
              disabled={busy || resendIn > 0}
              type="button"
            >
              {resendIn > 0 ? `Send a new code (${resendIn}s)` : 'Send a new code'}
            </Button>
          )}
          {mfaPrompt(factorSent).noCodeHint && <p className="tiny">{mfaPrompt(factorSent).noCodeHint}</p>}
          <Button onClick={() => { setFactorSent(null); setMfaCode(''); }} disabled={busy} type="button">
            Choose a different method
          </Button>
        </>
      ) : loginId != null ? (
        <>
          <p>Choose how to receive your verification code:</p>
          {factors.map((f) => (
            <Button key={f.id} variant="outlined" onClick={() => pickFactor(f)} disabled={busy} type="button">
              {f.label}
            </Button>
          ))}
        </>
      ) : (
        <>
          <p className="small">
            Sign in with your Church account (same as LCR) to re-authorize the daily sync. The session
            is stored encrypted — never your password — and is revocable anytime.
          </p>
          <div>
            <Segmented<ReauthMode>
              ariaLabel="Sign-in method"
              value={mode}
              onChange={setMode}
              disabled={busy}
              options={[
                { label: 'Church username', value: 'password' },
                { label: 'Email code', value: 'otp' },
              ]}
            />
          </div>
          {mode === 'password' ? (
            <>
              <label className="field">
                <span>Church username</span>
                <input
                  className="input"
                  name="church-username"
                  autoComplete="username"
                  autoCapitalize="none"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </label>
              <label className="field">
                <span>Password</span>
                <input
                  className="input"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !busy && username.trim() && password) signIn();
                  }}
                />
              </label>
            </>
          ) : (
            <>
              <label className="field">
                <span>Church username</span>
                {/* The identifier Okta matches is the USERNAME, not the email address: an unknown
                    identifier gets Okta's enumeration-prevention phantom flow — "code sent", nothing
                    arrives, every code "invalid" (probe-proven 2026-06-12; this field was labeled
                    "Church email" and stranded Ken Packer + the operator). Username autofill is
                    therefore CORRECT here — the saved LCR username is exactly what belongs in it. */}
                <input
                  className="input"
                  name="church-username"
                  autoComplete="username"
                  autoCapitalize="none"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !busy && email.trim()) startOtp();
                  }}
                />
              </label>
              <p className="tiny">
                We email a 6-digit code to the address on your Church Account. Enter your
                username (same as LCR) — usually not an email address.
              </p>
              {otpUsernameHint(email) && (
                <p className="tiny" style={{ color: 'var(--primary)' }} role="note">
                  {otpUsernameHint(email)}
                </p>
              )}
            </>
          )}
          {/* The password-free "authorize on the Church's own page" lane is MOBILE-only — a browser
              can't read churchofjesuschrist.org's cookies (same-origin), so the WebView capture
              can't run on web. Point leaders who'd rather not type a password at the app. */}
          <p className="tiny" style={{ color: 'var(--on-surface-variant)' }}>
            Prefer not to enter your password? Authorize from the Covenant Path <strong>mobile app</strong>,
            which signs you in on the Church's own website — no password in the app. (Enrolling your
            stake on the phone activates the daily sync here too.)
          </p>
        </>
      )}
      {busy && status && <p style={{ color: 'var(--primary)' }} role="status">{status}</p>}
      {error && <p style={{ color: 'var(--error)' }} role="alert">{error}</p>}
    </Modal>
  );
}
