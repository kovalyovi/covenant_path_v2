// Sync-settings sheet — the React port of `_SyncSettingsSheet` (+ the schedule + Google-Drive
// sub-sections) from dashboard_common.dart. Opens instantly with a skeleton, then resolves the
// broker enrollment status. Provider-only actions (Sync now / Revoke / schedule / Drive) self-gate.

import { useEffect, useState } from 'react';
import { broker, type EnrollmentStatus } from '../lib/broker';
import { fmtDateTime } from '../logic/dates';
import { Modal } from './Modal';
import { Button } from './ui';
import { Icon } from './Icon';
import { SyncSettingsSkeleton } from './Skeletons';
import { useToast } from './Toast';

interface Props {
  open: boolean;
  onClose: () => void;
  initial: EnrollmentStatus | null;
  onLoaded: (s: EnrollmentStatus) => void;
  onRevoke: () => void;
  onSyncNow: () => void;
}

export function SyncSettingsSheet({ open, onClose, initial, onLoaded, onRevoke, onSyncNow }: Props) {
  const [status, setStatus] = useState<EnrollmentStatus | null>(initial);
  const [loading, setLoading] = useState(initial == null);

  useEffect(() => {
    if (!open) return;
    if (initial != null) {
      setStatus(initial);
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    broker
      .enrollmentStatus()
      .then((s) => {
        if (!active) return;
        setStatus(s);
        onLoaded(s);
      })
      .catch(() => {})
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [open, initial, onLoaded]);

  const cred = status?.credential;
  const isProvider = cred?.isProvider === true;

  return (
    <Modal open={open} onClose={onClose} sheet title="Sync settings">
      {loading ? (
        <SyncSettingsSkeleton />
      ) : status == null ? (
        <p>Could not load sync settings — close and try again.</p>
      ) : (
        <div style={{ paddingBottom: 16 }}>
          <Row label="Stake" value={status.stakeName ?? '—'} />
          <Row label="Last synced" value={status.lastSyncedAt ? fmtDateTime(status.lastSyncedAt) : 'Never'} />
          <Row label="Members" value={String(status.memberCount)} />
          <hr className="divider" />
          {cred == null || cred.state === 'none' ? (
            <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
              <Icon name="warning" size={20} color="var(--warning)" />
              <div>
                <strong>No sync credential</strong>
                <p className="small muted">Sign in with your Church account to enable daily updates.</p>
              </div>
            </div>
          ) : (
            <>
              <Row
                label="Status"
                value={cred.state === 'revoked' ? 'Revoked' : 'Active'}
                color={cred.state === 'revoked' ? 'var(--warning)' : 'var(--success)'}
              />
              {cred.principalName && <Row label="Provided by" value={cred.principalName} />}
              {cred.enrolledAt && <Row label="Enrolled" value={fmtDateTime(cred.enrolledAt)} />}
              <Row label="Coverage" value={cred.complete ? 'Complete' : 'Partial'} />
            </>
          )}
          <p className="tiny" style={{ marginTop: 8 }}>
            Credentials are encrypted and stored server-side. Your password is never stored.
          </p>
          {isProvider && (
            <Button variant="filled" icon="sync" onClick={onSyncNow} style={{ marginTop: 16 }}>
              Sync my stake now
            </Button>
          )}
          {isProvider && (
            <Button
              variant="outlined"
              icon="link_off"
              onClick={() => {
                onClose();
                onRevoke();
              }}
              style={{ marginTop: 8 }}
            >
              Revoke my sync access
            </Button>
          )}
          {isProvider && <ScheduleSection />}
          <GoogleDriveSection />
        </div>
      )}
    </Modal>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="row" style={{ padding: '4px 0', alignItems: 'flex-start' }}>
      <span className="muted" style={{ width: 110, flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ color, fontWeight: color ? 500 : undefined }}>{value}</span>
    </div>
  );
}

/** #schedule: the provider sets WHEN their stake's daily sync runs (ET hour) and can pause it. */
function ScheduleSection() {
  const toast = useToast();
  const [hour, setHour] = useState(7);
  const [paused, setPaused] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [eligible, setEligible] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    broker
      .getSchedule()
      .then((s) => {
        if (!active) return;
        setEligible(s['eligible'] === true);
        setHour(Number(s['hour_et'] ?? 7) || 7);
        setPaused(s['paused'] === true);
        setLoaded(true);
      })
      .catch(() => active && setLoaded(true));
    return () => {
      active = false;
    };
  }, []);

  async function save(nextHour: number, nextPaused: boolean) {
    setBusy(true);
    try {
      await broker.setSchedule(nextHour, nextPaused);
      setHour(nextHour);
      setPaused(nextPaused);
    } catch (e) {
      toast.show({ message: `Could not save schedule: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  if (!loaded || !eligible) return null;
  const label = (h: number) => {
    const ampm = h < 12 ? 'AM' : 'PM';
    const h12 = h % 12 === 0 ? 12 : h % 12;
    return `${h12}:00 ${ampm} ET`;
  };

  return (
    <div>
      <hr className="divider" />
      <div className="row">
        <Icon name="schedule" size={18} color="var(--primary)" />
        <strong>Daily sync time</strong>
      </div>
      <p className="small muted" style={{ marginTop: 4 }}>
        {paused
          ? 'Automatic daily sync is paused. You can still "Sync my stake now" anytime.'
          : 'Your stake syncs automatically each day at this time.'}
      </p>
      <div className="row" style={{ marginTop: 8 }}>
        <select
          className="select"
          style={{ width: 'auto', opacity: paused ? 0.5 : 1 }}
          value={hour}
          disabled={busy || paused}
          onChange={(e) => save(Number(e.target.value), paused)}
          aria-label="Daily sync hour"
        >
          {Array.from({ length: 24 }, (_, h) => (
            <option key={h} value={h}>
              {label(h)}
            </option>
          ))}
        </select>
        <span style={{ flex: 1 }} />
        {busy ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <Button icon={paused ? 'play' : 'pause'} onClick={() => save(hour, !paused)}>
            {paused ? 'Resume' : 'Pause'}
          </Button>
        )}
      </div>
    </div>
  );
}

/** M7: per-stake Google Drive — self-gates to the stake's sync provider with OAuth configured. */
function GoogleDriveSection() {
  const toast = useToast();
  const [s, setS] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setS(await broker.googleDriveStatus());
    } catch {
      /* leave hidden on error */
    }
  };

  useEffect(() => {
    void load();
  }, []);

  if (s == null || s['eligible'] !== true) return null;

  const header = (
    <div className="row">
      <Icon name="drive" size={18} color="var(--primary)" />
      <strong>Google Drive</strong>
    </div>
  );

  if (s['configured'] !== true) {
    return (
      <div>
        <hr className="divider" />
        {header}
        <p className="small muted" style={{ marginTop: 4 }}>
          Drive integration isn't enabled on the server yet — your stake's sheet is kept on the
          shared service account for now.
        </p>
      </div>
    );
  }

  const connected = s['connected'] === true;
  const needsReconnect = s['needs_reconnect'] === true;
  const sheetUrl = s['sheet_url'] as string | undefined;
  const lastSynced = s['last_synced_at'] as string | undefined;

  async function connect() {
    setBusy(true);
    try {
      const r = await broker.googleDriveStart();
      const url = r['url'] as string | undefined;
      if (url) {
        window.open(url, '_blank', 'noopener');
        toast.show({ message: 'Finish in the Google window, then tap "Refresh".' });
      }
    } catch (e) {
      toast.show({ message: `Could not start: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await broker.googleDriveDisconnect();
      await load();
    } catch (e) {
      toast.show({ message: `Could not disconnect: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <hr className="divider" />
      {header}
      {needsReconnect ? (
        <div className="row" style={{ alignItems: 'flex-start', gap: 6, marginTop: 4 }}>
          <Icon name="warning" size={15} color="var(--warning)" />
          <span className="small" style={{ color: 'var(--warning)' }}>
            Google Drive needs reconnecting — the saved access expired, so syncs are using the shared
            sheet for now. Reconnect to resume writing to your own Drive.
          </span>
        </div>
      ) : (
        <p className="small" style={{ marginTop: 4 }}>
          {connected
            ? `Connected as ${s['email'] ?? ''}. Your stake's spreadsheet lives in your Drive.`
            : "Connect your Google account so your stake gets its own spreadsheet that you own (the app can only touch the file it creates)."}
        </p>
      )}
      {connected && sheetUrl && (
        <a href={sheetUrl} target="_blank" rel="noopener" className="row small" style={{ marginTop: 6 }}>
          <Icon name="table" size={16} />
          Open your stake spreadsheet
        </a>
      )}
      {connected && lastSynced && (
        <p className="tiny muted" style={{ marginTop: 4 }}>
          Sheet last refreshed {fmtDateTime(lastSynced)}.
        </p>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        {connected ? (
          <Button variant="outlined" icon="link_off" disabled={busy} onClick={disconnect}>
            Disconnect
          </Button>
        ) : (
          <Button variant="filled" icon="drive" disabled={busy} onClick={connect}>
            Connect Google Drive
          </Button>
        )}
        <Button disabled={busy} onClick={load}>
          Refresh
        </Button>
      </div>
    </div>
  );
}
