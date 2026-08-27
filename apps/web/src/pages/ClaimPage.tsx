// /claim?token=… — the landing page for the "confirm your access" email (migration 0065).
//
// The link is mailed to the address ON RECORD for a leader; opening it while signed in as the
// address that REQUESTED the claim links the two. Both halves are required, which is the whole
// security story: possessing the link is not enough, and being signed in is not enough.

import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { broker } from '../lib/broker';
import { Icon } from '../components/Icon';
import { Button, Spinner } from '../components/ui';

type Phase = { kind: 'working' } | { kind: 'done'; name: string; granted: number } | { kind: 'error'; message: string };

export function ClaimPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') ?? '';
  const [phase, setPhase] = useState<Phase>({ kind: 'working' });
  // React 18 StrictMode double-invokes effects in dev; the token is SINGLE-USE, so a second call
  // would consume it and report "already used". Guard so we only ever redeem once.
  const redeemed = useRef(false);

  useEffect(() => {
    if (redeemed.current) return;
    redeemed.current = true;
    if (!token) {
      setPhase({ kind: 'error', message: 'That link is missing its confirmation code.' });
      return;
    }
    let alive = true;
    broker
      .claimVerify(token)
      .then((res) => {
        if (!alive) return;
        setPhase({ kind: 'done', name: String(res['name'] ?? ''), granted: Number(res['granted'] ?? 0) });
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setPhase({ kind: 'error', message: e instanceof Error ? e.message : 'Could not confirm that link.' });
      });
    return () => { alive = false; };
  }, [token]);

  return (
    <div className="center-col" style={{ minHeight: '100vh', padding: 24, textAlign: 'center' }}>
      {phase.kind === 'working' && (
        <>
          <Spinner large />
          <p className="muted">Confirming your access…</p>
        </>
      )}
      {phase.kind === 'done' && (
        <>
          <Icon name="check_circle" size={56} color="var(--primary)" />
          <h2 style={{ fontSize: '1.1rem' }}>Access linked</h2>
          <p className="muted" style={{ maxWidth: 420 }}>
            This sign-in now has the same access as {phase.name || 'your leadership record'}
            {phase.granted > 1 ? ` (${phase.granted} callings)` : ''}. Your stake&rsquo;s data should
            appear right away.
          </p>
          <Button variant="filled" onClick={() => navigate('/baptisms', { replace: true })}>
            Open the app
          </Button>
        </>
      )}
      {phase.kind === 'error' && (
        <>
          <Icon name="info" size={56} color="var(--error)" />
          <h2 style={{ fontSize: '1.1rem' }}>Couldn&rsquo;t confirm that link</h2>
          <p className="muted" style={{ maxWidth: 420 }}>{phase.message}</p>
          <Button variant="outlined" onClick={() => navigate('/baptisms', { replace: true })}>
            Back to the app
          </Button>
        </>
      )}
    </div>
  );
}
