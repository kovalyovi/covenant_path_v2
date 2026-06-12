// Admin · Ops console — React port of admin_page.dart. One place to monitor and operate the
// platform, gated server-side by app_admins (the broker checks with the service-role key). Panels
// load independently so a slow/failed section (e.g. GitHub Actions) only errors in its own card.
// Panels, in order: system health, data freshness, maintenance (dispatch a rescrape), diagnostics,
// admin management, enrolled stakes (cross-stake ops + per-stake sync/revoke), recent logins,
// endpoint health trend, recent Actions runs, changelog, calling overrides.

import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { admin } from '../lib/admin';
import { status as statusColors } from '../theme/tokens';
import { agoOrNever, dur, fmtDateTime } from '../logic/dates';
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

export function AdminPage() {
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

  return (
    <div className="app-shell">
      <header className="appbar">
        <IconButton icon="chevron_left" label="Back" onClick={() => navigate(-1)} />
        <h1 className="appbar__title">Admin · Ops console</h1>
        <span className="appbar__spacer" />
        <IconButton icon="refresh" label="Refresh" onClick={refresh} disabled={busy} />
      </header>
      <main className="page" style={{ position: 'relative' }}>
        <div className="maxw" style={{ maxWidth: 900, padding: 12 }}>
          <Panel key={`sys-${nonce}`} title="System" load={() => admin.summary()}>
            {(s) => (
              <>
                <HealthCard summary={s} />
                <FreshnessCard summary={s} />
                <MaintenanceCard summary={s} busy={busy} onRun={dispatch} />
                <LinksCard summary={s} />
              </>
            )}
          </Panel>
          <Panel key={`diag-${nonce}`} title="Diagnostics" load={() => admin.diagnostics()}>
            {(s) => <DiagnosticsCard diag={s} onCopy={(t) => navigator.clipboard.writeText(t)} toast={toast} />}
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
          <Panel key={`stakes-${nonce}`} title="Enrolled stakes" load={() => admin.enrolledStakes()}>
            {(s) => (
              <EnrolledStakesCard
                stakes={((s['stakes'] as Json[]) ?? [])}
                busy={busy}
                onRevoke={revokeStake}
                onSync={syncStake}
                onWipe={wipeStakeData}
                onRemove={removeStake}
              />
            )}
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
              const { data } = await supabase
                .from('calling_access_overrides')
                .select('id, calling_match, grants_access, note, created_by')
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
          <div className="scrim" style={{ background: 'rgba(0,0,0,0.2)' }}>
            <span className="spinner spinner--lg" role="status" aria-label="Working" />
          </div>
        )}
      </main>

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
    return (
      <Card title={`${title}…`}>
        <CardSkeleton lines={3} />
      </Card>
    );
  }
  if (state.error) {
    return (
      <Card title={title}>
        <p className="small">
          Couldn't load: {state.error}
          {errorHint ? `\n\n${errorHint}` : ''}
        </p>
      </Card>
    );
  }
  return <>{children(state.data as T)}</>;
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

function HealthCard({ summary }: { summary: Json }) {
  const brokerOk = (summary['broker'] as Json)?.['ok'] === true;
  const sb = (summary['supabase'] as Json) ?? {};
  const githubConfigured = summary['github_configured'] === true;
  return (
    <Card title="System health">
      <div className="wrap" style={{ gap: 10 }}>
        <Pill label="Broker" ok={brokerOk} />
        <Pill label="Supabase" ok={sb['ok'] === true} />
        <Pill label="GitHub Actions" ok={githubConfigured} offText="not linked" />
      </div>
    </Card>
  );
}

function FreshnessCard({ summary }: { summary: Json }) {
  const sb = (summary['supabase'] as Json) ?? {};
  return (
    <Card title="Data freshness">
      <Kv k="Last member update" v={agoOrNever(sb['last_member_update'])} />
      <Kv k="Last stake sync" v={agoOrNever(sb['last_stake_sync'])} />
      <hr className="divider" />
      <div className="wrap" style={{ gap: 18 }}>
        <Stat label="Members" v={sb['members']} />
        <Stat label="Units" v={sb['units']} />
        <Stat label="Stakes" v={sb['stakes']} />
        <Stat label="Admins" v={sb['admins']} />
      </div>
    </Card>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div className="row" style={{ padding: '3px 0', justifyContent: 'space-between' }}>
      <span>{k}</span>
      <strong>{v}</strong>
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

function LinksCard({ summary }: { summary: Json }) {
  const links = ((summary['links'] as Json) ?? {}) as Record<string, string>;
  const entries = Object.entries(links);
  if (entries.length === 0) return null;
  return (
    <Card title="Tools & dashboards">
      <div className="wrap">
        {entries.map(([k, v]) => (
          <button key={k} type="button" className="chip" onClick={() => openUrl(v)}>
            <Icon name="open_in_new" size={16} />
            {k}
          </button>
        ))}
      </div>
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

function EnrolledStakesCard({
  stakes,
  busy,
  onRevoke,
  onSync,
  onWipe,
  onRemove,
}: {
  stakes: Json[];
  busy: boolean;
  onRevoke: (id: string, name: string) => void;
  onSync: (unit: string, name: string) => void;
  onWipe: (id: string, name: string) => void;
  onRemove: (id: string, name: string) => void;
}) {
  if (stakes.length === 0) return <Card title="Enrolled stakes">No stakes yet.</Card>;
  return (
    <Card title={`Enrolled stakes (${stakes.length})`}>
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
          credColor = '#e53935';
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
        return (
          <div key={i} style={{ padding: '6px 0' }}>
            <div className="row">
              <strong>{name}</strong>
              {/* Stable LCR stake ID — stakes get renamed, so the ID is how you identify them (#9). */}
              {unitNumber && unitNumber !== 'null' && (
                <span className="small muted" style={{ fontFamily: 'monospace', marginLeft: 8, flex: 1 }}>
                  ID {unitNumber}
                </span>
              )}
              {(!unitNumber || unitNumber === 'null') && <span style={{ flex: 1 }} />}
              {running && <span className="spinner" aria-hidden="true" style={{ width: 14, height: 14 }} />}
              {!running && credState !== 'revoked' && credState !== 'none' && (
                <IconButton icon="sync" label="Sync this stake now" size={18} disabled={busy} onClick={() => onSync(unitNumber, name)} />
              )}
              {(credState === 'active' || credState === 'stale') && (
                <IconButton icon="link_off" label="Revoke sync credential" size={18} disabled={busy} onClick={() => onRevoke(stakeId, name)} />
              )}
              <button type="button" disabled={busy} onClick={() => onWipe(stakeId, name)}
                title="Wipe member data (keeps the stake + roles + credential)"
                style={{ background: 'none', border: 'none', color: '#e65100', cursor: 'pointer', fontSize: 12, padding: '2px 6px', fontWeight: 600 }}>
                Wipe
              </button>
              <button type="button" disabled={busy} onClick={() => onRemove(stakeId, name)}
                title="Remove stake completely (irreversible)"
                style={{ background: 'none', border: 'none', color: '#c62828', cursor: 'pointer', fontSize: 12, padding: '2px 6px', fontWeight: 600 }}>
                Remove
              </button>
            </div>
            <div className="wrap" style={{ gap: 8, alignItems: 'center' }}>
              <span className="chip" style={{ borderColor: credColor, color: credColor, background: `${credColor}1f`, fontSize: 12 }}>
                {credLabel}
              </span>
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
              <p className="tiny" style={{ marginTop: 2, color: '#e53935' }}>
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
