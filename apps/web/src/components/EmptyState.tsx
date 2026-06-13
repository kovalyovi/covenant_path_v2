// The "no members visible" empty state — React port of `_EmptyState` (dashboard_shell.dart). The
// message + action depend on the broker enrollment status (no role / revoked / first sync running).

import { broker, type EnrollmentStatus } from '../lib/broker';
import { useDashboard } from '../hooks/useDashboard';
import { fmtEtHourLocal } from '../logic/dates';
import { Icon } from './Icon';
import { Button } from './ui';

export function EmptyState({ enrollStatus }: { enrollStatus: EnrollmentStatus | null }) {
  const d = useDashboard();
  const cred = enrollStatus?.credential;
  const hasNoRole = enrollStatus?.noRole === true;
  const churchLoginAvailable = broker.available;
  // In-app re-auth modal (never bounce a signed-in user back to the login screen).
  const authorize = () => d.openReauth();

  let title: string;
  let body: string;
  let action: React.ReactNode = null;

  if (enrollStatus == null) {
    // Signed in (e.g. via the email code) but the broker couldn't resolve any stake/role for this
    // email — it isn't linked yet. Name the TWO ways in, not the dead-end "sign in with the right
    // email" (they ARE signed in): a stake leader invites them, OR one Church login binds them.
    title = 'No stake linked to this sign-in';
    body =
      "You're signed in, but this email isn't linked to a stake yet. Ask your stake leader to invite " +
      'you, or — if you have a stake calling — sign in once with your Church account to link it ' +
      'automatically.';
  } else if (hasNoRole && enrollStatus.stakeName) {
    // Released-or-no-access member of a KNOWN stake (resolved via the broker's identity cache —
    // ADR-009 amendment G): tell the truth. Without this branch they fell into "Set up stake
    // sync" (their stake IS set up) or "Setting up your stake…" (nothing is coming for them).
    title = 'No access with your current calling';
    body =
      `${enrollStatus.stakeName} is synced with Covenant Path, but your current calling doesn't ` +
      'grant access to its member data. If you were recently released, access ends automatically. ' +
      'If this seems wrong, contact your stake leadership.';
  } else if (hasNoRole && cred?.state === 'none') {
    // No role AND no stake we can name — this email isn't linked to a stake. Two true paths in, and
    // we can't tell a brand-new-stake LEADER from an unlinked VIEWER, so present both: a leader signs
    // in with their Church account (sets up sync / binds their calling); a viewer asks to be invited.
    if (churchLoginAvailable) {
      title = 'Link your stake access';
      body =
        "You're signed in, but this email isn't linked to a stake yet. If your stake already uses " +
        'Covenant Path, ask a stake leader to invite you by email. If you lead the stake, sign in ' +
        'with your Church account to set it up — that also links your calling.';
      action = (
        <Button variant="filled" icon="key" onClick={authorize}>
          Sign in with Church account
        </Button>
      );
    } else {
      title = 'Not linked to a stake yet';
      body =
        'Ask your stake leader to invite you by email, or to set up Covenant Path with their Church ' +
        'account. Once your email is linked, this code sign-in shows your stake.';
    }
  } else if (cred?.state === 'revoked') {
    title = 'Sync paused';
    body = 'The daily sync credential for your stake has been revoked. Re-authorize to resume data updates.';
    if (churchLoginAvailable) {
      action = (
        <Button variant="outlined" icon="refresh" onClick={authorize}>
          Re-authorize
        </Button>
      );
    }
  } else if (cred?.state === 'stale') {
    title = 'Sync needs re-authorization';
    body =
      "This stake's daily sync stopped — the Church session that keeps it updated expired. Re-authorize with your Church account to resume updates.";
    if (churchLoginAvailable) {
      action = (
        <Button variant="filled" icon="refresh" onClick={authorize}>
          Re-authorize
        </Button>
      );
    }
  } else if (cred?.state === 'active') {
    title = 'Setting up your stake…';
    // The default daily-sync hour is 7 ET — shown in the viewer's local time.
    body = `Your credential is saved and the first sync is running — your stake's data will appear here in a few minutes. Refresh to check. (It also refreshes daily at ${fmtEtHourLocal(7)}.)`;
  } else {
    title = 'No stake linked to this sign-in';
    body =
      "You're signed in, but this email isn't linked to a stake yet. Ask your stake leader to invite " +
      'you, or sign in once with your Church account to link your calling automatically.';
  }

  return (
    <div className="center-col" style={{ minHeight: '60vh' }}>
      <Icon name="group_outline" size={56} color="var(--primary)" style={{ opacity: 0.4 }} />
      <h2 style={{ fontSize: '1.1rem' }}>{title}</h2>
      <p className="muted" style={{ maxWidth: 420 }}>
        {body}
      </p>
      {action}
    </div>
  );
}
