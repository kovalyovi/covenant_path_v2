// Admin · Ops console — React port of admin_page.dart. One place to monitor and operate the
// platform, gated server-side by app_admins (the broker checks with the service-role key). Panels
// load independently so a slow/failed section (e.g. GitHub Actions) only errors in its own card.
// Panels, in order (day-to-day ops first): system health/freshness/maintenance, enrolled stakes
// (cross-stake ops + per-stake sync/revoke, with re-auth + visibility worklists), recent logins,
// admin management, diagnostics, endpoint health trend, recent Actions runs, changelog, calling
// overrides.

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { admin } from '../lib/admin';
import { status as statusColors } from '../theme/tokens';
import { agoOrNever, dur, fmtDateTime } from '../logic/dates';
import { fieldGapSeries, humanizeField } from '../logic/fieldGaps';
import { Icon } from '../components/Icon';
import { IconButton, Button } from '../components/ui';
import { CardSkeleton } from '../components/Skeletons';
import { Modal } from '../components/Modal';
import { useToast } from '../components/Toast';
import { MaskedEmail, ViewAllLink } from './AdminListPage';

type Json = Record<string, unknown>;

function openUrl(url?: string) {
  if (url) window.open(url, '_blank', 'noopener');
}

/** When `embedded`, the console renders inside the dashboard's wide side sheet — the sheet supplies
 *  the title + close, so we drop our own app-shell/appbar chrome (just a Refresh control in a header
 *  row). Standalone (deep-link without the shell, kept for safety) still renders the full page. */
export function AdminPage({ embedded = false }: { embedded?: boolean } = {}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [nonce, setNonce] = useState(0); // bump to reload all panels

  const refresh = () => setNonce((n) => n + 1);

  const guard = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      try {
        await action();
      } catch (e) {
        toast.show({ message: String(e instanceof Error ? e.message : e) });
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );

  const [confirm, setConfirm] = useState<{ title: string; body: string; onYes: () => void; yesLabel: string } | null>(null);
  const ask = (title: string, body: string, yesLabel: string, onYes: () => void) => setConfirm({ title, body, yesLabel, onYes });

  function dispatch(label: string, body: string, inputs: Json) {
    ask(`${label}?`, `${body} It runs in the cloud (GitHub Actions) and takes a few minutes.`, label, () =>
      guard(async () => {
        await admin.run('daily-sync.yml', inputs);
        toast.show({ message: `${label} dispatched. Refresh in a minute to see the run.` });
        refresh();
      }),
    );
  }

  function rerun(id: number) {
    void guard(async () => {
      await admin.rerun(id);
      toast.show({ message: `Re-run requested for #${id}.` });
      refresh();
    });
  }

  function revokeStake(stakeId: string, name: string) {
    ask('Revoke sync for ' + name + '?', 'Daily sync for this stake will stop until a leader re-enrolls. You can do this to support a stake whose credential is stale or compromised.', 'Revoke', () =>
      guard(async () => {
        await admin.revokeStake(stakeId);
        toast.show({ message: `Revoked sync for ${name}.` });
        refresh();
      }),
    );
  }

  function syncStake(unit: string, name: string) {
    if (!unit || unit === 'null') {
      toast.show({ message: `No unit number on file for ${name} — can't scope a sync.` });
      return;
    }
    ask(`Sync ${name} now?`, 'Re-scrapes LCR for this one stake and writes to Supabase. Runs in the cloud (GitHub Actions) and takes a few minutes.', 'Sync', () =>
      guard(async () => {
        await admin.run('daily-sync.yml', { stake: unit, targets: 'supabase' });
        toast.show({ message: `Sync dispatched for ${name}. Refresh in a minute to see the run.` });
        refresh();
      }),
    );
  }

  function wipeStakeData(stakeId: string, name: string) {
    ask(`Wipe ${name}'s data?`,
      `Deletes ALL of this stake's member records — but KEEPS the stake, its leaders' access, and the sync credential. The data re-populates on the next sync. Use this to clear out bad or partial data.`,
      'Wipe data', () =>
      guard(async () => {
        await admin.wipeStakeData(stakeId);
        toast.show({ message: `Wiped member data for ${name}.` });
        refresh();
      }),
    );
  }

  function removeStake(stakeId: string, name: string) {
    ask(`Permanently remove ${name}?`,
      `DELETES EVERYTHING for this stake — the sync credential, ALL member data, every leader's access role, and the stake itself, as if it never onboarded. This CANNOT be undone.`,
      'Remove everything', () =>
      guard(async () => {
        await admin.removeStake(stakeId);
        toast.show({ message: `Removed ${name} completely.` });
        refresh();
      }),
    );
  }

  function sendReauth(stakeId: string, name: string) {
    void guard(async () => {
      const res = await admin.reauthEmail(stakeId);
      const to = res['to'] ? ` to ${String(res['to'])}` : '';
      toast.show({ message: `Re-authorization email sent${to} for ${name}.` });
    });
  }

  async function inviteAdmin(emailVal: string) {
    await guard(async () => {
      const res = await admin.invite(emailVal);
      const st = res['status'];
      toast.show({
        message:
          st === 'already_admin'
            ? `${emailVal} is already an admin.`
            : st === 'pending_owner_approval'
              ? `Request sent — the owner must approve ${emailVal} by email.`
              : `${emailVal}: ${st}`,
      });
      refresh();
    });
  }

  function revokeAdmin(emailVal: string) {
    void guard(async () => {
      await supabase.rpc('revoke_admin', { p_email: emailVal });
      toast.show({ message: `Revoked ${emailVal}.` });
      refresh();
    });
  }

  function addOverride(match: string, grants: boolean, note: string) {
    void guard(async () => {
      const { error } = await supabase.rpc('add_calling_override', { p_match: match, p_grants: grants, p_note: note || null });
      if (error) throw error;
      toast.show({ message: `Saved override "${match}".` });
      refresh();
    });
  }

  function removeOverride(id: number, match: string) {
    void guard(async () => {
      const { error } = await supabase.rpc('remove_calling_override', { p_id: id });
      if (error) throw error;
      toast.show({ message: `Removed "${match}".` });
      refresh();
    });
  }

  const panels = (
    <>
        <div className="maxw" style={{ maxWidth: 900, padding: 12 }}>
          <Panel key={`sys-${nonce}`} title="System" load={() => admin.summary()}>
            {(s) => (
              <>
                <SystemHealthCard summary={s} />
                <FreshnessCard summary={s} />
                <MaintenanceCard summary={s} busy={busy} onRun={dispatch} />
              </>
            )}
          </Panel>
          {/* Day-to-day ops surfaces lead: enrolled stakes (+ re-auth/visibility worklists) and recent
              logins sit ABOVE the deeper Diagnostics so the "did sync run? who can't see anything?"
              signals are the first thing an admin sees (A4). */}
          <Panel key={`stakes-${nonce}`} title="Enrolled stakes" load={() => admin.enrolledStakes()}>
            {(s) => {
              const stakes = (s['stakes'] as Json[]) ?? [];
              return (
                <>
                  {/* B2: a worklist of stakes needing action, derived from the SAME fetched array. */}
                  <ReauthWorklistCard stakes={stakes} busy={busy} onReauth={sendReauth} />
                  <EnrolledStakesCard
                    stakes={stakes}
                    busy={busy}
                    onRevoke={revokeStake}
                    onSync={syncStake}
                    onWipe={wipeStakeData}
                    onRemove={removeStake}
                    onReauth={sendReauth}
                  />
                </>
              );
            }}
          </Panel>
          <Panel
            key={`logins-${nonce}`}
            title="Recent logins"
            load={async () => {
              const { data } = await supabase
                .from('login_audit')
                .select('at, email, name, stake_name, callings, role_scope, authorized, outcome')
                .order('at', { ascending: false })
                .limit(50);
              return { logins: (data ?? []) as Json[] };
            }}
            errorHint="login_audit is admin-only (RLS) — rows appear once the broker records logins after its next deploy."
          >
            {(s) => <LoginAuditCard logins={(s['logins'] as Json[]) ?? []} />}
          </Panel>
          {/* B4: leaders who signed in but resolve to NO scope (empty app) — the exact people to bind. */}
          <Panel
            key={`visibility-${nonce}`}
            title="Signed in but sees nothing"
            load={async () => {
              const { data } = await supabase
                .from('login_audit')
                .select('at, email, name, stake_name, callings, role_scope, outcome')
                .eq('outcome', 'allowed')
                .eq('role_scope', 'none')
                .order('at', { ascending: false })
                .limit(100);
              return { rows: (data ?? []) as Json[] };
            }}
            errorHint="login_audit is admin-only (RLS) — rows appear once the broker records logins after its next deploy."
          >
            {(s) => <VisibilityWorklistCard rows={(s['rows'] as Json[]) ?? []} />}
          </Panel>
          <Panel
            key={`admins-${nonce}`}
            title="Admins"
            load={async () => {
              const { data } = await supabase.from('app_admins').select('email, invited_by_email');
              return { admins: (data ?? []) as Json[] };
            }}
          >
            {(s) => (
              <AdminsCard admins={(s['admins'] as Json[]) ?? []} busy={busy} onInvite={inviteAdmin} onRevoke={revokeAdmin} />
            )}
          </Panel>
          {/* Per-day aggregation of which fields are still missing (PII-free, all stakes) — sits in the
              middle of the console, above the single-run Diagnostics, so the "track these numbers over
              time" signal is scannable at a glance. */}
          <Panel key={`fieldgaps-${nonce}`} title="Field gaps (per day)" load={() => admin.diagnostics()}>
            {(s) => <FieldGapsCard diag={s} />}
          </Panel>
          <Panel key={`diag-${nonce}`} title="Diagnostics" load={() => admin.diagnostics()}>
            {(s) => <DiagnosticsCard diag={s} onCopy={(t) => navigator.clipboard.writeText(t)} toast={toast} />}
          </Panel>
          <Panel key={`ephealth-${nonce}`} title="Endpoint health (trend)" load={() => admin.endpointHealth(14)}>
            {(s) => <EndpointHealthCard data={s} />}
          </Panel>
          <Panel
            key={`actions-${nonce}`}
            title="GitHub Actions"
            load={() => admin.actions()}
            errorHint="Set GITHUB_TOKEN on the broker (Actions: read & write, Contents: read) to enable runs + the changelog. The rest of the console still works."
          >
            {(a) => (
              <>
                <RunsCard actions={a} busy={busy} onRerun={rerun} />
                <ChangelogCard actions={a} />
              </>
            )}
          </Panel>
          <Panel
            key={`overrides-${nonce}`}
            title="Calling access overrides"
            load={async () => {
              // The card renders calling_match + grants_access + note + id (remove). created_by is
              // AVAILABLE on the table but not fetched (the UI never shows who added an override).
              const { data } = await supabase
                .from('calling_access_overrides')
                .select('id, calling_match, grants_access, note')
                .order('calling_match');
              return { overrides: (data ?? []) as Json[] };
            }}
          >
            {(s) => (
              <CallingOverridesCard
                overrides={(s['overrides'] as Json[]) ?? []}
                busy={busy}
                onAdd={addOverride}
                onRemove={removeOverride}
              />
            )}
          </Panel>
        </div>
        {busy && (
          /* A busy-action overlay scoped to the console (absolute within its relative container) — not
             a screen-wide block. The Modal already keeps it visually inside the side sheet. */
          <div
            className="scrim"
            style={{ position: 'absolute', background: 'rgba(0,0,0,0.2)' }}
          >
            <span className="spinner spinner--lg" role="status" aria-label="Working" />
          </div>
        )}

      {confirm && (
        <Modal
          open
          onClose={() => setConfirm(null)}
          title={confirm.title}
          hideClose
          actions={
            <>
              <Button onClick={() => setConfirm(null)}>Cancel</Button>
              <Button
                variant="filled"
                onClick={() => {
                  const yes = confirm.onYes;
                  setConfirm(null);
                  yes();
                }}
              >
                {confirm.yesLabel}
              </Button>
            </>
          }
        >
          <p>{confirm.body}</p>
        </Modal>
      )}
    </>
  );

  // Embedded: the wide side sheet supplies the title + close + an inline Refresh (in the title row),
  // so we render just the panels — no separate refresh row (#28).
  if (embedded) {
    return <div style={{ position: 'relative' }}>{panels}</div>;
  }

  // Standalone (deep-link safety): the original full-page chrome.
  return (
    <div className="app-shell">
      <header className="appbar">
        <IconButton icon="chevron_left" label="Back" onClick={() => navigate(-1)} />
        <h1 className="appbar__title">Admin · Ops console</h1>
        <span className="appbar__spacer" />
        <IconButton icon="refresh" label="Refresh" onClick={refresh} disabled={busy} />
      </header>
      <main className="page" style={{ position: 'relative' }}>
        {panels}
      </main>
    </div>
  );
}

