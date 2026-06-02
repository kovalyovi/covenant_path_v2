// The grouped Settings screen — React port of settings_page.dart. Appearance (theme cycle),
// Security (add a passkey, when supported), Support (contact / feedback), About (about & privacy,
// rules & definitions), and Account (signed-in email, sign out).

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { signOut } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { passkey } from '../lib/passkey';
import { Icon, type IconName } from '../components/Icon';
import { IconButton } from '../components/ui';
import { AboutDialog, RulesDialog } from '../components/Disclaimer';
import { ContactDialog, FeedbackDialog, addPasskey } from './DashboardShell';
import { useToast } from '../components/Toast';

export function SettingsPage() {
  const navigate = useNavigate();
  const theme = useTheme();
  const toast = useToast();
  const [aboutOpen, setAboutOpen] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [resolvedEmail, setResolvedEmail] = useState<string>('');

  // Resolve the signed-in email once.
  useEffect(() => {
    void supabase.auth.getUser().then(({ data }) => setResolvedEmail(data.user?.email ?? '—'));
  }, []);

  return (
    <div className="app-shell">
      <header className="appbar">
        <IconButton icon="chevron_left" label="Back" onClick={() => navigate(-1)} />
        <h1 className="appbar__title">Settings</h1>
      </header>
      <main className="page">
        <div className="maxw" style={{ paddingBottom: 24 }}>
          <SectionHead>Appearance</SectionHead>
          <Tile icon="brightness" title="Theme" subtitle={theme.label} onClick={theme.cycle} chevron />
          <hr className="divider" style={{ margin: 0 }} />

          <SectionHead>Security</SectionHead>
          {passkey.available && (
            <Tile
              icon="key"
              title="Add a passkey"
              subtitle="Recommended — sign in with your face, fingerprint, or PIN instead of a password"
              onClick={() => void addPasskey(toast)}
            />
          )}
          {!passkey.available && (
            <Tile icon="shield" title="No extra security options in this browser" subtitle="" />
          )}
          <hr className="divider" style={{ margin: 0 }} />

          <SectionHead>Support</SectionHead>
          <Tile icon="support" title="Contact support" subtitle="Message the app owner" onClick={() => setContactOpen(true)} />
          <Tile icon="feedback" title="Send feedback" subtitle="Report a bug or suggest an improvement" onClick={() => setFeedbackOpen(true)} />
          <hr className="divider" style={{ margin: 0 }} />

          <SectionHead>About</SectionHead>
          <Tile icon="info" title="About & privacy" onClick={() => setAboutOpen(true)} />
          <Tile icon="rule" title="Rules & definitions" subtitle="Eligibility, data access & convert-care" onClick={() => setRulesOpen(true)} />
          <hr className="divider" style={{ margin: 0 }} />

          <SectionHead>Account</SectionHead>
          <Tile icon="account" title="Signed in as" subtitle={resolvedEmail || '—'} />
          <Tile
            icon="logout"
            title="Sign out"
            danger
            onClick={() => {
              navigate('/');
              void signOut();
            }}
          />
        </div>
      </main>

      <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} />
      <RulesDialog open={rulesOpen} onClose={() => setRulesOpen(false)} />
      <ContactDialog open={contactOpen} onClose={() => setContactOpen(false)} />
      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </div>
  );
}

function SectionHead({ children }: { children: string }) {
  return <h2 className="settings-section-head">{children}</h2>;
}

function Tile({
  icon,
  title,
  subtitle,
  onClick,
  chevron,
  danger,
}: {
  icon: IconName;
  title: string;
  subtitle?: string;
  onClick?: () => void;
  chevron?: boolean;
  danger?: boolean;
}) {
  const color = danger ? 'var(--error)' : undefined;
  const content = (
    <>
      <Icon name={icon} size={22} color={color} />
      <span className="list-tile__main">
        <span style={{ color }}>{title}</span>
        {subtitle && (
          <span className="small muted" style={{ display: 'block' }}>
            {subtitle}
          </span>
        )}
      </span>
      {chevron && <Icon name="chevron_right" size={18} />}
    </>
  );
  if (onClick) {
    return (
      <button type="button" className="list-tile" onClick={onClick}>
        {content}
      </button>
    );
  }
  return <div className="list-tile">{content}</div>;
}
