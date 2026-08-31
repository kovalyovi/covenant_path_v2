// Owner-only MAINTENANCE mode (migration 0056). While the global switch is ON, everyone EXCEPT the
// owner sees a lock screen — and the database already returns no member data to them (a RESTRICTIVE
// RLS gate), so this component is purely the UX layer over that containment. The owner keeps the app
// and gets a banner + an Admin card to flip it. "Protected to only me": the toggle RPC is owner-gated
// server-side, and the control only renders for the owner. Strings are localized (i18n) with English
// fallback.

import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  return (
    <div className="maint-screen">
      <div className="maint-screen__icon" aria-hidden>🛠️</div>
      <h1>{t('maintenance.title')}</h1>
      <p>{message?.trim() || t('maintenance.body')}</p>
    </div>
  );
}

function OwnerMaintenanceBanner() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const turnOff = useCallback(async () => {
    setBusy(true);
    try { await setMaintenance(false); window.location.reload(); } catch { setBusy(false); }
  }, []);
  return (
    <div role="status" className="maint-banner">
      <span>🛠️ {t('maintenance.ownerBannerOn')}</span>
      <span className="maint-banner__actions">
        <button type="button" className="btn btn--outlined" onClick={turnOff} disabled={busy}>
          {busy ? t('maintenance.turningOff') : t('maintenance.turnOff')}
        </button>
        <Link to="/admin">{t('maintenance.admin')}</Link>
      </span>
    </div>
  );
}

/** Owner-only card for the Admin console: enable/disable maintenance + an optional message. Renders
 *  nothing for non-owners (and the RPC is owner-gated regardless). */
export function MaintenanceModeCard() {
  const { t } = useTranslation();
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
    <div className="card">
      <div className="card__body ops-maint">
        <div className="ops-card__head">
          <span className="ops-card__title">{t('maintenance.cardTitle')}</span>
        </div>

        {/* The switch IS the state: label, explanation and control in one row, so there is no
            guessing which button applies to which state (the old card showed a pill and up to two
            buttons whose meanings depended on it). */}
        <label className={`ops-maint__state${on ? ' ops-maint__state--on' : ''}`}>
          <span className="ops-maint__label">
            <b>{on ? t('maintenance.on') : t('maintenance.off')}</b>
            <span>{on ? t('maintenance.stateOn') : t('maintenance.stateOff')}</span>
          </span>
          <input
            type="checkbox"
            className="switch"
            checked={on}
            disabled={busy}
            aria-label={on ? t('maintenance.turnOffFull') : t('maintenance.turnOn')}
            onChange={(e) => void apply(e.target.checked)}
          />
        </label>

        <p className="ops-card__intro" style={{ margin: 0 }}>{t('maintenance.cardHelp')}</p>

        <label className="field">
          <span>{t('maintenance.messageLabel')}</span>
          <input
            className="input"
            value={msg}
            onChange={(e) => setMsg(e.target.value)}
            placeholder={t('maintenance.messagePlaceholder')}
            disabled={busy}
          />
        </label>

        {on && (
          <div className="ops-maint__actions">
            <button type="button" className="btn btn--outlined" disabled={busy} onClick={() => void apply(true)}>
              {busy ? t('maintenance.saving') : t('maintenance.updateMessage')}
            </button>
          </div>
        )}

        {err && <div className="small" style={{ color: 'var(--error)' }}>{err}</div>}
      </div>
    </div>
  );
}
