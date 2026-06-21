// Sync-settings sheet — the React port of `_SyncSettingsSheet` (+ the schedule + Google-Drive
// sub-sections) from dashboard_common.dart. Opens instantly with a skeleton, then resolves the
// broker enrollment status. Provider-only actions (Sync now / Revoke / schedule / Drive) self-gate.

import { useEffect, useState } from 'react';
import { broker, type EnrollmentStatus } from '../lib/broker';
import { fmtDateTime, fmtEtHourLocal } from '../logic/dates';
import { Modal } from './Modal';
import { Button } from './ui';
import { Icon } from './Icon';
import { SyncSettingsSkeleton, SubsectionSkeleton } from './Skeletons';
import { useToast } from './Toast';

interface Props {
  open: boolean;
  onClose: () => void;
  initial: EnrollmentStatus | null;
  onLoaded: (s: EnrollmentStatus) => void;
  onRevoke: () => void;
  onSyncNow: () => void;
  /** Opens the Church re-authorization dialog (set up / re-enroll / take over the sync). */
  onReauth: () => void;
}

export function SyncSettingsSheet({ open, onClose, initial, onLoaded, onRevoke, onSyncNow, onReauth }: Props) {
  const toast = useToast();
  const [status, setStatus] = useState<EnrollmentStatus | null>(initial);
  const [loading, setLoading] = useState(initial == null);
  const [confirmWipe, setConfirmWipe] = useState(false);
  const [wiping, setWiping] = useState(false);

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
  const credState = cred?.state ?? 'none';
  const isProvider = cred?.isProvider === true;
  // A revoked/stale credential needs RE-AUTHORIZATION (any authorized leader may provide it — the
  // broker enforces who can take over). It can't "Sync now", and a revoked one can't be re-revoked
  // (the "status says Revoked but offers Revoke" report, 2026-06-10).
  const needsReauth = credState === 'revoked' || credState === 'stale';
  // TAKE-OVER (the Raleigh/Ricky bug, 2026-06-18): an ACTIVE credential provided by SOMEONE ELSE used
  // to leave a higher-access stake leader with no action at all — they couldn't put their own (broader)
  // credential in place. Offer it now to any stake-level leader who isn't already the provider. The
  // broker's most-elevated-wins rule decides on submit: a higher/equal account takes over; a strictly
  // lower one is told its access is narrower and nothing changed (so a lower leader can't clobber).
  const canTakeOver =
    credState === 'active' && !isProvider && status?.viewerIsStakeLeader === true;

  /** Provider self-service wipe: deletes the stake's MEMBER records (access + the sync credential
   *  stay; data re-populates on the next sync) — the self-serve mirror of the admin "Wipe data". */
  async function doWipe() {
    const stakeId = status?.stakeId;
    setConfirmWipe(false);
    if (!stakeId) return;
    setWiping(true);
    try {
      await broker.wipeData(stakeId);
      toast.show({ message: "Stake data wiped — it will re-populate on the next sync." });
      const s = await broker.enrollmentStatus();
      setStatus(s);
      onLoaded(s);
    } catch (e) {
      toast.show({ message: `Could not wipe data: ${e instanceof Error ? e.message : e}` });
    } finally {
      setWiping(false);
    }
  }

  return (
    <>
    <Modal open={open} onClose={onClose} side title="Sync settings">
      {loading ? (
        <SyncSettingsSkeleton />
      ) : status == null ? (
        <p>Could not load sync settings — close and try again.</p>
      ) : (
        <div style={{ paddingBottom: 16 }}>
          <Row label="Stake" value={status.stakeName ?? '—'} />
          {/* Stable LCR stake ID — stakes get renamed, so the ID reliably identifies the stake (#9). */}
          {status.unitNumber != null && <Row label="Stake ID" value={String(status.unitNumber)} />}
          <Row label="Last synced" value={status.lastSyncedAt ? fmtDateTime(status.lastSyncedAt) : 'Never'} />
          <Row label="Members" value={String(status.memberCount)} />
          <hr className="divider" />
          {cred == null || cred.state === 'none' ? (
            <>
              <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
                <Icon name="warning" size={20} color="var(--warning)" />
                <div>
                  <strong>
                    {status.unitNumber != null
                      ? `No sync credential for stake ${status.unitNumber}`
                      : 'No sync credential'}
                  </strong>
                  <p className="small muted">Sign in with your Church account to enable daily updates.</p>
                </div>
              </div>
              <Button
                variant="filled"
                icon="key"
                onClick={() => {
                  onClose();
                  onReauth();
                }}
                style={{ marginTop: 12 }}
              >
                Set up daily sync
              </Button>
            </>
          ) : (
            <>
              <Row
                label="Status"
                value={
                  credState === 'revoked'
                    ? 'Revoked'
                    : credState === 'stale'
                      ? 'Needs re-authorization'
                      : 'Active'
                }
                color={credState === 'active' ? 'var(--success)' : 'var(--warning)'}
              />
              {cred.principalName && <Row label="Provided by" value={cred.principalName} />}
              {cred.enrolledAt && <Row label="Enrolled" value={fmtDateTime(cred.enrolledAt)} />}
              <Row label="Coverage" value={cred.complete ? 'Complete' : 'Partial'} />
              {credState === 'stale' && cred.lastError && (
                <p className="tiny muted" style={{ marginTop: 4 }}>
                  Last sync error: {cred.lastError}
                </p>
              )}
            </>
          )}
          <p className="tiny" style={{ marginTop: 8 }}>
            Credentials are encrypted and stored server-side. Your password is never stored.
          </p>
          {needsReauth && (
            <Button
              variant="filled"
              icon="key"
              onClick={() => {
                onClose();
                onReauth();
              }}
              style={{ marginTop: 16 }}
            >
              Re-authorize daily sync
            </Button>
          )}
          {canTakeOver && (
            <>
              <div className="row" style={{ alignItems: 'flex-start', gap: 6, marginTop: 16 }}>
                <Icon name="key" size={15} color="var(--primary)" />
                <span className="small muted">
                  This stake's sync is provided by {cred?.principalName || 'another leader'}. If your
                  calling has the same or broader access, you can take it over with your own Church
                  account.
                </span>
              </div>
              <Button
                variant="outlined"
                icon="key"
                onClick={() => {
                  onClose();
                  onReauth();
                }}
                style={{ marginTop: 8 }}
              >
                Use my account for sync
              </Button>
            </>
          )}
          {isProvider && credState === 'active' && (
            <Button variant="filled" icon="sync" onClick={onSyncNow} style={{ marginTop: 16 }}>
              Sync my stake now
            </Button>
          )}
          {isProvider && credState !== 'revoked' && credState !== 'none' && (
            <>
              {/* R3 revoke-risk: a complete (full-access) credential keeps the WHOLE stake synced for
                  every leader. Warn before revoking — the data freezes until someone re-authorizes. */}
              {cred?.complete && (
                <div className="row" style={{ alignItems: 'flex-start', gap: 6, marginTop: 12 }}>
                  <Icon name="warning" size={15} color="var(--warning)" />
                  <span className="small" style={{ color: 'var(--warning)' }}>
                    This is the stake's full-access sync. Revoking it pauses daily updates for the
                    entire stake — every ward — until a leader re-authorizes.
                  </span>
                </div>
              )}
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
            </>
          )}
          {isProvider && (
            <Button
              variant="outlined"
              icon="error"
              disabled={wiping}
              loading={wiping}
              onClick={() => setConfirmWipe(true)}
              style={{ marginTop: 8 }}
            >
              Wipe stake data
            </Button>
          )}
          {isProvider && <ScheduleSection />}
          <GoogleDriveSection />
        </div>
      )}
    </Modal>

    <Modal
      open={confirmWipe}
      onClose={() => setConfirmWipe(false)}
      title="Wipe stake data?"
      hideClose
      actions={
        <>
          <Button onClick={() => setConfirmWipe(false)}>Cancel</Button>
          <Button variant="filled" onClick={() => void doWipe()}>
            Wipe data
          </Button>
        </>
      }
    >
      <p>
        This deletes ALL member records for your stake. Your access and the sync credential stay,
        and the data re-populates on the next sync.
      </p>
    </Modal>
    </>
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

  if (!loaded) return <SubsectionSkeleton />; // #16: skeleton while loading, not a blank pop-in
  if (!eligible) return null;
  // The schedule is stored as an ET hour (the cron gate runs in ET) but DISPLAYED in the
  // viewer's local time — nobody should have to convert timezones to read their sync time.
  const label = (h: number) => fmtEtHourLocal(h);

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
          : 'Your stake syncs automatically each day at this time (shown in your local time).'}
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
  const [loaded, setLoaded] = useState(false); // #16: tell "loading" apart from "loaded, not eligible"
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setS(await broker.googleDriveStatus());
    } catch {
      /* leave hidden on error */
    } finally {
      setLoaded(true);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  if (!loaded) return <SubsectionSkeleton />; // #16: skeleton while the status loads, not a pop-in
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
