// Three ways in, one resulting session (ported from apps/viewer/lib/login_page.dart):
//  • Church account (username + password, MFA-aware) — via the auth broker (CORS), only shown when
//    the broker is configured. Blocks a no-access calling at login (N2) instead of signing them in.
//  • Email code — Supabase OTP to the email LCR has on file (with a broker relay fallback for
//    networks that can't reach Supabase directly).
//  • Passkey — passwordless WebAuthn (web), when the broker + a platform authenticator are present.
// The broker is warmed up the moment this screen opens (N5) to hide its cold start.

import { useEffect, useRef, useState } from 'react';
import { supabase } from '../lib/supabase';
import { broker, BrokerError, mfaRequired, type BrokerFactor, type BrokerResult } from '../lib/broker';
import { passkey } from '../lib/passkey';
import { kNoAccessMessage } from '../lib/disclaimer';
import { Button, Segmented } from '../components/ui';
import { Icon } from '../components/Icon';

type Mode = 'church' | 'email';

export function LoginPage() {
  const brokerAvailable = broker.available;
  const passkeyAvailable = passkey.available;

  const [mode, setMode] = useState<Mode>(brokerAvailable ? 'church' : 'email');
  const [status, setStatus] = useState<string | null>(null); // "waking up the sign-in service…"
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Church-account fields
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [loginId, setLoginId] = useState<string | null>(null);
  const [factors, setFactors] = useState<BrokerFactor[]>([]);
  const [factorSent, setFactorSent] = useState<BrokerFactor | null>(null);
  // Explicit, default-OFF authorization — signing in alone never captures the leader's session.
  const [authorizeSync, setAuthorizeSync] = useState(false);

  // Email-code fields
  const [email, setEmail] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const [emailCodeSent, setEmailCodeSent] = useState(false);
  const [useRelay, setUseRelay] = useState(false);

  const warmed = useRef(false);
  useEffect(() => {
    broker.onStatus = (m) => setStatus(m);
    if (!warmed.current) {
      warmed.current = true;
      broker.warmUp(); // N5: start waking the broker while the user types — hides cold start
    }
    return () => {
      broker.onStatus = undefined;
    };
  }, []);

  function reset() {
    setLoginId(null);
    setFactors([]);
    setFactorSent(null);
    setMfaCode('');
    setEmailCodeSent(false);
    setEmailCode('');
    setError(null);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof BrokerError || e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Turn a broker-minted OTP into a real Supabase session (the router then routes to the app).
  async function consume(r: BrokerResult) {
    if (!r.email || !r.otp) throw new BrokerError('Sign-in service did not return a session.');
    const { error: e } = await supabase.auth.verifyOtp({ email: r.email, token: r.otp, type: 'email' });
    if (e) throw e;
  }

  // N2: a present, explicit authorized:false means this calling has NO covenant-path access — don't
  // create a session; show why and stay on the login screen. null (unknown) is allowed through.
  function noAccess(r: BrokerResult): boolean {
    if (r.authorized === false) {
      setError(kNoAccessMessage);
      return true;
    }
    return false;
  }

  const churchSignIn = () =>
    run(async () => {
      const r = await broker.password(username.trim(), password, authorizeSync);
      if (mfaRequired(r)) {
        setLoginId(r.loginId ?? null);
        setFactors(r.factors);
        if (r.factors.length === 1) await selectFactor(r.factors[0]);
        return;
      }
      await finishChurch(r);
    });

  const selectFactor = (f: BrokerFactor) =>
    run(async () => {
      await broker.selectFactor(loginId!, f.id);
      setFactorSent(f);
    });

  const verifyMfa = () =>
    run(async () => {
      const r = await broker.verifyMfa(loginId!, mfaCode.trim(), authorizeSync);
      await finishChurch(r);
    });

  // After a successful Church login: block a no-access calling (N2); else, if the stake has no
  // sufficient sync credential and this leader could provide one (set one up, or improve a weaker
  // existing one), OFFER it post-login (#8 — consent is no longer a login-form checkbox). On accept,
  // re-auth WITH consent so the broker stores the credential. Finally, adopt the session.
  async function finishChurch(r: BrokerResult) {
    if (noAccess(r)) return;
    if (!authorizeSync && (r.canEnroll || r.canImprove)) {
      const stake = r.stake ?? 'Your stake';
      const missing = r.canImprove && r.missing?.length ? ` (missing: ${r.missing.slice(0, 3).join(', ')})` : '';
      const msg = r.canImprove
        ? `${stake} is currently synced by a leader whose access can't pull everything${missing}. ` +
          `Authorize your Church session to take over the daily sync? It's stored encrypted (never your password) and revocable anytime.`
        : `${stake} isn't set up for daily sync yet. Authorize your Church session so your stake's ` +
          `data refreshes automatically each day? It's stored encrypted (never your password) and revocable anytime.`;
      if (window.confirm(msg)) {
        const r2 = await broker.password(username.trim(), password, true); // re-auth WITH consent
        if (mfaRequired(r2)) {
          setAuthorizeSync(true); // so completing MFA stores the credential
          setLoginId(r2.loginId ?? null);
          setFactors(r2.factors);
          if (r2.factors.length === 1) await selectFactor(r2.factors[0]);
          return;
        }
        if (noAccess(r2)) return;
        await consume(r2);
        return;
      }
    }
    await consume(r);
  }

  const passkeySignIn = () =>
    run(async () => {
      const r = await passkey.login();
      await consume(r);
    });

  const sendEmailCode = () =>
    run(async () => {
      if (useRelay) {
        await broker.emailStart(email.trim()); // server-side, bypasses browser→Supabase
      } else {
        const { error: e } = await supabase.auth.signInWithOtp({ email: email.trim() });
        if (e) throw e;
      }
      setEmailCodeSent(true);
    });

  const verifyEmailCode = () =>
    run(async () => {
      if (useRelay) {
        const t = await broker.emailVerify(email.trim(), emailCode.trim());
        const { error: e } = await supabase.auth.setSession({
          access_token: t['access_token'] as string,
          refresh_token: t['refresh_token'] as string,
        });
        if (e) throw e;
      } else {
        const { error: e } = await supabase.auth.verifyOtp({
          email: email.trim(),
          token: emailCode.trim(),
          type: 'email',
        });
        if (e) throw e;
      }
    });

  return (
    <main className="login-wrap">
      <form
        className="login-card"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <h1 style={{ fontSize: '1.4rem' }}>Covenant Path</h1>

        {brokerAvailable && (
          <Segmented<Mode>
            ariaLabel="Sign-in method"
            value={mode}
            onChange={(m) => {
              if (busy) return;
              setMode(m);
              reset();
            }}
            options={[
              { value: 'church', label: 'Church account' },
              { value: 'email', label: 'Email code' },
            ]}
          />
        )}

        {mode === 'church' ? (
          <ChurchFields
            busy={busy}
            username={username}
            password={password}
            mfaCode={mfaCode}
            loginId={loginId}
            factors={factors}
            factorSent={factorSent}
            setUsername={setUsername}
            setPassword={setPassword}
            setMfaCode={setMfaCode}
            onSignIn={churchSignIn}
            onSelectFactor={selectFactor}
            onVerify={verifyMfa}
            onBack={() => reset()}
            onChooseDifferent={() => setFactorSent(null)}
          />
        ) : (
          <EmailFields
            busy={busy}
            email={email}
            emailCode={emailCode}
            emailCodeSent={emailCodeSent}
            useRelay={useRelay}
            brokerAvailable={brokerAvailable}
            setEmail={setEmail}
            setEmailCode={setEmailCode}
            onSend={sendEmailCode}
            onVerify={verifyEmailCode}
            onUseDifferent={() => setEmailCodeSent(false)}
            onEnableRelay={() => {
              setUseRelay(true);
              setEmailCodeSent(false);
              setEmailCode('');
              setError(null);
            }}
            onDisableRelay={() => {
              setUseRelay(false);
              setEmailCodeSent(false);
              setEmailCode('');
              setError(null);
            }}
          />
        )}

        {passkeyAvailable && (
          <>
            <div className="divider-or">or</div>
            <Button variant="outlined" icon="fingerprint" onClick={passkeySignIn} disabled={busy} type="button">
              Sign in with a passkey
            </Button>
          </>
        )}

        {busy && status && <p style={{ color: 'var(--primary)' }} role="status">{status}</p>}
        {error && (
          <p style={{ color: 'var(--error)' }} role="alert">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}

interface ChurchProps {
  busy: boolean;
  username: string;
  password: string;
  mfaCode: string;
  loginId: string | null;
  factors: BrokerFactor[];
  factorSent: BrokerFactor | null;
  setUsername: (v: string) => void;
  setPassword: (v: string) => void;
  setMfaCode: (v: string) => void;
  onSignIn: () => void;
  onSelectFactor: (f: BrokerFactor) => void;
  onVerify: () => void;
  onBack: () => void;
  onChooseDifferent: () => void;
}

function ChurchFields(p: ChurchProps) {
  // Step 3: enter the MFA code that was sent.
  if (p.factorSent) {
    return (
      <>
        <p>Enter the code sent via {p.factorSent.label}.</p>
        <label className="field">
          <span>Verification code</span>
          <input
            className="input"
            inputMode="numeric"
            value={p.mfaCode}
            onChange={(e) => p.setMfaCode(e.target.value)}
            autoComplete="one-time-code"
          />
        </label>
        <Button variant="filled" onClick={p.onVerify} disabled={p.busy} loading={p.busy} type="button">
          Verify & sign in
        </Button>
        <Button onClick={p.onChooseDifferent} disabled={p.busy} type="button">
          Choose a different method
        </Button>
      </>
    );
  }
  // Step 2: pick an MFA factor.
  if (p.loginId) {
    return (
      <>
        <p>Choose how to receive your verification code:</p>
        {p.factors.map((f) => (
          <Button key={f.id} variant="outlined" onClick={() => p.onSelectFactor(f)} disabled={p.busy} type="button">
            {f.label}
          </Button>
        ))}
        <Button onClick={p.onBack} disabled={p.busy} type="button">
          Back
        </Button>
      </>
    );
  }
  // Step 1: username + password.
  return (
    <>
      <p>Sign in with your Church account (same as LCR).</p>
      <label className="field">
        <span>Church username</span>
        <input
          className="input"
          value={p.username}
          autoComplete="username"
          onChange={(e) => p.setUsername(e.target.value)}
        />
      </label>
      <label className="field">
        <span>Password</span>
        <input
          className="input"
          type="password"
          value={p.password}
          autoComplete="current-password"
          onChange={(e) => p.setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !p.busy) p.onSignIn();
          }}
        />
      </label>
      {/* No "authorize daily sync" checkbox here (#8): signing in only views. If the stake isn't
          synced yet, we offer to set it up in a dialog AFTER a successful sign-in. */}
      <Button variant="filled" onClick={p.onSignIn} disabled={p.busy} loading={p.busy} type="submit">
        Sign in
      </Button>
    </>
  );
}

interface EmailProps {
  busy: boolean;
  email: string;
  emailCode: string;
  emailCodeSent: boolean;
  useRelay: boolean;
  brokerAvailable: boolean;
  setEmail: (v: string) => void;
  setEmailCode: (v: string) => void;
  onSend: () => void;
  onVerify: () => void;
  onUseDifferent: () => void;
  onEnableRelay: () => void;
  onDisableRelay: () => void;
}

function EmailFields(p: EmailProps) {
  return (
    <>
      <p>Sign in with the email your stake has on file.</p>
      {p.useRelay && (
        <div className="row" style={{ alignItems: 'flex-start' }}>
          <Icon name="shield" size={15} color="var(--primary)" />
          <span className="tiny" style={{ color: 'var(--primary)' }}>
            Backup mode: signing in through our server (for networks that block Supabase).
          </span>
        </div>
      )}
      <label className="field">
        <span>Email</span>
        <input
          className="input"
          type="email"
          autoComplete="email"
          disabled={p.emailCodeSent}
          value={p.email}
          onChange={(e) => p.setEmail(e.target.value)}
        />
      </label>
      {p.emailCodeSent && (
        <label className="field">
          <span>6-digit code</span>
          <input
            className="input"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={p.emailCode}
            onChange={(e) => p.setEmailCode(e.target.value)}
          />
        </label>
      )}
      <Button
        variant="filled"
        onClick={p.emailCodeSent ? p.onVerify : p.onSend}
        disabled={p.busy}
        loading={p.busy}
        type="submit"
      >
        {p.emailCodeSent ? 'Verify & sign in' : 'Send code'}
      </Button>
      {p.emailCodeSent && (
        <Button onClick={p.onUseDifferent} disabled={p.busy} type="button">
          Use a different email
        </Button>
      )}
      {p.brokerAvailable && !p.useRelay && (
        <Button onClick={p.onEnableRelay} disabled={p.busy} type="button">
          Can't connect? Use backup sign-in
        </Button>
      )}
      {p.useRelay && (
        <Button onClick={p.onDisableRelay} disabled={p.busy} type="button">
          Use normal sign-in
        </Button>
      )}
    </>
  );
}
