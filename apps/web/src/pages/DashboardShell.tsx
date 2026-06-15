// The dashboard scaffold — React port of `_DashboardPageState.build` + `_appBarActions`. App bar
// with a stake-switcher title (when >1 stake is visible), a freshness chip, Refresh, and a "⋯" menu
// (Sync settings / Generate report / Invite / Admin / Settings). Responsive nav: a side rail on
// tablet/desktop, a frosted bottom nav on mobile. Hosts the syncing/stale banners and the sheets.

import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useDashboard } from '../hooks/useDashboard';
import { useTier } from '../hooks/useTier';
import { signOut } from '../hooks/useAuth';
import { broker } from '../lib/broker';
import { admin } from '../lib/admin';
import { currentAccessToken } from '../lib/supabase';
import { lazyWithReload } from '../lib/lazyReload';
import { passkey } from '../lib/passkey';
import { TABS } from '../theme/tokens';
import { Icon, type IconName } from '../components/Icon';
import { IconButton, Spinner } from '../components/ui';
import { Menu, type MenuItem } from '../components/Menu';
import {
  SyncingBanner, StaleBanner, PatriarchalBanner, LastUpdatedChip,
} from '../components/dashboard';
import { SyncSettingsSheet } from '../components/SyncSettingsSheet';
import { PowerUserSheet } from '../components/PowerUserSheet';
import { ReauthDialog } from '../components/ReauthDialog';
import { ReportSheet } from '../components/ReportSheet';
import { useToast } from '../components/Toast';
import { Modal } from '../components/Modal';
import { Button } from '../components/ui';
import { AdminSkeleton } from '../components/Skeletons';
import { SettingsPage } from './SettingsPage';
import { PersonDetailBody, personLcrUrl } from './PersonDetailPage';

// Settings + Admin render as side sheets OVER the dashboard (see router). The console is heavy
// (dense tables) + rarely opened, so its content is code-split out of the dashboard bundle and lazy-
// loaded inside the sheet — the same chunks the standalone routes used.
const AdminPage = lazy(lazyWithReload(() => import('./AdminPage').then((m) => ({ default: m.AdminPage }))));
const AdminListPage = lazy(lazyWithReload(() => import('./AdminListPage').then((m) => ({ default: m.AdminListPage }))));

