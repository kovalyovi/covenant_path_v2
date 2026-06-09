// In-app Church re-authorization (feedback: "hit re-authorize and was pushed back to the login
// screen — should be an extra modal"). Opens over the dashboard, runs the Church sign-in WITH sync
// consent (enroll=true, MFA-aware), and keeps the user in the app: on success the broker stores the
// fresh credential (0038 refresh rules) and we just reload enrollment status + toast. Used by the
// stale/revoked banner, the EmptyState set-up-sync CTA, and Sync settings.

import { useState } from 'react';
import { supabase } from '../lib/supabase';
import { broker, BrokerError, mfaRequired, type BrokerFactor, type BrokerResult } from '../lib/broker';
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

  function resetAll() {
    setLoginId(null);
    setFactors([]);
    setFactorSent(null);
    setMfaCode('');
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
    toast.show({
      message: r.stored
        ? 'Daily sync authorized — your stake will refresh within minutes.'
        : 'Signed in — sync authorization completed.',
    });
    void d.reloadEnrollStatus();
    resetAll();
    setUsername('');
    setPassword('');
    onClose();
  }

  const signIn = () =>
    run(async () => {
      const r = await broker.password(username.trim(), password, true); // enroll=true: this IS the consent
      if (mfaRequired(r)) {
        setLoginId(r.loginId ?? null);
        setFactors(r.factors);
        if (r.factors.length === 1) {
          await broker.selectFactor(r.loginId!, r.factors[0].id);
          setFactorSent(r.factors[0]);
        }
        return;
      }
      await finish(r);
    });

  const pickFactor = (f: BrokerFactor) =>
    run(async () => {
      await broker.selectFactor(loginId!, f.id);
      setFactorSent(f);
    });

  const verify = () =>
    run(async () => {
      const r = await broker.verifyMfa(loginId!, mfaCode.trim(), true);
      await finish(r);
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
      actions={
        <>
          <Button onClick={() => { resetAll(); onClose(); }} disabled={busy}>
            Cancel
          </Button>
          {factorSent ? (
            <Button variant="filled" onClick={verify} disabled={busy || !mfaCode.trim()} loading={busy}>
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
          <p>Enter the code sent via {factorSent.label}.</p>
          <label className="field">
            <span>Verification code</span>
            <input
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value)}
            />
          </label>
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
          <label className="field" style={{ marginBottom: 8 }}>
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
      )}
      {busy && status && <p style={{ color: 'var(--primary)' }} role="status">{status}</p>}
      {error && <p style={{ color: 'var(--error)' }} role="alert">{error}</p>}
    </Modal>
  );
}
