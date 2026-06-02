// The "no members visible" empty state — React port of `_EmptyState` (dashboard_shell.dart). The
// message + action depend on the broker enrollment status (no role / revoked / first sync running).

import { signOut } from '../hooks/useAuth';
import { broker, type EnrollmentStatus } from '../lib/broker';
import { Icon } from './Icon';
import { Button } from './ui';

export function EmptyState({ enrollStatus }: { enrollStatus: EnrollmentStatus | null }) {
  const cred = enrollStatus?.credential;
  const hasNoRole = enrollStatus?.noRole === true;
  const churchLoginAvailable = broker.available;

  let title: string;
  let body: string;
  let action: React.ReactNode = null;

  if (enrollStatus == null) {
    title = 'No members visible';
    body = 'Access is scoped to your LCR calling. Sign in with the email your stake has on file.';
  } else if (hasNoRole && cred?.state === 'none') {
    if (churchLoginAvailable) {
      title = 'Set up stake sync';
      body =
        "Your stake hasn't set up Covenant Path yet. Sign in with your Church account to start daily data updates — signing in keeps your stake synced automatically.";
      action = (
        <Button variant="filled" icon="logout" onClick={() => void signOut()}>
          Sign in to enable sync
        </Button>
      );
    } else {
      title = 'Stake not set up';
      body =
        'Ask your stake leader to enable Covenant Path by signing in with their Church account. Once set up, sign in with your email code for access.';
    }
  } else if (cred?.state === 'revoked') {
    title = 'Sync paused';
    body = 'The daily sync credential for your stake has been revoked. Re-enroll to resume data updates.';
    if (churchLoginAvailable) {
      action = (
        <Button variant="outlined" icon="refresh" onClick={() => void signOut()}>
          Re-enroll
        </Button>
      );
    }
  } else if (cred?.state === 'active') {
    title = 'Setting up your stake…';
    body =
      "Your credential is saved and the first sync is running — your stake's data will appear here in a few minutes. Refresh to check. (It also refreshes daily at 7 am ET.)";
  } else {
    title = 'No members visible';
    body = 'Access is derived from your LCR calling. Sign in with the email your stake has on file.';
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