export function DashboardShell() {
  const d = useDashboard();
  const tier = useTier();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();

  const [syncOpen, setSyncOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false); // #5: power-user sheet
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [adminNonce, setAdminNonce] = useState(0); // #28: header Refresh remounts the console → reloads all panels
  // Mobile: hide the bottom nav while scrolling DOWN, reveal it when scrolling back up.
  const [navHidden, setNavHidden] = useState(false);
  const lastScrollY = useRef(0);
  function onPageScroll(e: React.UIEvent<HTMLElement>) {
    const y = e.currentTarget.scrollTop;
    const last = lastScrollY.current;
    if (y > last + 6 && y > 56) setNavHidden(true);
    else if (y < last - 6) setNavHidden(false);
    lastScrollY.current = y;
  }

  // Settings + Admin are URL-driven side sheets overlaying the dashboard. They're "open" purely as a
  // function of the path, so a deep link / refresh on /settings or /admin lands on the dashboard with
  // the sheet open (the route renders the default tab underneath). Closing navigates back to the tab
  // the user was on (remembered below), so the URL updates and Back/forward work.
  const path = location.pathname;
  const settingsOpen = path === '/settings';
  const adminOpen = path === '/admin' || path.startsWith('/admin/');
  const adminSection = path.startsWith('/admin/') ? path.slice('/admin/'.length) : '';
  // Person detail is a URL-landable side/bottom sheet too. Parse the id from the path (not useParams,
  // since the matched route element is BackgroundTab, not this shell), and the optional ?editNote.
  const personMatch = /^\/person\/(.+)$/.exec(path);
  const personId = personMatch ? decodeURIComponent(personMatch[1]) : null;
  const personOpen = personId != null;
  const editNote = new URLSearchParams(location.search).get('editNote') === '1';
  const personMember = personId != null
    ? d.members.find((m) => String(m['person_uuid'] ?? '') === personId)
    : undefined;
  const personTitle = personMember ? String(personMember['name'] ?? 'Member') : 'Member';
  const anyOverlay = settingsOpen || adminOpen || personOpen;

  // Remember the last real tab so closing a sheet returns there AND the sheet renders that tab as its
  // backdrop (BackgroundTab in router.tsx reads this) — opening Settings/Admin no longer resets the
  // view to Baptisms. Persisted to sessionStorage so a URL-landed sheet still shows the right backdrop.
  const lastTabRef = useRef<string>('/baptisms');
  if (!anyOverlay && path !== '/') {
    lastTabRef.current = path;
    try { sessionStorage.setItem('cp:lastTab', path); } catch { /* private mode */ }
  }
  const closeOverlay = () => navigate(lastTabRef.current || '/baptisms');

  // #34: filter/view state lives in the URL query string so Back restores previous states. On a FRESH
  // page load we start clean — strip any params present at load (so a refresh resets to defaults rather
  // than resurrecting the last session's filters). Runs once; in-session changes still push params.
  const strippedRef = useRef(false);
  useEffect(() => {
    if (strippedRef.current) return;
    strippedRef.current = true;
    if (window.location.search) navigate(`${window.location.pathname}${window.location.hash}`, { replace: true });
  }, [navigate]);

  const credState = d.enrollStatus?.credential.state;
  // Show the banner for a REVOKED credential or a STALE one (its delegated session died → sync failing).
  const showStaleBanner = credState === 'revoked' || credState === 'stale';
  // For a HEALTHY credential, nudge the provider (whose calling can read profiles) to re-authorize and
  // refresh patriarchal blessing — the one field the daily sync can't pull. Suppressed when the
  // stale/revoked banner already prompts re-auth (which refreshes it too). GRACE WINDOW: patriarchal
  // is a one-time ordinance, so it's fine for it to be up to 2 weeks stale — once a re-auth has run
  // (credential.enrolledAt = its updated_at), stay quiet for 14 days instead of nagging again on the
  // next load (the "I refreshed but the banner didn't go away" report).
  const cred = d.enrollStatus?.credential;
  const REFRESH_GRACE_DAYS = 14;
  const lastReauthMs = cred?.enrolledAt ? new Date(cred.enrolledAt).getTime() : 0;
  const patriarchalStale =
    !lastReauthMs || Date.now() - lastReauthMs > REFRESH_GRACE_DAYS * 24 * 60 * 60 * 1000;
  const showPatriarchalBanner =
    !showStaleBanner &&
    !d.syncing &&
    broker.available &&
    cred?.isProvider === true &&
    cred?.canRefreshPatriarchal === true &&
    patriarchalStale &&
    (d.enrollStatus?.patriarchalPending ?? 0) > 0;

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
    // Open the report sheet IMMEDIATELY and load INSIDE it (spinner over the sheet body) — no
    // full-screen scrim blocking the whole app while the broker builds the report.
    setReport(null);
    setReportLoading(true);
    try {
      const rep = await broker.report();
      setReport(rep);
    } catch (e) {
      setReportLoading(false);
      toast.show({ message: `Couldn't build report: ${e instanceof Error ? e.message : e}` });
      return;
    }
    setReportLoading(false);
  }

  function closeReport() {
    setReport(null);
    setReportLoading(false);
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
      // Refetch so the REVOKER sees the revoked state immediately (banner + settings) — nulling
      // alone left the UI unchanged until a full reload (caught by the fullstack e2e lane).
      void d.reloadEnrollStatus();
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
      case 'invite': return setInviteOpen(true);
      // Navigate so the URL updates → Settings/Admin open as URL-landable side sheets (Back/refresh work).
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
        {/* #2: a real tooltip + a visible PENDING state — the icon spins while the latest data reloads
            (the button used to give no feedback, so it felt like it did nothing). */}
        {d.refreshing ? (
          <span className="iconbtn" aria-label="Refreshing data" title="Refreshing data" aria-busy="true">
            <Spinner />
          </span>
        ) : (
          <IconButton icon="refresh" label="Refresh data" onClick={() => void d.refresh()} />
        )}
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
      {showStaleBanner && (
        <StaleBanner
          state={credState as string}
          isProvider={d.enrollStatus?.credential.isProvider === true}
          lastError={d.enrollStatus?.credential.lastError ?? null}
          // In-app re-auth modal — never bounce a signed-in user back to the login screen.
          onReenroll={broker.available ? d.openReauth : () => void signOut()}
          onSyncNow={broker.available ? syncNow : undefined}
        />
      )}
      {showPatriarchalBanner && (
        <PatriarchalBanner
          pending={d.enrollStatus?.patriarchalPending ?? 0}
          onRefresh={d.openReauth}
        />
      )}
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
        {/* When a side sheet (Settings/Admin) is open, the tab behind it is just a static backdrop —
            don't replay its entrance animation (that was the "blink" behind the sheet). */}
        <main
          id="main"
          className={`page${anyOverlay ? ' page--backdrop' : ''}`}
          aria-label="Dashboard content"
          onScroll={tier === 'mobile' ? onPageScroll : undefined}
        >
          {banners}
          <Outlet />
        </main>
      </div>
      {tier === 'mobile' && (
        <nav className={`bottomnav${navHidden ? ' bottomnav--hidden' : ''}`} aria-label="Primary">
          {/* #31: a sliding indicator that glides to the active tab (hidden when a sheet route has no
              active tab). Width = one slot; it translates by activeIndex slots. */}
          {(() => {
            const activeIndex = TABS.findIndex((t) => location.pathname === `/${t.path}`);
            return (
              <span
                className="bottomnav__indicator"
                aria-hidden="true"
                style={{
                  width: `${100 / TABS.length}%`,
                  transform: `translateX(${Math.max(0, activeIndex) * 100}%)`,
                  opacity: activeIndex < 0 ? 0 : 1,
                }}
              />
            );
          })()}
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
        onReauth={d.openReauth}
      />
      <ReauthDialog open={d.reauthOpen} onClose={d.closeReauth} />
      <PowerUserSheet open={inviteOpen} onClose={() => setInviteOpen(false)} />
      {/* Report flow loads INSIDE a side sheet (spinner over the body) — never a full-screen block.
          While the broker builds it we show a loading side sheet; once it arrives, the real
          ReportSheet replaces it. */}
      {reportLoading && !report && (
        <Modal open side title="Generating report" loading onClose={closeReport}>
          <span />
        </Modal>
      )}
      {report && <ReportSheet open onClose={closeReport} report={report} onEmail={emailReport} />}

      {/* Person detail, Settings + Admin all overlay the dashboard as URL-landable side sheets
          (open is path-driven; on phones the `side` variant falls back to a bottom sheet). */}
      <Modal
        open={personOpen}
        side
        wide
        title={personTitle}
        onClose={closeOverlay}
        headerExtra={personId ? (
          <a
            className="iconbtn"
            href={personLcrUrl(personId)}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Open this person in LCR"
            title="Open this person in LCR"
          >
            <Icon name="open_in_new" size={20} />
          </a>
        ) : undefined}
      >
        {personOpen && personId && <PersonDetailBody id={personId} autoEdit={editNote} />}
      </Modal>

      <Modal open={settingsOpen} side title="Settings" onClose={closeOverlay}>
        {settingsOpen && <SettingsPage />}
      </Modal>
      {adminOpen && adminSection ? (
        // Admin sub-list (full history): its own app-bar acts as the header → render bare + wide.
        <Modal open side wide bare title="Admin" onClose={closeOverlay}>
          <Suspense fallback={<AdminSkeleton />}>
            <AdminListPage />
          </Suspense>
        </Modal>
      ) : (
        // Refresh lives INLINE in the title row (next to ×), not on its own row — it remounts the
        // console (key) so every panel reloads. The lazy chunk loads behind section-shaped skeletons.
        <Modal
          open={adminOpen}
          side
          wide
          title="Admin · Ops console"
          onClose={closeOverlay}
          headerExtra={<IconButton icon="refresh" label="Refresh" onClick={() => setAdminNonce((n) => n + 1)} size={20} />}
        >
          {adminOpen && (
            <Suspense fallback={<AdminSkeleton />}>
              <AdminPage key={adminNonce} embedded />
            </Suspense>
          )}
        </Modal>
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
