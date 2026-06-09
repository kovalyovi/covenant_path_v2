// Admin · full-list detail views (#7): /admin/runs · /admin/changelog · /admin/logins. The ops
// console front page shows only the top few rows of each long section; these routes hold the FULL
// history with client-side pagination. Server-gated like the console (broker require_admin; the
// logins query is admin-only RLS).

import { useEffect, useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { admin } from '../lib/admin';
import { status as statusColors } from '../theme/tokens';
import { agoOrNever, dur } from '../logic/dates';
import { Icon } from '../components/Icon';
import { IconButton, Button } from '../components/ui';
import { CardSkeleton } from '../components/Skeletons';

type Json = Record<string, unknown>;

const PAGE_SIZE = 25;

const SECTIONS: Record<string, { title: string; hint: string }> = {
  runs: { title: 'Actions runs', hint: 'Every recent GitHub Actions run (newest first).' },
  changelog: { title: 'Changelog', hint: 'Recent commits to main (newest first).' },
  logins: { title: 'Login history', hint: 'Every recorded sign-in: who, outcome, callings, scope.' },
};

export function AdminListPage() {
  const { section = '' } = useParams();
  const navigate = useNavigate();
  const meta = SECTIONS[section];
  const [rows, setRows] = useState<Json[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    setRows(null);
    setError(null);
    setPage(0);
    if (!meta) return;
    (async () => {
      try {
        if (section === 'runs') {
          const a = await admin.actions(100, 1);
          setRows(((a['runs'] as Json[]) ?? []));
        } else if (section === 'changelog') {
          const a = await admin.actions(1, 100);
          setRows(((a['commits'] as Json[]) ?? []));
        } else {
          const { data, error: e } = await supabase
            .from('login_audit')
            .select('at, email, name, stake_name, callings, role_scope, authorized, outcome')
            .order('at', { ascending: false })
            .limit(500);
          if (e) throw e;
          setRows((data ?? []) as Json[]);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [section, meta]);

  if (!meta) return <Navigate to="/admin" replace />;

  const total = rows?.length ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visible = (rows ?? []).slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="app-shell">
      <header className="appbar">
        <IconButton icon="chevron_left" label="Back to ops console" onClick={() => navigate('/admin')} />
        <h1 className="appbar__title">Admin · {meta.title}</h1>
        <span className="appbar__spacer" />
        {total > 0 && <span className="small muted">{total} total</span>}
      </header>
      <main className="page">
        <div className="page__inner" style={{ maxWidth: 860 }}>
          <p className="small muted">{meta.hint}</p>
          {error && (
            <p style={{ color: 'var(--error)' }} role="alert">
              Couldn't load: {error}
            </p>
          )}
          {!rows && !error && <CardSkeleton lines={8} />}
          {rows && rows.length === 0 && <p className="muted">Nothing recorded yet.</p>}
          {visible.map((r, i) =>
            section === 'runs' ? (
              <RunTile key={i} r={r} />
            ) : section === 'changelog' ? (
              <CommitTile key={i} c={r} />
            ) : (
              <LoginTile key={i} r={r} />
            ),
          )}
          {pages > 1 && (
            <nav className="row" style={{ justifyContent: 'center', gap: 12, padding: '14px 0' }} aria-label="Pagination">
              <Button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                ← Newer
              </Button>
              <span className="small muted">
                Page {page + 1} of {pages}
              </span>
              <Button disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>
                Older →
              </Button>
            </nav>
          )}
        </div>
      </main>
    </div>
  );
}

/** "View all (N) →" trailing link for the console's truncated sections. */
export function ViewAllLink({ to, n }: { to: string; n: number }) {
  return (
    <Link to={to} className="small" style={{ color: 'var(--primary)', fontWeight: 600, whiteSpace: 'nowrap' }}>
      View all ({n}) →
    </Link>
  );
}

function openUrl(url?: string) {
  if (url) window.open(url, '_blank', 'noopener');
}

function RunTile({ r }: { r: Json }) {
  const inProgress = r['status'] === 'in_progress' || r['status'] === 'queued';
  const ok = r['status'] === 'completed' ? r['conclusion'] === 'success' : null;
  return (
    <button
      type="button"
      className="list-tile"
      style={{ padding: '8px 0', width: '100%', background: 'transparent', border: 'none', textAlign: 'left', color: 'inherit', borderBottom: '1px solid var(--outline-variant)' }}
      onClick={() => openUrl(r['html_url'] as string)}
    >
      {ok == null ? (
        inProgress ? (
          <span className="spinner" aria-hidden="true" style={{ width: 18, height: 18 }} />
        ) : (
          <Icon name="schedule" size={20} color={statusColors.info} />
        )
      ) : (
        <Icon name={ok ? 'check_circle' : 'error'} size={20} color={ok ? statusColors.success : statusColors.danger} />
      )}
      <span className="list-tile__main">
        <span>
          {String(r['name'])} #{String(r['run_number'])}
        </span>
        <span className="small muted" style={{ display: 'block' }}>
          {String(r['event'])} · {agoOrNever(r['created_at'])}
          {dur(r['duration_seconds']) && ` · ${r['status'] === 'completed' ? 'took' : 'running'} ${dur(r['duration_seconds'])}`}
        </span>
      </span>
      <Icon name="open_in_new" size={14} />
    </button>
  );
}

function CommitTile({ c }: { c: Json }) {
  return (
    <button
      type="button"
      className="list-tile"
      style={{ padding: '8px 0', width: '100%', background: 'transparent', border: 'none', textAlign: 'left', color: 'inherit', borderBottom: '1px solid var(--outline-variant)' }}
      onClick={() => openUrl(c['html_url'] as string)}
    >
      <Icon name="commit" size={18} />
      <span className="list-tile__main">
        <span>{String(c['message'])}</span>
        <span className="small muted" style={{ display: 'block' }}>
          {String(c['sha'])} · {String(c['author'] ?? '')} · {agoOrNever(c['date'])}
        </span>
      </span>
      {c['html_url'] != null && <Icon name="open_in_new" size={14} />}
    </button>
  );
}

function LoginTile({ r }: { r: Json }) {
  const outcome = String(r['outcome'] ?? r['authorized'] ?? '');
  const good = outcome === 'allowed' || outcome === 'enrolled';
  const callings = (Array.isArray(r['callings']) ? (r['callings'] as unknown[]) : []).join(', ');
  const scope = String(r['role_scope'] ?? '');
  const at = String(r['at'] ?? '');
  return (
    <div style={{ padding: '6px 0', borderBottom: '1px solid var(--outline-variant)' }}>
      <div className="row">
        <strong style={{ flex: 1 }}>{String(r['email'] ?? '(unknown email)')}</strong>
        <span style={{ color: good ? statusColors.successFg : statusColors.warning, fontWeight: 600 }}>{outcome || '—'}</span>
      </div>
      {r['stake_name'] ? <div className="small muted">{String(r['stake_name'])}</div> : null}
      {callings ? <div className="small muted">Callings: {callings}</div> : null}
      {scope ? <div className="small muted">Sees: {scope}</div> : null}
      <div className="small muted">{at.slice(0, 16).replace('T', ' ')}</div>
    </div>
  );
}
