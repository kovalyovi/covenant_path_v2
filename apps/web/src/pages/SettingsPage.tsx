// The grouped Settings screen — React port of settings_page.dart. Appearance (theme cycle),
// Preferences, Security (add a passkey, when supported), Support (contact / feedback), About, and
// Account (signed-in email + the user's stake / unit(s) / calling(s) / rights, sign out).
//
// Settings is presented as a right SIDE SHEET over the dashboard (see DashboardShell), so this file
// renders the sheet BODY only — no app-shell/appbar of its own (the Modal supplies the title +
// close). It stays URL-landable at /settings (a refresh lands on the dashboard with this sheet open).

import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { signOut } from '../hooks/useAuth';
import { useTheme } from '../hooks/useTheme';
import { useDashboard } from '../hooks/useDashboard';
import { passkey } from '../lib/passkey';
import { Icon, type IconName } from '../components/Icon';
import { AboutDialog, RulesDialog } from '../components/Disclaimer';
import { ContactDialog, FeedbackDialog, addPasskey } from './DashboardShell';
import { useToast } from '../components/Toast';

/** A resolved role row (user_roles + joined unit/stake names) for the account section. */
interface AccountRole {
  role: string;
  callingName: string | null;
  unitId: string | null;
  unitName: string | null;
  stakeId: string | null;
  stakeName: string | null;
}

/** Pretty role label + what level of rights it grants. A stake-level role (no unit) sees the whole
 *  stake; a unit-level role sees that unit only. */
function rightsFor(r: AccountRole): { label: string; rights: string } {
  const stake = r.stakeName ?? 'your stake';
  const unit = r.unitName ?? 'your unit';
  const role = (r.role ?? '').toLowerCase();
  const stakeLevel = r.unitId == null || role.includes('stake');
  if (stakeLevel) {
    return { label: prettyRole(r.role) || 'Stake leader', rights: `Sees all units in ${stake}` };
  }
  return { label: prettyRole(r.role) || 'Ward leader', rights: `Sees ${unit} only` };
}

function prettyRole(role: string): string {
  if (!role) return '';
  return role
    .split('_')
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(' ');
}

export function SettingsPage() {
  const theme = useTheme();
  const toast = useToast();
  const d = useDashboard();
  const { showNotes, setShowNotes, isAdmin } = d;
  const [aboutOpen, setAboutOpen] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [resolvedEmail, setResolvedEmail] = useState<string>('');
  const [roles, setRoles] = useState<AccountRole[] | null>(null);

  // Resolve the signed-in email once.
  useEffect(() => {
    void supabase.auth.getUser().then(({ data }) => setResolvedEmail(data.user?.email ?? '—'));
  }, []);

  // Resolve the signed-in user's role(s) — stake / unit / calling / rights. RLS scopes user_roles to
  // the signed-in user; join units + stakes for display names. Best-effort: any error → no role block
  // (the email line still shows). A power user / no-role login simply yields an empty list.
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { data, error } = await supabase
          .from('user_roles')
          .select('role, calling_name, unit_id, stake_id, units(name), stakes(name)');
        if (error) throw error;
        if (!active) return;
        const rows = (data ?? []) as Array<Record<string, unknown>>;
        const mapped: AccountRole[] = rows.map((r) => ({
          role: String(r['role'] ?? ''),
          callingName: (r['calling_name'] as string | null) ?? null,
          unitId: (r['unit_id'] as string | null) ?? null,
          unitName: joinedName(r['units']),
          stakeId: (r['stake_id'] as string | null) ?? null,
          stakeName: joinedName(r['stakes']),
        }));
        setRoles(mapped);
      } catch {
        if (active) setRoles([]);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return (
    <div style={{ paddingBottom: 24 }}>
      <SectionHead>Appearance</SectionHead>
      <Tile icon="brightness" title="Theme" subtitle={theme.label} onClick={theme.cycle} chevron />
      {/* #6a commit-2: preview the alternate "Refined" visual style live, then keep whichever you prefer. */}
      <Tile
        icon="favorite"
        title="Style"
        subtitle={theme.look === 'refined' ? 'Refined (preview)' : 'Classic'}
        onClick={() => theme.setLook(theme.look === 'refined' ? 'classic' : 'refined')}
        chevron
      />
      <hr className="divider" style={{ margin: 0 }} />

      <SectionHead>Preferences</SectionHead>
      {/* Filters/sorts/view choices now live in the URL (Back restores them; a refresh starts clean),
          so there's no longer a "remember preferences" switch. */}
      <ToggleTile
        icon="note"
        title="Show notes on member lists"
        subtitle="Display each member's note on the main screen"
        checked={showNotes}
        onChange={setShowNotes}
      />
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
      <AccessSummary roles={roles} isAdmin={isAdmin} fallbackStake={d.stakeName} />
      <Tile
        icon="logout"
        title="Sign out"
        danger
        onClick={() => {
          void signOut();
        }}
      />

      <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} />
      <RulesDialog open={rulesOpen} onClose={() => setRulesOpen(false)} />
      <ContactDialog open={contactOpen} onClose={() => setContactOpen(false)} />
      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </div>
  );
}

