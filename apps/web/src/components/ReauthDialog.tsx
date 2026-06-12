// In-app Church re-authorization (feedback: "hit re-authorize and was pushed back to the login
// screen — should be an extra modal"). Opens over the dashboard, runs the Church sign-in WITH sync
// consent (enroll=true, MFA-aware), and keeps the user in the app: on success the broker stores the
// fresh credential (0038 refresh rules) and we just reload enrollment status + toast.
//
// USERNAME + PASSWORD ONLY (2026-06-12). Setting up daily sync mints a 45-day Member Tools token via
// a silent SSO that needs the GLOBAL Okta session only the classic username+password lane establishes
// (/auth/web/*). The passwordless emailed-code (OTP) lane was removed: its Okta session is app-scoped
// and could never mint the token — it stored a credential that failed every sync ("Ken Packer" loop).
// Passwordless VIEWING still exists on the login screen via the Supabase email relay (a different
// system: no Church session, can't enroll). See docs/DECISIONS.md (ADR-010).

import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { broker, BrokerError, mfaRequired, type BrokerFactor, type BrokerResult } from '../lib/broker';
import { mfaPrompt } from '../lib/mfaCopy';
import { kNoAccessMessage } from '../lib/disclaimer';
import { useDashboard } from '../hooks/useDashboard';
import { useToast } from './Toast';
import { Modal } from './Modal';
import { Button } from './ui';

export function ReauthDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const d = useDashboard();
  const toast = useToast();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [loginId, setLoginId] = useState<string | null>(null);
  const [factors, setFactors] = useState<BrokerFactor[]>([]);
  const [factorSent, setFactorSent] = useState<BrokerFactor | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  // The password lane IS the credential-capture (one-MFA) flow (/auth/web/*): the single MFA mints
  // the 45-day sync token. Its MFA continuation stays on the web endpoints.
  const selectFactorFn = (lid: string, fid: string) => broker.webSelectFactor(lid, fid);
  const verifyMfaFn = (lid: string, code: string) => broker.webVerify(lid, code, true);

  // Enter (or re-enter) the MFA factor step. An MFA-enabled account may, after the first factor,
  // demand a DISTINCT factor (for Church accounts that's often the password — 2026-06-12, the
  // operator's own account after enabling MFA: every correct code read as "couldn't verify").
  async function enterMfa(r: BrokerResult) {
    setLoginId(r.loginId ?? null);
    setFactors(r.factors);
    setFactorSent(null);
    setMfaCode('');
    if (r.factors.length === 1 && r.loginId) {
      await selectFactorFn(r.loginId, r.factors[0].id);
      setFactorSent(r.factors[0]);
      setResendIn(30);
    }
  }

  const signIn = () =>
    run(async () => {
      const r = await broker.webStart(username.trim(), password, true); // enroll=true: this IS the consent
      if (mfaRequired(r)) {
        await enterMfa(r);
        return;
      }
      await finish(r);
    });

  const pickFactor = (f: BrokerFactor) =>
    run(async () => {
      await selectFactorFn(loginId!, f.id);
      setFactorSent(f);
      setMfaCode('');
      setResendIn(30);
    });

  const verify = () =>
    run(async () => {
      try {
        const r = await verifyMfaFn(loginId!, mfaCode.trim());
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
          {factorSent ? (
            <Button
              variant="filled"
              onClick={verify}
              // A password isn't a 6-digit code — gate it on non-empty only.
              disabled={busy || (factorSent.method === 'password' ? mfaCode.length === 0 : mfaCode.length < 6)}
              loading={busy}
            >
              Verify & authorize
            </Button>
          ) : loginId == null ? (
            <Button variant="filled" onClick={signIn} disabled={busy || !username.trim() || !password} loading={busy}>
              Authorize
            </Button>
          ) : null}
        </>
      }
    >
      {factorSent ? (
        <>
          <p>{mfaPrompt(factorSent).prompt}</p>
          {mfaPrompt(factorSent).warning && (
            <p className="tiny" style={{ color: 'var(--primary)' }}>
              {mfaPrompt(factorSent).warning}
            </p>
          )}
          {factorSent.method === 'password' ? (
            /* MFA continuation: the next factor is the PASSWORD (a distinct factor type from the
               emailed code) — a digits-only code box can't take it. */
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
            Sign in with your Church account (same username and password as LCR) to set up the daily
            sync. The session is stored encrypted — never your password — and is revocable anytime.
          </p>
          <p className="tiny" style={{ color: 'var(--on-surface-variant)' }}>
            Daily sync needs your <strong>username and password</strong> — that's the only sign-in the
            Church lets us renew unattended for ~45 days. (An emailed code can sign you in to view, but
            can't authorize the background sync.)
          </p>
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
