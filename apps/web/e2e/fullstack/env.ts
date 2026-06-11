// FULLSTACK-lane env + service-role REST helpers (node-side only — values are secrets from the
// repo .env and must never be logged or shipped to the browser). The browser gets only the anon
// key via vite env (playwright.config.ts); these helpers let the SPEC seed-check and clean up
// rows in the TEST project directly.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');

/** Minimal .env parser (KEY=value, optional quotes, # comments). Process env wins. */
export function repoEnv(): Record<string, string> {
  const out: Record<string, string> = {};
  const file = path.join(REPO_ROOT, '.env');
  if (fs.existsSync(file)) {
    for (const line of fs.readFileSync(file, 'utf-8').split(/\r?\n/)) {
      const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)$/.exec(line);
      if (!m) continue;
      out[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
    }
  }
  for (const [k, v] of Object.entries(process.env)) {
    if (v != null && v !== '') out[k] = v;
  }
  return out;
}

export interface FullstackEnv {
  url: string;
  anon: string;
  service: string;
}

/** The CP_TEST_* trio; throws with the fix when missing or pointing at production. */
export function fullstackEnv(): FullstackEnv {
  const env = repoEnv();
  const url = (env.CP_TEST_SUPABASE_URL || '').replace(/\/$/, '');
  const anon = env.CP_TEST_SUPABASE_ANON_KEY || '';
  const service = env.CP_TEST_SUPABASE_SERVICE_ROLE_KEY || '';
  if (!url || !anon || !service) {
    throw new Error(
      'E2E_FULLSTACK=1 needs CP_TEST_SUPABASE_URL / _ANON_KEY / _SERVICE_ROLE_KEY ' +
        '(repo .env or process env) — a dedicated TEST Supabase project, never prod.',
    );
  }
  const prod = (env.SUPABASE_URL || '').replace(/\/$/, '');
  if (prod && url === prod) {
    throw new Error('REFUSING: CP_TEST_SUPABASE_URL equals SUPABASE_URL (production).');
  }
  return { url, anon, service };
}

function svcHeaders(e: FullstackEnv): Record<string, string> {
  return {
    apikey: e.service,
    Authorization: `Bearer ${e.service}`,
    'Content-Type': 'application/json',
  };
}

/** Service-role GET → parsed JSON rows. */
export async function svcRows<T = Record<string, unknown>>(restPath: string): Promise<T[]> {
  const e = fullstackEnv();
  const r = await fetch(`${e.url}/rest/v1/${restPath}`, { headers: svcHeaders(e) });
  if (!r.ok) throw new Error(`svcRows ${restPath} -> ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return (await r.json()) as T[];
}

/** Service-role DELETE (returns deleted count via representation). */
export async function svcDelete(restPath: string): Promise<number> {
  const e = fullstackEnv();
  const r = await fetch(`${e.url}/rest/v1/${restPath}`, {
    method: 'DELETE',
    headers: { ...svcHeaders(e), Prefer: 'return=representation' },
  });
  if (!r.ok) throw new Error(`svcDelete ${restPath} -> ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const body = await r.text();
  return body ? (JSON.parse(body) as unknown[]).length : 0;
}

/** The seeded Testvale stake id (unit 999001). */
export async function testStakeId(): Promise<string> {
  const rows = await svcRows<{ id: string }>('stakes?select=id&unit_number=eq.999001&limit=1');
  if (rows.length === 0) throw new Error('test project not seeded — run: python -m tests.seed');
  return rows[0].id;
}

/** Current credential row for the Testvale stake (or null). */
export async function testCredential(): Promise<Record<string, unknown> | null> {
  const stake = await testStakeId();
  const rows = await svcRows(
    `stake_credentials?select=revoked,principal_email,last_failed_at&stake_id=eq.${stake}&limit=1`,
  );
  return rows[0] ?? null;
}

/** Remove any credential rows for the Testvale stake (keeps enroll offers deterministic). */
export async function deleteTestCredential(): Promise<number> {
  const stake = await testStakeId();
  return svcDelete(`stake_credentials?stake_id=eq.${stake}`);
}

/** Latest login_audit row for an email (the broker writes them on every attempt). */
export async function latestAudit(email: string): Promise<Record<string, unknown> | null> {
  const rows = await svcRows(
    `login_audit?select=outcome,authorized,phase&email=eq.${encodeURIComponent(email)}` +
      '&order=at.desc&limit=1',
  );
  return rows[0] ?? null;
}
