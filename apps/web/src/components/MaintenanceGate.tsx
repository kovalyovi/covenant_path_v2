// Owner-only MAINTENANCE mode (migration 0056). While the global switch is ON, everyone EXCEPT the
// owner sees a lock screen — and the database already returns no member data to them (a RESTRICTIVE
// RLS gate), so this component is purely the UX layer over that containment. The owner keeps the app
// and gets a banner + an Admin card to flip it. "Protected to only me": the toggle RPC is owner-gated
// server-side, and the control only renders for the owner.

import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../lib/supabase';

export type MaintenanceState = { on: boolean; isOwner: boolean; message: string | null; loading: boolean };

/** Read the global switch + whether the signed-in user is the OWNER. Best-effort, once per mount. */
export function useMaintenance(): MaintenanceState {
  const [state, setState] = useState<MaintenanceState>({ on: false, isOwner: false, message: null, loading: true });
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [status, owner] = await Promise.all([
          supabase.from('maintenance_status').select('maintenance_mode,maintenance_message').maybeSingle(),
          supabase.rpc('is_owner'),
        ]);
        if (!active) return;
        const row = status.data as { maintenance_mode?: boolean; maintenance_message?: string | null } | null;
        setState({
          on: row?.maintenance_mode === true,
          message: row?.maintenance_message ?? null,
          isOwner: owner.data === true,
          loading: false,
        });
      } catch {
        if (active) setState((s) => ({ ...s, loading: false }));
      }
    })();
    return () => { active = false; };
  }, []);
  return state;
}

/** Owner-only: flip the switch (the RPC raises 'not authorized' for anyone else). */
export async function setMaintenance(on: boolean, message?: string | null): Promise<void> {
  const { error } = await supabase.rpc('set_maintenance_mode', { p_on: on, p_message: message ?? null });
  if (error) throw new Error(error.message);
}

/** Wraps the authenticated app. Non-owners get the lock screen during maintenance; the owner gets a
 *  banner + the normal app. While the status is loading we render children (the DB still contains the
 *  data, so there is nothing to leak) to avoid a loader flash on every load. */
export function MaintenanceGate({ children }: { children: React.ReactNode }) {
  const m = useMaintenance();
  if (!m.loading && m.on && !m.isOwner) return <MaintenanceScreen message={m.message} />;
  return (
    <>
      {m.on && m.isOwner && <OwnerMaintenanceBanner />}
      {children}
    </>
  );
}

function MaintenanceScreen({ message }: { message: string | null }) {
  return (
    <div className="center-col" style={{ minHeight: '100vh', gap: 14, padding: 24, textAlign: 'center' }}>
      <div style={{ fontSize: 44 }} aria-hidden>🛠️</div>
      <h1 style={{ margin: 0 }}>We’ll be right back</h1>
      <p className="muted" style={{ maxWidth: 440 }}>
        {message?.trim() || 'Covenant Path is briefly down for maintenance. Please check back in a little while.'}
      </p>
    </div>
  );
}

function OwnerMaintenanceBanner() {
  const [busy, setBusy] = useState(false);
  const turnOff = useCallback(async () => {
    setBusy(true);
    try { await setMaintenance(false); window.location.reload(); } catch { setBusy(false); }
  }, []);
  return (
    <div role="status" style={{
      background: '#8a6d00', color: '#fff', padding: '8px 14px', display: 'flex',
      alignItems: 'center', justifyContent: 'center', gap: 14, fontSize: 14, flexWrap: 'wrap',
    }}>
      <span>🛠️ Maintenance mode is <b>ON</b> — only you can see the app.</span>
      <button onClick={turnOff} disabled={busy}
              style={{ color: 'inherit', background: 'none', border: '1px solid currentColor',
                       borderRadius: 6, padding: '2px 10px', cursor: 'pointer' }}>
        {busy ? 'Turning off…' : 'Turn off'}
      </button>
      <Link to="/admin" style={{ color: 'inherit' }}>Admin</Link>
    </div>
  );
}

/** Owner-only card for the Admin console: enable/disable maintenance + an optional message. Renders
 *  nothing for non-owners (and the RPC is owner-gated regardless). */
export function MaintenanceModeCard() {
  const m = useMaintenance();
  const [on, setOn] = useState(false);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setOn(m.on); setMsg(m.message ?? ''); }, [m.on, m.message]);
  if (m.loading || !m.isOwner) return null;

  const apply = async (next: boolean) => {
    setBusy(true);
    setErr(null);
    try { await setMaintenance(next, next ? (msg.trim() || null) : null); setOn(next); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div className="card__body" style={{ display: 'grid', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <b>Maintenance mode</b>
          <span style={{
            fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 999,
            background: on ? '#8a6d00' : 'var(--surface-2, #2a2a2a)', color: on ? '#fff' : 'inherit',
          }}>{on ? 'ON' : 'OFF'}</span>
        </div>
        <div className="muted" style={{ fontSize: 13 }}>
          When ON, everyone except you sees a maintenance screen and the database returns no member data
          to them — flip it the moment anything looks wrong, then turn it back off once it’s fixed.
        </div>
        <input
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          placeholder="Optional message shown to users"
          disabled={busy}
          style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border, #444)',
                   background: 'var(--surface, transparent)', color: 'inherit' }}
        />
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {on
            ? <button className="btn btn--filled" disabled={busy} onClick={() => apply(false)}>
                {busy ? 'Saving…' : 'Turn OFF maintenance'}
              </button>
            : <button className="btn btn--danger" disabled={busy} onClick={() => apply(true)}>
                {busy ? 'Saving…' : 'Turn ON maintenance'}
              </button>}
          {on && <button className="btn" disabled={busy} onClick={() => apply(true)}>Update message</button>}
        </div>
        {err && <div style={{ color: 'var(--error, #e5484d)', fontSize: 13 }}>{err}</div>}
      </div>
    </div>
  );
}