/** A panel that renders immediately as a titled card: skeleton while loading, error (with hint) on
 * failure, else the built content. Mirrors `_section`. */
function Panel<T extends Json>({
  title,
  load,
  errorHint,
  children,
}: {
  title: string;
  load: () => Promise<T>;
  errorHint?: string;
  children: (data: T) => ReactNode;
}) {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  useEffect(() => {
    let active = true;
    setState({ data: null, error: null, loading: true });
    load()
      .then((d) => active && setState({ data: d, error: null, loading: false }))
      .catch((e) => active && setState({ data: null, error: e instanceof Error ? e.message : String(e), loading: false }));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state.loading) {
    // #29: reserve a min-height close to the typical loaded panel so content doesn't jump on arrival.
    return (
      <Card title={`${title}…`}>
        <div style={{ minHeight: 96 }}>
          <CardSkeleton lines={4} />
        </div>
      </Card>
    );
  }
  if (state.error) {
    return (
      <Card title={title}>
        <p className="small">
          Couldn't load: {state.error}
          {/* A5: a hint joined with "\n\n" collapses to a single space in HTML — render it as its
              own block so it actually reads as a separate line. */}
          {errorHint ? <span style={{ display: 'block', marginTop: 6 }}>{errorHint}</span> : null}
        </p>
      </Card>
    );
  }
  // Crossfade the real content in when it resolves (instead of a hard pop after the skeleton).
  return <div className="reveal">{children(state.data as T)}</div>;
}

function Card({ title, trailing, children }: { title: string; trailing?: ReactNode; children: ReactNode }) {
  return (
    <div className="card">
      <div className="card__body">
        <div className="row" style={{ marginBottom: 8 }}>
          <strong style={{ flex: 1, fontSize: '1rem' }}>{title}</strong>
          {trailing}
        </div>
        {children}
      </div>
    </div>
  );
}

// Recent Church-login evaluations (admin-only). The tool for debugging "this leader can't log in":
// who tried, their stake + callings, the outcome, and what scope they actually RESOLVE to (role_scope
// = 'none' means they signed in but see an empty app — the under-visibility signal).
function LoginAuditCard({ logins: all }: { logins: Json[] }) {
  if (!all.length)
    return (
      <Card title="Recent logins">
        <p className="small muted">No login attempts recorded yet.</p>
      </Card>
    );
  const logins = all.slice(0, 8); // full, paginated history at /admin/logins (#7)
  const color = (o: string) => (o === 'allowed' || o === 'enrolled' ? statusColors.successFg : statusColors.warning);
  return (
    <Card title="Recent logins" trailing={all.length > 8 ? <ViewAllLink to="/admin/logins" n={all.length} /> : undefined}>
      {logins.map((r, i) => {
        const outcome = String(r['outcome'] ?? r['authorized'] ?? '');
        const callings = (Array.isArray(r['callings']) ? (r['callings'] as unknown[]) : []).join(', ');
        const scope = String(r['role_scope'] ?? '');
        const at = String(r['at'] ?? '');
        return (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
            <div className="row">
              <MaskedEmail email={r['email']} />
              <span style={{ color: color(outcome), fontWeight: 600 }}>{outcome || '—'}</span>
            </div>
            {r['stake_name'] ? <div className="small muted">{String(r['stake_name'])}</div> : null}
            {callings ? <div className="small muted">Callings: {callings}</div> : null}
            {scope ? <div className="small muted">Sees: {scope}</div> : null}
            {/* fmtDateTime renders the admin's LOCAL time; the raw `at` slice showed UTC. */}
            <div className="small muted">{fmtDateTime(at)}</div>
          </div>
        );
      })}
    </Card>
  );
}

function Pill({ label, ok, offText = 'down' }: { label: string; ok: boolean; offText?: string }) {
  const c = ok ? statusColors.successFg : statusColors.warning;
  return (
    <span className="chip" style={{ borderColor: c, color: c, background: `${c}1f` }}>
      <Icon name={ok ? 'check_circle' : 'error'} size={16} color={c} />
      {label} · {ok ? 'ok' : offText}
    </span>
  );
}

// #7a: ONE panel merging system health + the external tool/dashboard deeplinks — each system on its
// own row with a status dot (where we know it), a useful live stat (where we have one), and a deeplink.
function SystemHealthCard({ summary }: { summary: Json }) {
  const brokerOk = (summary['broker'] as Json)?.['ok'] === true;
  const sb = (summary['supabase'] as Json) ?? {};
  const githubConfigured = summary['github_configured'] === true;
  const links = ((summary['links'] as Json) ?? {}) as Record<string, string>;
  const linkEntries = Object.entries(links);
  const matched = new Set<string>();
  const linkFor = (needles: string[]): string | undefined => {
    const hit = linkEntries.find(([k]) => needles.some((n) => k.toLowerCase().includes(n)));
    if (hit) matched.add(hit[0]);
    return hit?.[1];
  };

  type Sys = { name: string; ok?: boolean; stat?: string; offText?: string; url?: string };
  const systems: Sys[] = [
    { name: 'Broker (Render)', ok: brokerOk, stat: brokerOk ? 'up' : undefined, offText: 'down', url: linkFor(['render', 'broker']) },
    { name: 'Supabase', ok: sb['ok'] === true, stat: sb['members'] != null ? `${sb['members']} members` : undefined, url: linkFor(['supabase']) },
    { name: 'GitHub Actions', ok: githubConfigured, stat: githubConfigured ? 'linked' : undefined, offText: 'not linked', url: linkFor(['github', 'actions']) },
    { name: 'Axiom — logs', url: linkFor(['axiom', 'log']) },
    { name: 'Sentry — errors', url: linkFor(['sentry']) },
  ];
  // Any links we didn't map to a known system become their own deeplink rows.
  for (const [k, v] of linkEntries) if (!matched.has(k)) systems.push({ name: k, url: v });

  const shown = systems.filter((s) => s.ok !== undefined || s.url);
  return (
    <Card title="System health">
      <div className="stack" style={{ gap: 2 }}>
        {shown.map((s) => (
          <div key={s.name} className="row" style={{ justifyContent: 'space-between', gap: 8, padding: '6px 0' }}>
            <span className="row" style={{ gap: 8, alignItems: 'center', minWidth: 0 }}>
              {s.ok !== undefined && (
                <span
                  aria-label={s.ok ? 'healthy' : (s.offText ?? 'down')}
                  title={s.ok ? 'healthy' : (s.offText ?? 'down')}
                  style={{ width: 9, height: 9, borderRadius: '50%', background: s.ok ? '#2e7d32' : '#bdbdbd', flexShrink: 0 }}
                />
              )}
              <strong style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.name}</strong>
              {(s.stat || (s.ok === false && s.offText)) && (
                <span className="small muted">{s.stat ?? s.offText}</span>
              )}
            </span>
            {s.url && (
              <button type="button" className="chip" onClick={() => openUrl(s.url!)} aria-label={`Open ${s.name}`}>
                <Icon name="open_in_new" size={14} />
                Open
              </button>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function FreshnessCard({ summary }: { summary: Json }) {
  const sb = (summary['supabase'] as Json) ?? {};
  // A6: the two timestamps are the urgent "did sync actually run?" signal — lead with them, emphasized.
  // The row counts are background context, so demote them under a quiet "Counts" sublabel.
  return (
    <Card title="Data freshness">
      <BigKv k="Last member update" v={agoOrNever(sb['last_member_update'])} />
      <BigKv k="Last stake sync" v={agoOrNever(sb['last_stake_sync'])} />
      <hr className="divider" />
      <p className="small muted" style={{ margin: '0 0 8px', fontWeight: 600 }}>Counts</p>
      <div className="wrap" style={{ gap: 18 }}>
        <Stat label="Members" v={sb['members']} />
        <Stat label="Units" v={sb['units']} />
        <Stat label="Stakes" v={sb['stakes']} />
        <Stat label="Admins" v={sb['admins']} />
      </div>
    </Card>
  );
}

// A6: the freshness timestamps, emphasized — bigger value than a plain Kv since they answer the most
// urgent ops question (did the sync run?).
function BigKv({ k, v }: { k: string; v: string }) {
  return (
    <div className="row" style={{ padding: '5px 0', justifyContent: 'space-between' }}>
      <span>{k}</span>
      <strong style={{ fontSize: '1.05rem' }}>{v}</strong>
    </div>
  );
}

function Stat({ label, v }: { label: string; v: unknown }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{v == null ? '—' : String(v)}</div>
      <div>{label}</div>
    </div>
  );
}

function MaintenanceCard({
  summary,
  busy,
  onRun,
}: {
  summary: Json;
  busy: boolean;
  onRun: (label: string, body: string, inputs: Json) => void;
}) {
  const configured = summary['github_configured'] === true;
  const dis = busy || !configured;
  return (
    <Card title="Maintenance">
      <p>Each flow re-scrapes LCR (required for fresh data); the choice controls where it writes.</p>
      <div className="wrap" style={{ gap: 10, marginTop: 12 }}>
        <Button variant="filled" icon="cloud_sync" disabled={dis} onClick={() => onRun('Full sync', 'Re-scrapes LCR and repopulates both Google Sheets and Supabase.', { targets: 'both' })}>
          Full sync
        </Button>
        <Button variant="outlined" icon="storage" disabled={dis} onClick={() => onRun('Supabase only', 'Re-scrapes LCR and repopulates Supabase (the app data) only.', { targets: 'supabase' })}>
          Supabase only
        </Button>
        <Button variant="outlined" icon="table" disabled={dis} onClick={() => onRun('Google Sheets only', 'Re-scrapes LCR and repopulates the Google Sheet only.', { targets: 'sheets' })}>
          Sheets only
        </Button>
        <Button variant="outlined" icon="photo" disabled={dis} onClick={() => onRun('Refresh photos', 'Re-scrapes LCR, updates Supabase, and refreshes member avatars in Storage.', { targets: 'supabase', photos: 'true' })}>
          Refresh photos
        </Button>
      </div>
      {!configured && (
        <p className="small" style={{ marginTop: 8 }}>
          Link GitHub (set GITHUB_TOKEN on the broker) to enable flows.
        </p>
      )}
    </Card>
  );
}

// #13–15: collapse an endpoint to its route pattern so calls aggregate — defensive on the CLIENT so
// even OLD diagnostics rows (captured before the metrics-normalizer fix) group cleanly.
function normEndpoint(ep: string): string {
  return ep
    .split('/')
    .map((s) => (s === '{id}' || /^\d+$/.test(s) || /^(\{id\})?[0-9a-fA-F]{8,}$/.test(s) ? '{id}' : s))
    .join('/');
}

interface EpRow { endpoint: string; calls: number; errors: number; avg_ms: number; max_ms: number }

/** Group raw per-endpoint metrics by route (sum calls/errors, weight avg latency by calls), sorted
 *  failing-first then by volume — the readable view behind #15. */
function groupEndpoints(endpoints: Json[]): EpRow[] {
  const by = new Map<string, { calls: number; errors: number; ms: number; max: number }>();
  for (const raw of endpoints) {
    const key = normEndpoint(String(raw['endpoint'] ?? ''));
    const calls = Number(raw['calls'] ?? 0);
    const avg = Number(raw['avg_ms'] ?? 0);
    const g = by.get(key) ?? { calls: 0, errors: 0, ms: 0, max: 0 };
    g.calls += calls;
    g.errors += Number(raw['errors'] ?? 0);
    g.ms += avg * calls;
    g.max = Math.max(g.max, Number(raw['max_ms'] ?? avg));
    by.set(key, g);
  }
  return [...by.entries()]
    .map(([endpoint, g]) => ({
      endpoint,
      calls: g.calls,
      errors: g.errors,
      avg_ms: g.calls > 0 ? Math.round(g.ms / g.calls) : 0,
      max_ms: g.max,
    }))
    .sort((a, b) => b.errors - a.errors || b.calls - a.calls);
}

// --- Field gaps, aggregated per day (#track-missing-fields) -----------------------------------
// "Which fields are missing, and is it trending better or worse?" — answered without any PII. Every
// sync run stamps a structured field-gap report into its diagnostics payload (run_stats.field_gaps:
// per-field members-missing + WHY) and also emits a live Axiom `sync.field_gaps` event. This card
// reads the recent diagnostics rows, rolls them up per calendar day (logic/fieldGaps.ts), and charts
// the daily total per field as a sparkline so a leader's "ministering is blank" is a number you watch
// fall. The aggregation lives in logic/ (pure, unit-tested) — this file is just the render.

/** A tiny inline bar series (oldest → newest); the last bar is the current day (full opacity). */
function Spark({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(1, ...values);
  return (
    <span className="row" style={{ gap: 2, alignItems: 'flex-end', height: 22 }} aria-hidden>
      {values.map((v, i) => (
        <span
          key={i}
          title={String(v)}
          style={{
            width: 6,
            height: Math.max(2, Math.round((v / max) * 22)),
            background: color,
            opacity: i === values.length - 1 ? 1 : 0.4,
            borderRadius: 1,
          }}
        />
      ))}
    </span>
  );
}

function FieldGapsCard({ diag }: { diag: Json }) {
  const { days, fields, totals, reasons } = fieldGapSeries((diag['runs'] as Json[]) ?? []);
  if (days.length === 0) {
    return <Card title="Field gaps (per day)">No field-gap telemetry yet — it appears after the next sync.</Card>;
  }

  return (
    <Card title="Field gaps (per day)" trailing={<span className="small muted">last {days.length}d · all stakes</span>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Members still missing each field, summed across stakes and grouped by day (latest run per stake).
        The live per-sync signal is the Axiom <code>sync.field_gaps</code> event.
      </p>
      {fields.length === 0 ? (
        <p className="small" style={{ color: statusColors.success }}>No gaps — every tracked field is filled. ✓</p>
      ) : (
        fields.map((f) => {
          const series = totals[f];
          const cur = series[series.length - 1];
          const prev = series.length > 1 ? series[series.length - 2] : cur;
          const delta = cur - prev;
          // Worse (more missing) is red ▲; better is green ▼; flat is muted.
          const trend =
            delta > 0
              ? { glyph: '▲', color: statusColors.danger, label: `up ${delta}` }
              : delta < 0
                ? { glyph: '▼', color: statusColors.success, label: `down ${-delta}` }
                : { glyph: '–', color: 'var(--on-surface-variant)', label: 'no change' };
          return (
            <div key={f} className="row" style={{ padding: '8px 0', alignItems: 'center', gap: 12, borderTop: '1px solid var(--outline-variant)' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row" style={{ gap: 8, alignItems: 'baseline' }}>
                  <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{humanizeField(f)}</strong>
                  <span style={{ color: trend.color, fontSize: 12 }} title={trend.label} aria-label={trend.label}>
                    {trend.glyph} {Math.abs(delta) || ''}
                  </span>
                </div>
                {reasons[f] && (
                  <div className="small muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{reasons[f]}</div>
                )}
              </div>
              <Spark values={series} color={statusColors.warning} />
              <span style={{ width: 40, textAlign: 'right', fontWeight: 600 }} aria-label={`${cur} missing`}>{cur}</span>
            </div>
          );
        })
      )}
    </Card>
  );
}

function DiagnosticsCard({ diag, onCopy, toast }: { diag: Json; onCopy: (t: string) => void; toast: ReturnType<typeof useToast> }) {
  const [failingOnly, setFailingOnly] = useState(true); // #15: failing endpoints first / show all
  const runs = ((diag['runs'] as Json[]) ?? []);
  const run = runs.find((r) => r['kind'] === 'sync');
  if (!run) return <Card title="Diagnostics">No sync diagnostics yet.</Card>;
  const p = (run['payload'] as Json) ?? {};
  const req = (p['requests'] as Json) ?? {};
  const stats = (p['run_stats'] as Json) ?? {};
  const coverage = (p['field_coverage'] as Json) ?? {};
  const endpoints = ((req['endpoints'] as Json[]) ?? []);
  const groupedEndpoints = groupEndpoints(endpoints);
  const failingEndpoints = groupedEndpoints.filter((e) => e.errors > 0);
  const shownEndpoints = failingOnly && failingEndpoints.length ? failingEndpoints : groupedEndpoints;
  const failed = ((stats['failed_units'] as unknown[]) ?? []);
  const successPct = Number(req['success_pct'] ?? 100);

  function dump(): string {
    const lines: string[] = [];
    lines.push('Covenant Path — sync diagnostics (PII-safe)');
    lines.push(`run_at: ${run!['run_at']}   kind: ${run!['kind']}`);
    lines.push(`requests: ${req['success_pct'] ?? '?'}% success, ${req['total_errors'] ?? 0} errors`);
    lines.push(`units ok: ${stats['units'] ?? '?'}${failed.length ? `   failed: ${failed.join(', ')}` : ''}`);
    if (Object.keys(coverage).length) {
      lines.push('field_coverage (filled/blocked/pending):');
      for (const [k, v] of Object.entries(coverage)) {
        const c = v as Json;
        lines.push(`  ${k}: ${c['filled'] ?? 0}/${c['blocked'] ?? 0}/${c['pending'] ?? 0}`);
      }
    }
    if (groupedEndpoints.length) {
      lines.push('endpoints (grouped by route, failing first):');
      for (const ep of groupedEndpoints) lines.push(`  ${ep.endpoint}: ${ep.calls} calls, ${ep.avg_ms}ms avg, ${ep.errors} err`);
    }
    const stale = (p['field_staleness'] as Json) ?? {};
    if (Object.keys(stale).length) {
      lines.push('field staleness (fresh / warn>3d / error>7d / never-fetched):');
      for (const [k, v] of Object.entries(stale)) {
        const c = v as Json;
        lines.push(`  ${k}: ${c['fresh'] ?? 0} / ${c['warn'] ?? 0} / ${c['error'] ?? 0} / ${c['never'] ?? 0}`);
      }
    }
    const neutralized = (stats['neutralized_stale'] as unknown[]) ?? [];
    if (neutralized.length) lines.push(`STALE-ACTION (neutralized, last-good preserved): ${neutralized.join(', ')}`);
    // Full payload so nothing is lost when pasting to Claude.
    lines.push('', '--- full diagnostics payload (JSON) ---', JSON.stringify(p, null, 2));
    return lines.join('\n');
  }

  return (
    <Card title="Diagnostics" trailing={<span className="small muted">{agoOrNever(run['run_at'])}</span>}>
      <div className="wrap" style={{ gap: 10 }}>
        <Pill label={`Requests ${successPct.toFixed(0)}%`} ok={successPct >= 99} />
        <Pill label={`Units ${stats['units'] ?? '—'} ok`} ok={failed.length === 0} offText={`${failed.length} failed`} />
        <Pill label={`${req['total_errors'] ?? 0} request errors`} ok={Number(req['total_errors'] ?? 0) === 0} />
      </div>
      <div style={{ textAlign: 'right' }}>
        <Button
          icon="copy"
          onClick={() => {
            onCopy(dump());
            toast.show({ message: 'Diagnostics copied — paste into Claude.' });
          }}
        >
          Copy for Claude
        </Button>
      </div>
      {failed.length > 0 && (
        <p style={{ marginTop: 8, color: statusColors.warning }}>Failed units: {failed.join(', ')}</p>
      )}
      {Object.keys(coverage).length > 0 && (
        <>
          <p className="small" style={{ marginTop: 14, fontWeight: 600 }}>Field parity (filled / blocked / pending)</p>
          {Object.entries(coverage).map(([field, v]) => (
            <ParityRow key={field} field={field} c={v as Json} />
          ))}
        </>
      )}
      {groupedEndpoints.length > 0 && (
        <>
          <div className="row" style={{ marginTop: 14, alignItems: 'center' }}>
            <p className="small" style={{ fontWeight: 600, flex: 1, margin: 0 }}>Endpoint performance</p>
            {failingEndpoints.length > 0 && (
              <button type="button" className="btn btn--text" onClick={() => setFailingOnly((f) => !f)}>
                {failingOnly ? `Show all ${groupedEndpoints.length}` : `Failing only (${failingEndpoints.length})`}
              </button>
            )}
          </div>
          {shownEndpoints.map((ep, i) => (
            <div key={i} className="row" style={{ padding: '2px 0' }}>
              <code style={{ flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis' }}>{ep.endpoint}</code>
              <span className="small" style={{ color: ep.errors !== 0 ? statusColors.danger : undefined }}>
                {ep.calls} calls · {ep.avg_ms}ms avg{ep.errors !== 0 ? ` · ${ep.errors} err` : ''}
              </span>
            </div>
          ))}
        </>
      )}
    </Card>
  );
}

function EndpointHealthCard({ data }: { data: Json }) {
  const eps = (data['endpoints'] as Json[]) ?? [];
  const byHour = (data['by_hour'] as Record<string, Json>) ?? {};
  const runs = Number(data['runs'] ?? 0);
  const days = Number(data['days'] ?? 14);
  if (eps.length === 0) {
    return <Card title="Endpoint health (trend)">No sync/probe telemetry in the last {days} days yet.</Card>;
  }
  const shown = eps.slice(0, 10); // top of the list only — the full, paginated set lives at /admin/endpoints
  // Telemetry buckets are UTC hours; show the admin their LOCAL wall-clock hour (whole-hour
  // offset — half-hour timezones read ±30 min, fine for a "quiet hour" scan).
  const offH = Math.round(-new Date().getTimezoneOffset() / 60);
  const hours = Object.keys(byHour)
    .map((k) => ({ k, local: (((Number(k) + offH) % 24) + 24) % 24 }))
    .sort((a, b) => a.local - b.local);
  const verdictColor = (v: string) =>
    v === 'hot' ? statusColors.danger : v === 'watch' ? statusColors.warning : statusColors.success;
  const hourColor = (pct: number) =>
    pct >= 10 ? statusColors.danger : pct >= 2 ? statusColors.warning : statusColors.success;
  return (
    <Card
      title="Endpoint health (trend)"
      trailing={
        <span className="row" style={{ gap: 10 }}>
          <span className="small muted">{runs} runs · {days}d</span>
          {eps.length > 10 && <ViewAllLink to="/admin/endpoints" n={eps.length} />}
        </span>
      }
    >
      <p className="small muted" style={{ marginTop: 0 }}>
        Passive read from telemetry the sync/probe already record — zero added load on LCR. error% is at the
        sync&apos;s current pace; for the safe ceiling, run the rate finder (tools/rate_finder.py).
      </p>
      {shown.map((ep, i) => {
        const errPct = Number(ep['error_pct'] ?? 0);
        const verdict = String(ep['verdict'] ?? 'healthy');
        return (
          <div key={i} className="row" style={{ padding: '3px 0', alignItems: 'center' }}>
            <code style={{ flex: 1, fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {String(ep['endpoint'])}
            </code>
            <span className="small" style={{ marginLeft: 8, color: errPct > 0 ? statusColors.danger : undefined }}>
              {String(ep['calls'])} calls · {String(ep['avg_ms'])}ms avg{errPct > 0 ? ` · ${errPct}% err` : ''}
            </span>
            <span
              className="chip"
              style={{ marginLeft: 8, padding: '1px 8px', fontSize: 11, borderColor: verdictColor(verdict), color: verdictColor(verdict) }}
            >
              {verdict}
            </span>
          </div>
        );
      })}
      {hours.length > 0 && (
        <>
          <p className="small" style={{ marginTop: 14, fontWeight: 600 }}>
            Error rate by hour (your local time) — schedule the heavy sync at a quiet hour
          </p>
          <div className="wrap" style={{ gap: 6 }}>
            {hours.map(({ k, local }) => {
              const b = byHour[k];
              const pct = Number(b['error_pct'] ?? 0);
              return (
                <span
                  key={k}
                  className="chip"
                  title={`${String(b['calls'])} calls`}
                  style={{ padding: '1px 8px', fontSize: 11, borderColor: hourColor(pct) }}
                >
                  {local}h · {pct}%
                </span>
              );
            })}
          </div>
        </>
      )}
    </Card>
  );
}

function ParityRow({ field, c }: { field: string; c: Json }) {
  const filled = Number(c['filled'] ?? 0);
  const blocked = Number(c['blocked'] ?? 0);
  const pending = Number(c['pending'] ?? 0);
  const total = Math.max(1, filled + blocked + pending);
  return (
    <div className="row" style={{ padding: '3px 0' }}>
      <span style={{ width: 150, overflow: 'hidden', textOverflow: 'ellipsis' }}>{field}</span>
      <span style={{ flex: 1, display: 'flex', borderRadius: 4, overflow: 'hidden', height: 10 }}>
        {filled > 0 && <span style={{ flex: filled, background: '#66bb6a' }} />}
        {blocked > 0 && <span style={{ flex: blocked, background: '#ef5350' }} />}
        {pending > 0 && <span style={{ flex: pending, background: '#bdbdbd' }} />}
      </span>
      <span className="small" style={{ marginLeft: 8 }}>
        {filled}/{total}
      </span>
    </div>
  );
}

// --- enrolled-stakes shared derivations (B1/B2/B5) ---------------------------------------------

/** The 45-day Member Tools token countdown for a stake's credential: null when there's no token
 *  (manual re-auth), a green/amber/red number of days left otherwise. (B1) */
function tokenExpiry(cred: Json | undefined): { days: number; color: string; label: string } | null {
  if (!cred) return null;
  const raw = cred['token_expires_in_days'];
  if (raw == null) return null; // no self-renewing token on file
  const days = Number(raw);
  if (!Number.isFinite(days)) return null;
  if (days < 0) return { days, color: statusColors.danger, label: '45-day token: expired' };
  const color = days > 10 ? statusColors.success : statusColors.warning;
  return { days, color, label: `45-day token: ${days} day${days === 1 ? '' : 's'} left` };
}

/** A stake needs admin action when its credential is stale/revoked, the sync is flagged
 *  needs_reauth, or the 45-day token is expired/absent (no self-renewal). (B2) */
function stakeNeedsAction(s: Json): { reason: string } | null {
  const cred = s['credential'] as Json | undefined;
  const state = cred ? String(cred['state'] ?? '') : 'none';
  if (s['sync_state'] === 'needs_reauth') return { reason: 'Sync flagged needs re-authorization' };
  if (state === 'revoked') return { reason: 'Credential revoked' };
  if (state === 'stale') return { reason: 'Last sync failed — session needs re-auth' };
  if (!cred) return null; // never enrolled — not an action item (it shows in the main list)
  const exp = tokenExpiry(cred);
  if (exp && exp.days < 0) return { reason: '45-day sync token expired' };
  if (!exp && cred['self_renewing'] !== true) return { reason: 'No self-renewing token — session will need re-auth' };
  return null;
}

/** Sort key: soonest-to-expire first. Expired/absent tokens (the most urgent) sort ahead of
 *  long-lived ones; a stake with no countdown at all goes last. (B1) */
function expirySortKey(s: Json): number {
  const cred = s['credential'] as Json | undefined;
  const raw = cred?.['token_expires_in_days'];
  if (raw == null) return Number.POSITIVE_INFINITY; // no token info → bottom
  const n = Number(raw);
  return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
}

/** B5: a one-line rollup over the fetched stakes — self-renewing vs manual vs expiring within 7d. */
function selfRenewingRollup(stakes: Json[]): { renewing: number; manual: number; expiring: number } {
  let renewing = 0;
  let manual = 0;
  let expiring = 0;
  for (const s of stakes) {
    const cred = s['credential'] as Json | undefined;
    if (!cred) continue; // not enrolled
    if (cred['self_renewing'] === true) renewing += 1;
    else manual += 1;
    const exp = tokenExpiry(cred);
    if (exp && exp.days >= 0 && exp.days <= 7) expiring += 1;
  }
  return { renewing, manual, expiring };
}

// B2: a compact worklist of stakes needing admin action, derived from the SAME fetched array — no
// new endpoint. Shows name + reason + provider email + the "Send re-auth email" button.
function ReauthWorklistCard({
  stakes,
  busy,
  onReauth,
}: {
  stakes: Json[];
  busy: boolean;
  onReauth: (id: string, name: string) => void;
}) {
  const needs = stakes
    .map((s) => ({ s, action: stakeNeedsAction(s) }))
    .filter((x): x is { s: Json; action: { reason: string } } => x.action != null)
    .sort((a, b) => expirySortKey(a.s) - expirySortKey(b.s));
  if (needs.length === 0) return null; // nothing to do → the card hides itself
  return (
    <Card title={`Needs re-authorization (${needs.length})`}>
      {needs.map(({ s, action }, i) => {
        const cred = s['credential'] as Json | undefined;
        const name = String(s['name'] ?? '—');
        const stakeId = String(s['stake_id']);
        const provider = cred?.['principal_email'] != null ? String(cred['principal_email']) : '';
        return (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
            <div className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
              <strong>{name}</strong>
              {provider && (
                <Button
                  variant="outlined"
                  icon="mail"
                  disabled={busy}
                  onClick={() => onReauth(stakeId, name)}
                >
                  Send re-auth email
                </Button>
              )}
            </div>
            <div className="small" style={{ color: statusColors.warning }}>{action.reason}</div>
            {provider ? (
              <div className="small muted">Provider: {provider}</div>
            ) : (
              <div className="small muted">No provider email on file — a leader must re-enroll.</div>
            )}
          </div>
        );
      })}
    </Card>
  );
}

function EnrolledStakesCard({
  stakes: rawStakes,
  busy,
  onRevoke,
  onSync,
  onWipe,
  onRemove,
  onReauth,
}: {
  stakes: Json[];
  busy: boolean;
  onRevoke: (id: string, name: string) => void;
  onSync: (unit: string, name: string) => void;
  onWipe: (id: string, name: string) => void;
  onRemove: (id: string, name: string) => void;
  onReauth: (id: string, name: string) => void;
}) {
  if (rawStakes.length === 0) return <Card title="Enrolled stakes">No stakes yet.</Card>;
  // B1: soonest-to-expire first so the stakes about to stop syncing are at the top.
  const stakes = [...rawStakes].sort((a, b) => expirySortKey(a) - expirySortKey(b));
  // B5: a one-line self-renewing rollup under the title.
  const roll = selfRenewingRollup(rawStakes);
  return (
    <Card title={`Enrolled stakes (${rawStakes.length})`}>
      <p className="small muted" style={{ marginTop: 0 }}>
        {roll.renewing} self-renewing · {roll.manual} manual
        {roll.expiring > 0 ? ` · ${roll.expiring} expiring within 7 days` : ''}
      </p>
      {stakes.map((s, i) => {
        const cred = s['credential'] as Json | undefined;
        const name = String(s['name'] ?? '—');
        const stakeId = String(s['stake_id']);
        const unitNumber = String(s['unit_number'] ?? '');
        const jobs7d = Number(s['jobs_7d'] ?? 0) || 0;
        const members = s['member_count'] ?? 0;
        const running = s['sync_state'] === 'running';
        let credLabel: string;
        let credColor: string;
        if (!cred) {
          credLabel = 'No credential';
          credColor = statusColors.neutral;
        } else if (cred['state'] === 'revoked') {
          credLabel = 'Revoked';
          credColor = statusColors.warning;
        } else if (cred['state'] === 'stale') {
          credLabel = 'Stale · needs re-auth';
          credColor = statusColors.danger;
        } else if (cred['complete'] === true) {
          credLabel = 'Active · full coverage';
          credColor = statusColors.success;
        } else {
          credLabel = 'Active · partial';
          credColor = statusColors.info;
        }
        const credState = cred ? String(cred['state'] ?? '') : 'none';
        const lastError = cred?.['last_error'] != null ? String(cred['last_error']) : '';
        const missing = (cred?.['missing'] as unknown[]) ?? [];
        const exp = tokenExpiry(cred);
        const canReauth = !!cred && (credState === 'active' || credState === 'stale');
        return (
          <div key={i} style={{ padding: '6px 0' }}>
            {/* A2: name + ID on their own line so they never get clipped on a phone. */}
            <div className="row" style={{ gap: 8 }}>
              <strong>{name}</strong>
              {/* Stable LCR stake ID — stakes get renamed, so the ID is how you identify them (#9). */}
              {unitNumber && unitNumber !== 'null' && (
                <span className="small muted" style={{ fontFamily: 'monospace' }}>ID {unitNumber}</span>
              )}
              {running && <span className="spinner" aria-hidden="true" style={{ width: 14, height: 14 }} />}
            </div>
            {/* A2: actions in a wrapping container so they flow to a second line on narrow screens.
                A3: the destructive Wipe/Remove are separated and use the danger token (dark-mode-safe). */}
            <div className="wrap" style={{ gap: 4, marginTop: 2 }}>
              {!running && credState !== 'revoked' && credState !== 'none' && (
                <IconButton icon="sync" label="Sync this stake now" size={18} disabled={busy} onClick={() => onSync(unitNumber, name)} />
              )}
              {(credState === 'active' || credState === 'stale') && (
                <IconButton icon="link_off" label="Revoke sync credential" size={18} disabled={busy} onClick={() => onRevoke(stakeId, name)} />
              )}
              {canReauth && (
                <IconButton icon="mail" label="Send re-authorization email" size={18} disabled={busy} onClick={() => onReauth(stakeId, name)} />
              )}
              {/* A small spacer divider before the destructive actions so they read as a distinct group. */}
              <span aria-hidden="true" style={{ width: 1, alignSelf: 'stretch', margin: '0 4px', background: 'var(--outline-variant)' }} />
              <button type="button" className="btn btn--text btn--danger" disabled={busy} onClick={() => onWipe(stakeId, name)}
                title="Wipe member data (keeps the stake + roles + credential)"
                style={{ fontSize: 12, padding: '2px 8px', fontWeight: 600 }}>
                Wipe
              </button>
              <button type="button" className="btn btn--text btn--danger" disabled={busy} onClick={() => onRemove(stakeId, name)}
                title="Remove stake completely (irreversible)"
                style={{ fontSize: 12, padding: '2px 8px', fontWeight: 600 }}>
                Remove
              </button>
            </div>
            <div className="wrap" style={{ gap: 8, alignItems: 'center', marginTop: 4 }}>
              <span className="chip" style={{ borderColor: credColor, color: credColor, background: `${credColor}1f`, fontSize: 12 }}>
                {credLabel}
              </span>
              {/* B1: 45-day token countdown chip — green >10, amber ≤10, red expired. */}
              {exp && (
                <span className="chip" style={{ borderColor: exp.color, color: exp.color, background: `${exp.color}1f`, fontSize: 12 }}>
                  {exp.label}
                </span>
              )}
              <span className="small muted">{String(members)} members</span>
              <span className="small muted">· synced {agoOrNever(s['last_synced_at'])}</span>
              {/* Sync jobs that actually ran for this stake in the last 7 days (#9). Amber when zero. */}
              <span className="small" style={{ color: jobs7d === 0 ? statusColors.warning : 'var(--muted)' }}>
                · {jobs7d} job{jobs7d === 1 ? '' : 's'}/7d
              </span>
              {cred?.['principal_name'] != null && <span className="small muted">· by {String(cred['principal_name'])}</span>}
            </div>
            {cred && (
              /* Authorization cadence: when it was last authorized, whether it can self-renew
                 (refresh token captured at enroll), and how often re-auth has actually happened. */
              <div className="tiny muted" style={{ marginTop: 2 }}>
                authorized {agoOrNever(cred['updated_at'])}
                {cred['self_renewing'] === true
                  ? ' · self-renewing'
                  : cred['self_renewing'] === false
                    ? ' · manual re-auth needed when session expires'
                    : ''}
                {' · '}{Number(cred['reauths_30d'] ?? 0)} re-auth{Number(cred['reauths_30d'] ?? 0) === 1 ? '' : 's'}/30d
              </div>
            )}
            {credState === 'stale' && (
              <p className="tiny" style={{ marginTop: 2, color: statusColors.danger }}>
                Last sync failed{lastError ? `: ${lastError.slice(0, 120)}` : ''} — a leader must re-authorize (or take over).
              </p>
            )}
            {cred && cred['complete'] !== true && missing.length > 0 && (
              <p className="tiny" style={{ marginTop: 2, color: statusColors.warning }}>
                Missing: {missing.join(', ')}
              </p>
            )}
            <hr className="divider" style={{ margin: '8px 0 0' }} />
          </div>
        );
      })}
    </Card>
  );
}

// B4: leaders who signed in but resolve to NO scope — the exact people to invite/bind (a missing
// email binding). De-duped by email; shows email + stake + callings.
function VisibilityWorklistCard({ rows: all }: { rows: Json[] }) {
  // De-dupe by email, keeping the most recent (the query is already newest-first).
  const seen = new Set<string>();
  const rows: Json[] = [];
  for (const r of all) {
    const email = String(r['email'] ?? '').toLowerCase();
    if (!email || seen.has(email)) continue;
    seen.add(email);
    rows.push(r);
  }
  if (rows.length === 0)
    return (
      <Card title="Signed in but sees nothing">
        <p className="small muted">None recently — every signed-in leader resolves to a scope.</p>
      </Card>
    );
  const shown = rows.slice(0, 12);
  return (
    <Card title={`Signed in but sees nothing (${rows.length})`}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Signed in successfully but resolve to no scope (empty app) — usually a missing email binding.
        Invite or bind these leaders.
      </p>
      {shown.map((r, i) => {
        const callings = (Array.isArray(r['callings']) ? (r['callings'] as unknown[]) : []).join(', ');
        return (
          <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
            <MaskedEmail email={r['email']} />
            {r['stake_name'] ? <div className="small muted">{String(r['stake_name'])}</div> : null}
            {callings ? <div className="small muted">Callings: {callings}</div> : null}
            <div className="tiny muted">{fmtDateTime(String(r['at'] ?? ''))}</div>
          </div>
        );
      })}
    </Card>
  );
}

function RunsCard({ actions, busy, onRerun }: { actions: Json; busy: boolean; onRerun: (id: number) => void }) {
  if (actions['configured'] !== true) return null;
  const all = ((actions['runs'] as Json[]) ?? []);
  // Top of the list only — the full, paginated history lives at /admin/runs (#7).
  const runs = all.slice(0, 8);
  return (
    <Card title="Recent Actions runs" trailing={all.length > 8 ? <ViewAllLink to="/admin/runs" n={all.length} /> : undefined}>
      {runs.length === 0 ? (
        <p>No runs found.</p>
      ) : (
        runs.map((r, i) => {
          const inProgress = r['status'] === 'in_progress' || r['status'] === 'queued';
          const ok = r['status'] === 'completed' ? r['conclusion'] === 'success' : null;
          return (
            <div key={i} className="list-tile" style={{ padding: '8px 0' }}>
              {ok == null ? (
                <Icon name="schedule" size={20} color={statusColors.info} />
              ) : (
                <Icon name={ok ? 'check_circle' : 'error'} size={20} color={ok ? statusColors.success : statusColors.danger} />
              )}
              <button
                type="button"
                className="list-tile__main"
                onClick={() => openUrl(r['html_url'] as string)}
                style={{ background: 'transparent', border: 'none', textAlign: 'left', color: 'inherit', padding: 0 }}
              >
                <span>
                  {String(r['name'])} #{String(r['run_number'])}
                </span>
                <span className="small muted" style={{ display: 'block' }}>
                  {String(r['event'])} · {agoOrNever(r['created_at'])}
                  {dur(r['duration_seconds']) &&
                    ` · ${r['status'] === 'completed' ? 'took' : 'running'} ${dur(r['duration_seconds'])}`}
                </span>
              </button>
              {!inProgress ? (
                <IconButton
                  icon="replay"
                  label="Re-run"
                  size={20}
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation();
                    onRerun(r['id'] as number);
                  }}
                />
              ) : (
                <span className="spinner" aria-hidden="true" style={{ width: 18, height: 18 }} />
              )}
            </div>
          );
        })
      )}
    </Card>
  );
}

function ChangelogCard({ actions }: { actions: Json }) {
  if (actions['configured'] !== true) return null;
  const all = ((actions['commits'] as Json[]) ?? []);
  if (all.length === 0) return null;
  const commits = all.slice(0, 5); // full history at /admin/changelog (#7)
  return (
    <Card title="Changelog" trailing={all.length > 5 ? <ViewAllLink to="/admin/changelog" n={all.length} /> : undefined}>
      {commits.map((c, i) => (
        <button key={i} type="button" className="list-tile" style={{ padding: '8px 0' }} onClick={() => openUrl(c['html_url'] as string)}>
          <Icon name="commit" size={18} />
          <span className="list-tile__main">
            <span>{String(c['message'])}</span>
            <span className="small muted" style={{ display: 'block' }}>
              {String(c['sha'])} · {String(c['author'] ?? '')} · {agoOrNever(c['date'])}
            </span>
          </span>
          {c['html_url'] != null && <Icon name="open_in_new" size={14} />}
        </button>
      ))}
    </Card>
  );
}

// #3c "map it + add new": admins grant member-data access to a calling the LCR matrix / always-allowed
// list doesn't cover, without a deploy. Applied on the next sync (provision_roles unions these in).
function CallingOverridesCard({
  overrides,
  busy,
  onAdd,
  onRemove,
}: {
  overrides: Json[];
  busy: boolean;
  onAdd: (match: string, grants: boolean, note: string) => void;
  onRemove: (id: number, match: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [match, setMatch] = useState('');
  const [grants, setGrants] = useState(true);
  const [note, setNote] = useState('');
  const submit = () => {
    const m = match.trim();
    if (!m) return;
    onAdd(m, grants, note.trim());
    setOpen(false);
    setMatch('');
    setNote('');
    setGrants(true);
  };
  return (
    <Card
      title="Calling access overrides"
      trailing={
        <Button disabled={busy} onClick={() => setOpen(true)}>
          Add
        </Button>
      }
    >
      {overrides.length === 0 ? (
        <p className="small muted">
          None. Add one to grant a calling member-data access without a code change (applied next sync).
        </p>
      ) : (
        overrides.map((o, i) => (
          <div key={i} className="list-tile" style={{ padding: '8px 0' }}>
            <Icon name={o['grants_access'] === false ? 'link_off' : 'key'} size={20} />
            <span className="list-tile__main">
              <span>{String(o['calling_match'])}</span>
              <span className="small muted" style={{ display: 'block' }}>
                {o['grants_access'] === false ? 'denies access' : 'grants access'}
                {o['note'] ? ` · ${String(o['note'])}` : ''}
              </span>
            </span>
            <IconButton
              icon="error"
              label="Remove"
              size={20}
              onClick={() => onRemove(Number(o['id']), String(o['calling_match']))}
            />
          </div>
        ))
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add a calling override"
        hideClose
        actions={
          <>
            <Button onClick={() => setOpen(false)}>Cancel</Button>
            <Button disabled={!match.trim()} onClick={submit}>
              Save
            </Button>
          </>
        }
      >
        <div className="stack" style={{ gap: 10 }}>
          <input
            className="input"
            placeholder="Calling contains… (e.g. Ward Mission Leader)"
            value={match}
            onChange={(e) => setMatch(e.target.value)}
          />
          <label className="row" style={{ gap: 8, alignItems: 'center' }}>
            <input type="checkbox" checked={grants} onChange={(e) => setGrants(e.target.checked)} />
            <span>Grants member-data access</span>
          </label>
          <input
            className="input"
            placeholder="Note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <p className="small muted">Case-insensitive substring match of the calling name.</p>
        </div>
      </Modal>
    </Card>
  );
}

function AdminsCard({
  admins,
  busy,
  onInvite,
  onRevoke,
}: {
  admins: Json[];
  busy: boolean;
  onInvite: (email: string) => void;
  onRevoke: (email: string) => void;
}) {
  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [me, setMe] = useState<string | undefined>(undefined);
  useEffect(() => {
    void supabase.auth.getUser().then(({ data }) => setMe(data.user?.email?.toLowerCase()));
  }, []);

  return (
    <Card
      title="Admins"
      trailing={
        <Button icon="person_add" disabled={busy} onClick={() => setInviteOpen(true)}>
          Invite
        </Button>
      }
    >
      {admins.map((a, i) => {
        const aEmail = String(a['email']);
        const isMe = aEmail.toLowerCase() === me;
        return (
          <div key={i} className="list-tile" style={{ padding: '8px 0' }}>
            <Icon name="shield" size={20} />
            <span className="list-tile__main">
              <span>{aEmail}</span>
              {a['invited_by_email'] != null && (
                <span className="small muted" style={{ display: 'block' }}>
                  invited by {String(a['invited_by_email'])}
                </span>
              )}
            </span>
            {isMe ? (
              <span className="chip" style={{ fontSize: 12 }}>
                you
              </span>
            ) : (
              <IconButton icon="error" label="Revoke" size={20} onClick={() => onRevoke(aEmail)} />
            )}
          </div>
        );
      })}

      <Modal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title="Invite an admin"
        hideClose
        actions={
          <>
            <Button onClick={() => setInviteOpen(false)}>Cancel</Button>
            <Button
              variant="filled"
              onClick={() => {
                const e = email.trim();
                setInviteOpen(false);
                setEmail('');
                if (e) onInvite(e);
              }}
            >
              Invite
            </Button>
          </>
        }
      >
        <label className="field">
          <span>Email</span>
          {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
          <input className="input" type="email" autoFocus placeholder="name@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
      </Modal>
    </Card>
  );
}
