// The dashboard scaffold — React port of `_DashboardPageState.build` + `_appBarActions`. App bar
// with a stake-switcher title (when >1 stake is visible), a freshness chip, Refresh, and a "⋯" menu
// (Sync settings / Generate report / Invite / Admin / Settings). Responsive nav: a side rail on
// tablet/desktop, a frosted bottom nav on mobile. Hosts the syncing/stale banners and the sheets.

import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useDashboard } from '../hooks/useDashboard';
import { useTier } from '../hooks/useTier';
import { signOut } from '../hooks/useAuth';
import { broker } from '../lib/broker';
import { admin } from '../lib/admin';
import { currentAccessToken } from '../lib/supabase';
import { passkey } from '../lib/passkey';
import { TABS } from '../theme/tokens';
import { Icon, type IconName } from '../components/Icon';
import { IconButton } from '../components/ui';
import { Menu, type MenuItem } from '../components/Menu';
import {
  SyncingBanner, StaleBanner, LastUpdatedChip,
} from '../components/dashboard';
import { SyncSettingsSheet } from '../components/SyncSettingsSheet';
import { ReportSheet } from '../components/ReportSheet';
import { useToast } from '../components/Toast';
import { Modal } from '../components/Modal';
import { Button } from '../components/ui';

export function DashboardShell() {
  const d = useDashboard();
  const tier = useTier();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();

  const [syncOpen, setSyncOpen] = useState(false);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);

  const staleCred = d.enrollStatus?.credential.state === 'revoked';

  // ---- Menu actions (mirror _appBarActions + the dashboard handlers) --------------------------
  function openSyncSettings() {
    if (!broker.available) {
      toast.show({ message: 'Sync settings require Church account login.' });
      return;
    }
    setSyncOpen(true);
  }

  async function generateReport() {
    if (!broker.available) {
      toast.show({ message: 'Reports need Church-account login configured.' });
      return;
    }
    setReportLoading(true);
    try {
      const rep = await broker.report();
      setReport(rep);
    } catch (e) {
      toast.show({ message: `Couldn't build report: ${e instanceof Error ? e.message : e}` });
    } finally {
      setReportLoading(false);
    }
  }

  async function emailReport() {
    try {
      const res = await broker.emailReport();
      toast.show({ message: `Report emailed to ${res['to'] ?? 'you'}.` });
    } catch (e) {
      toast.show({ message: `Couldn't email report: ${e instanceof Error ? e.message : e}` });
    }
  }

  async function syncNow() {
    setSyncOpen(false);
    try {
      const res = await broker.syncNow();
      const partial = res['coverage_complete'] === false;
      d.markSyncing();
      toast.show({
        message: partial
          ? "Sync started — note: your calling can't pull every field, so some data stays blank. Takes a few minutes."
          : 'Sync started for your stake — this takes a few minutes.',
      });
    } catch (e) {
      toast.show({ message: `Couldn't start sync: ${e instanceof Error ? e.message : e}` });
    }
  }

  const [confirmRevoke, setConfirmRevoke] = useState(false);
  async function doRevoke() {
    const stakeId = d.enrollStatus?.stakeId;
    setConfirmRevoke(false);
    if (!stakeId) return;
    try {
      await broker.revoke(stakeId);
      d.setEnrollStatus(null);
      toast.show({ message: 'Sync access revoked. Data will not update until re-enrolled.' });
    } catch (e) {
      toast.show({ message: `Could not revoke: ${e instanceof Error ? e.message : e}` });
    }
  }

  const menuItems: MenuItem[] = [
    { value: 'sync', label: 'Sync settings', icon: 'sync' },
    { value: 'report', label: 'Generate report', icon: 'summarize' },
    { value: 'invite', label: 'Invite a power user', icon: 'person_add' },
    ...(d.isAdmin ? [{ value: 'admin', label: 'Admin · Ops console', icon: 'admin' as IconName }] : []),
    { value: 'settings', label: 'Settings', icon: 'settings' },
  ];

  function onMenu(v: string) {
    switch (v) {
      case 'sync': return openSyncSettings();
      case 'report': return void generateReport();
      case 'invite': return navigate('/invite');
      case 'admin': return navigate('/admin');
      case 'settings': return navigate('/settings');
    }
  }

  const appbar = (
    <header className="appbar">
      <StakeTitle />
      <span className="appbar__spacer" />
      <div className="appbar__actions">
        {d.lastSynced && (
          <LastUpdatedChip
            iso={d.lastSynced}
            compact={tier === 'mobile'}
            syncing={d.syncing}
            onSyncNow={broker.available ? syncNow : undefined}
          />
        )}
        <IconButton icon="refresh" label="Refresh" onClick={() => void d.refresh()} />
        <Menu
          label="Menu"
          items={menuItems}
          onSelect={onMenu}
          trigger={({ toggle, open, id, controls }) => (
            <button
              type="button"
              className="iconbtn"
              aria-label="Menu"
              title="Menu"
              aria-haspopup="menu"
              aria-expanded={open}
              aria-controls={controls}
              id={id}
              onClick={toggle}
            >
              <Icon name="menu" size={22} />
            </button>
          )}
        />
      </div>
    </header>
  );

  const banners = (
    <>
      {d.syncing && <SyncingBanner startedAt={d.syncStartedAt} />}
      {staleCred && <StaleBanner onReenroll={() => void signOut()} />}
    </>
  );

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      {appbar}
      <div className="shell-body">
        {tier !== 'mobile' && (
          <nav className="rail" aria-label="Primary">
            {TABS.map((t) => (
              <NavLink key={t.path} to={`/${t.path}`} className={({ isActive }) => (isActive ? 'rail__item active' : 'rail__item')}>
                {({ isActive }) => (
                  <>
                    <Icon name={t.icon as IconName} size={22} color={isActive ? t.color : `${t.color}99`} />
                    {t.label}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        )}
        <main id="main" className="page" aria-label="Dashboard content">
          {banners}
          <Outlet />
        </main>
      </div>
      {tier === 'mobile' && (
        <nav className="bottomnav" aria-label="Primary">
          {TABS.map((t) => {
            const active = location.pathname === `/${t.path}`;
            return (
              <NavLink key={t.path} to={`/${t.path}`} className={active ? 'bottomnav__item active' : 'bottomnav__item'}>
                <Icon name={t.icon as IconName} size={24} color={active ? t.color : `${t.color}99`} className="icon" />
                {t.label}
              </NavLink>
            );
          })}
        </nav>
      )}

      <SyncSettingsSheet
        open={syncOpen}
        onClose={() => setSyncOpen(false)}
        initial={d.enrollStatus}
        onLoaded={(s) => d.setEnrollStatus(s)}
        onRevoke={() => setConfirmRevoke(true)}
        onSyncNow={syncNow}
      />
      {report && <ReportSheet open onClose={() => setReport(null)} report={report} onEmail={emailReport} />}
      {reportLoading && (
        <div className="scrim">
          <span className="spinner spinner--lg" role="status" aria-label="Building report" />
        </div>
      )}

      <Modal
        open={confirmRevoke}
        onClose={() => setConfirmRevoke(false)}
        title="Revoke sync access?"
        hideClose
        actions={
          <>
            <Button onClick={() => setConfirmRevoke(false)}>Cancel</Button>
            <Button variant="filled" onClick={doRevoke}>
              Revoke
            </Button>
          </>
        }
      >
        <p>Daily sync for your stake will stop. Re-enroll anytime by signing in again.</p>
      </Modal>

      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
      <ContactDialog open={contactOpen} onClose={() => setContactOpen(false)} />
      {/* expose the support dialogs to Settings via context-free location state would be heavier;
          Settings opens its own copies. These remain for parity if invoked from the shell. */}
    </div>
  );
}

/** App-bar title that doubles as a stake switcher when >1 stake is visible. Mirrors `_StakeTitle`. */
function StakeTitle() {
  const d = useDashboard();
  const fallback = d.stakeName ?? 'Covenant Path';
  if (d.stakes.length < 2) {
    return <h1 className="appbar__title">{fallback}</h1>;
  }
  const items: MenuItem[] = d.stakes.map((s) => ({
    value: s.id,
    label: String(s.name ?? '—'),
    checked: s.id === d.currentStakeId,
  }));
  return (
    <Menu
      label="Switch stake"
      align="left"
      items={items}
      onSelect={(id) => d.switchStake(id)}
      trigger={({ toggle, open, controls }) => (
        <button
          type="button"
          className="appbar__title"
          style={{ background: 'transparent', border: 'none', display: 'inline-flex', alignItems: 'center', gap: 2, color: 'inherit' }}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={controls}
          title="Switch stake"
          onClick={toggle}
        >
          {fallback}
          <Icon name="arrow_down" size={18} />
        </button>
      )}
    />
  );
}

// ---- Support dialogs (feedback / contact) — used by Settings, kept here for shell parity --------

export function FeedbackDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [summary, setSummary] = useState('');
  const [details, setDetails] = useState('');
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!summary.trim()) return;
    setBusy(true);
    try {
      const token = await currentAccessToken();
      const adminClient = admin;
      void token;
      const res = await adminClient.feedback(summary.trim(), details.trim());
      toast.show({
        message: `Thanks! Filed issue #${res['number']}${res['copilot'] === true ? ' — assigned to Copilot' : ''}`,
      });
      setSummary('');
      setDetails('');
      onClose();
    } catch (e) {
      toast.show({ message: `Couldn't send feedback: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send feedback"
      hideClose
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="filled" loading={busy} onClick={send}>
            Send
          </Button>
        </>
      }
    >
      <label className="field" style={{ marginBottom: 8 }}>
        <span>Summary</span>
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <input className="input" autoFocus value={summary} onChange={(e) => setSummary(e.target.value)} />
      </label>
      <label className="field">
        <span>Details (optional)</span>
        <textarea className="textarea" rows={4} value={details} onChange={(e) => setDetails(e.target.value)} />
      </label>
    </Modal>
  );
}

export function ContactDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);

  async function send() {
    if (!body.trim()) return;
    setBusy(true);
    try {
      await broker.contact(subject.trim(), body.trim());
      toast.show({ message: 'Message sent — thank you!' });
      setSubject('');
      setBody('');
      onClose();
    } catch (e) {
      toast.show({ message: `Couldn't send: ${e instanceof Error ? e.message : e}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Contact support"
      hideClose
      actions={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="filled" loading={busy} onClick={send}>
            Send
          </Button>
        </>
      }
    >
      <p className="small">Send a message to the app owner. They'll reply to your sign-in email.</p>
      <label className="field" style={{ margin: '8px 0' }}>
        <span>Subject (optional)</span>
        <input className="input" value={subject} onChange={(e) => setSubject(e.target.value)} />
      </label>
      <label className="field">
        <span>How can we help?</span>
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <textarea className="textarea" autoFocus rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
    </Modal>
  );
}

/** Shared "add a passkey" action (used by Settings + the post-login nudge). */
export async function addPasskey(toast: ReturnType<typeof useToast>) {
  if (!passkey.available) {
    toast.show({ message: 'Passkeys are available in the web app.' });
    return;
  }
  try {
    await passkey.register();
    toast.show({ message: 'Passkey added — next time, sign in with a passkey (no password).' });
  } catch (e) {
    toast.show({ message: `Could not add passkey: ${e instanceof Error ? e.message : e}` });
  }
}