/** PostgREST embeds a to-one join as a nested object (or, defensively, a 1-element array). */
function joinedName(v: unknown): string | null {
  if (v == null) return null;
  if (Array.isArray(v)) return joinedName(v[0]);
  if (typeof v === 'object' && 'name' in (v as Record<string, unknown>)) {
    const n = (v as Record<string, unknown>)['name'];
    return n == null ? null : String(n);
  }
  return null;
}

/** The "what can I see" block: stake, unit(s), calling(s), and the rights each grants — plus an admin
 *  badge. Renders nothing extra (just the loading/empty hint) until roles resolve. */
function AccessSummary({
  roles,
  isAdmin,
  fallbackStake,
}: {
  roles: AccountRole[] | null;
  isAdmin: boolean;
  fallbackStake: string | null;
}) {
  if (roles == null) {
    return (
      <div className="list-tile" aria-busy="true">
        <Icon name="shield" size={22} />
        <span className="list-tile__main">
          <span>Access</span>
          <span className="small muted" style={{ display: 'block' }}>Loading your access…</span>
        </span>
      </div>
    );
  }

  // A power user / no-LCR-role login resolves to no user_roles rows — be honest about it.
  if (roles.length === 0) {
    return (
      <div className="list-tile" style={{ alignItems: 'flex-start' }}>
        <Icon name="shield" size={22} />
        <span className="list-tile__main">
          <span>Access</span>
          <span className="small muted" style={{ display: 'block' }}>
            {fallbackStake
              ? `Viewing ${fallbackStake}. No specific calling on file — access was granted directly (power user).`
              : 'No specific calling on file — access was granted directly (power user).'}
          </span>
          {isAdmin && <AdminBadge />}
        </span>
      </div>
    );
  }

  // Group by stake so multi-unit / multi-calling people read cleanly. Most logins have one stake.
  const byStake = new Map<string, AccountRole[]>();
  for (const r of roles) {
    const key = r.stakeName ?? r.stakeId ?? '—';
    const arr = byStake.get(key) ?? [];
    arr.push(r);
    byStake.set(key, arr);
  }

  return (
    <div className="list-tile" style={{ alignItems: 'flex-start' }}>
      <Icon name="shield" size={22} />
      <span className="list-tile__main">
        <span>Access</span>
        {[...byStake.entries()].map(([stakeKey, stakeRoles]) => (
          <span key={stakeKey} style={{ display: 'block', marginTop: 4 }}>
            <span className="small" style={{ fontWeight: 600 }}>{stakeKey}</span>
            {stakeRoles.map((r, i) => {
              const { label, rights } = rightsFor(r);
              const calling = r.callingName ?? label;
              return (
                <span key={i} className="small muted" style={{ display: 'block' }}>
                  {calling} — {rights}
                </span>
              );
            })}
          </span>
        ))}
        {isAdmin && <AdminBadge />}
      </span>
    </div>
  );
}

function AdminBadge() {
  return (
    <span className="chip" style={{ marginTop: 6, fontSize: 12 }}>
      <Icon name="shield" size={14} />
      App admin — ops console access
    </span>
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

/** A settings row with a right-aligned on/off switch (item 9 preferences). */
function ToggleTile({
  icon,
  title,
  subtitle,
  checked,
  onChange,
}: {
  icon: IconName;
  title: string;
  subtitle?: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label className="list-tile" style={{ cursor: 'pointer' }}>
      <Icon name={icon} size={22} />
      <span className="list-tile__main">
        <span>{title}</span>
        {subtitle && (
          <span className="small muted" style={{ display: 'block' }}>
            {subtitle}
          </span>
        )}
      </span>
      <input
        type="checkbox"
        role="switch"
        className="switch"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={title}
      />
    </label>
  );
}
