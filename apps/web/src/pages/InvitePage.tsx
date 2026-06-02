// Power users — give someone your exact access. React port of invite_page.dart. They sign in with
// the invited email (a one-time code — no Church account needed) and see what you see, and can
// invite others. Backed by the invite_power_user / revoke_power_user RPCs (escalation-safe).

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { IconButton, Button } from '../components/ui';
import { Icon } from '../components/Icon';
import { CardSkeleton } from '../components/Skeletons';

interface Invitation {
  invited_email: string;
  role?: string;
  unit_id?: string | null;
  status?: string;
  invited_by_email?: string | null;
  created_at?: string;
}

interface Unit {
  id: string;
  name: string;
}

export function InvitePage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [units, setUnits] = useState<Unit[]>([]);
  const [unitId, setUnitId] = useState<string | null>(null);
  const [invites, setInvites] = useState<Invitation[] | null>(null);

  async function loadInvites() {
    const { data } = await supabase
      .from('invitations')
      .select('invited_email, role, unit_id, status, invited_by_email, created_at')
      .order('created_at', { ascending: false });
    setInvites((data ?? []) as Invitation[]);
  }

  useEffect(() => {
    void loadInvites();
    supabase
      .from('units')
      .select('id, name')
      .order('name')
      .then(({ data }) => setUnits((data ?? []) as Unit[]), () => {});
  }, []);

  async function invite() {
    const e = email.trim();
    if (!e) return;
    setBusy(true);
    setMsg(null);
    try {
      const params: Record<string, unknown> = { p_email: e };
      if (unitId != null) params['p_unit'] = unitId;
      const { data, error } = await supabase.rpc('invite_power_user', params);
      if (error) throw error;
      const n = Number(data);
      setMsg(`Invited ${e} (${n} scope${n === 1 ? '' : 's'}). They can sign in with that email.`);
      setOk(true);
      setEmail('');
      await loadInvites();
    } catch (err) {
      setMsg(`Could not invite: ${err instanceof Error ? err.message : err}`);
      setOk(false);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(e: string) {
    try {
      await supabase.rpc('revoke_power_user', { p_email: e });
    } finally {
      await loadInvites();
    }
  }

  // collapse multiple scope rows per email
  const byEmail = new Map<string, Invitation>();
  for (const r of invites ?? []) {
    if (!byEmail.has(r.invited_email)) byEmail.set(r.invited_email, r);
  }

  return (
    <div className="app-shell">
      <header className="appbar">
        <IconButton icon="chevron_left" label="Back" onClick={() => navigate(-1)} />
        <h1 className="appbar__title">Power users</h1>
      </header>
      <main className="page">
        <div className="maxw">
          <div style={{ padding: 16 }} className="stack">
            <p>
              Give someone your exact access. They sign in with the invited email (a one-time code is
              sent — no Church account needed), see what you see, and can invite others.
            </p>
            {units.length > 1 && (
              <label className="field" style={{ marginTop: 12 }}>
                <span>Access to</span>
                <select className="select" value={unitId ?? ''} onChange={(e) => setUnitId(e.target.value || null)}>
                  <option value="">Everything I can see</option>
                  {units.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} only
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="row" style={{ marginTop: 12, alignItems: 'flex-end' }}>
              <label className="field" style={{ flex: 1 }}>
                <span>Email to invite</span>
                <input
                  className="input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !busy) void invite();
                  }}
                />
              </label>
              <Button variant="filled" loading={busy} onClick={invite}>
                Invite
              </Button>
            </div>
            {msg && (
              <p style={{ marginTop: 10, color: ok ? 'var(--success)' : 'var(--error)' }}>{msg}</p>
            )}
          </div>
          <hr className="divider" style={{ margin: 0 }} />
          {invites == null ? (
            <div style={{ padding: 16 }}>
              <CardSkeleton lines={3} />
            </div>
          ) : byEmail.size === 0 ? (
            <p style={{ textAlign: 'center', padding: 24 }}>No power users invited yet.</p>
          ) : (
            <div>
              {[...byEmail.values()].map((r) => (
                <div key={r.invited_email} className="list-tile">
                  <Icon name={r.status === 'revoked' ? 'account' : 'account'} size={22} />
                  <span className="list-tile__main">
                    <span>{r.invited_email}</span>
                    <span className="small muted" style={{ display: 'block' }}>
                      {r.role} • {r.status}
                      {r.invited_by_email ? ` • by ${r.invited_by_email}` : ''}
                    </span>
                  </span>
                  {r.status !== 'revoked' && (
                    <Button onClick={() => revoke(r.invited_email)}>Revoke</Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
