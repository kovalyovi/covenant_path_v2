// Network-edge mocks: page.route() interceptors for the two fake hosts the dev server is
// configured with (playwright.config.ts E2E_ENV). Nothing ever leaves the browser — every
// supabase-js and broker request is answered here, including the CORS preflights Chromium
// sends for cross-origin JSON/authorized requests.
//
//  • mockSupabase(page, fixtures): gotrue auth endpoints (verify/token/user/logout) with canonical
//    session shapes + PostgREST tables (stakes / members / member_comments, generic `eq.` filters)
//    + the is_admin RPC. POSTed member_comments are appended to the in-memory fixture set so the
//    UI's read-after-write works like the real backend.
//  • mockBroker(page, overrides): defaults for every endpoint the app calls (/health, /log,
//    /auth/password, /auth/mfa/*, /auth/enrollment-status, /auth/sync-now, /auth/schedule,
//    /auth/google/status, /auth/revoke); per-test overrides by "METHOD /path" (or bare "/path"),
//    as a static reply or a function of the call index — and 'abort' to simulate a cold broker.
//
// Both return a recorder of every non-preflight request for behavioural assertions (e.g. "the
// second /auth/password carried enroll:true").

import type { Page, Route, Request } from '@playwright/test';
import {
  brokerLogin, defaultComments, defaultMembers, enrollmentStatus, stakeRow, type Row,
} from './fixtures';
import { fakeSession, fakeUser } from './session';

export const SUPABASE_URL = 'http://supabase.local.test';
export const BROKER_URL = 'http://broker.local.test';

// ---- CORS plumbing ------------------------------------------------------------------------------

const CORS_HEADERS: Record<string, string> = {
  'access-control-allow-origin': '*',
  'access-control-expose-headers': '*',
};

/** Answer a CORS preflight, echoing the requested headers (a `*` wildcard does NOT cover
 *  Authorization in Chromium, so the echo is load-bearing for the bearer-token endpoints). */
async function fulfillPreflight(route: Route): Promise<void> {
  const requested = (await route.request().headerValue('access-control-request-headers')) ?? '*';
  await route.fulfill({
    status: 204,
    headers: {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
      'access-control-allow-headers': requested,
      'access-control-max-age': '600',
    },
  });
}

async function fulfillJson(route: Route, status: number, body?: unknown): Promise<void> {
  if (body === undefined) {
    await route.fulfill({ status, headers: { ...CORS_HEADERS } });
    return;
  }
  await route.fulfill({
    status,
    headers: { ...CORS_HEADERS, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// ---- Shared recorder ----------------------------------------------------------------------------

export interface RecordedCall {
  method: string;
  path: string;
  url: string;
  /** Parsed JSON request body (null when absent / not JSON). */
  body: Row | null;
}

export interface Recorder {
  calls: RecordedCall[];
  /** All non-preflight calls to an exact pathname. */
  callsTo(path: string): RecordedCall[];
}

function makeRecorder(): Recorder & { push(c: RecordedCall): void } {
  const calls: RecordedCall[] = [];
  return {
    calls,
    push: (c) => calls.push(c),
    callsTo: (path) => calls.filter((c) => c.path === path),
  };
}

function parseBody(request: Request): Row | null {
  const raw = request.postData();
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Row;
  } catch {
    return null;
  }
}

// ---- Supabase mock ------------------------------------------------------------------------------

export interface SupabaseFixtures {
  /** Rows for `stakes` (default: the Testvale stake). Pass [] for a viewer with no visible stake. */
  stakes?: Row[];
  /** Rows for `members` (default: the 4 value-variant fixtures). */
  members?: Row[];
  /** Rows for `member_comments` (default: one note on Avery). POSTs append here. */
  comments?: Row[];
  /** rpc/is_admin result (default false). */
  isAdmin?: boolean;
}

/** Apply PostgREST-style `<col>=eq.<value>` query filters to fixture rows. */
function applyEqFilters(rows: Row[], url: URL): Row[] {
  let out = rows;
  for (const [key, value] of url.searchParams.entries()) {
    if (value.startsWith('eq.')) {
      const want = value.slice(3);
      out = out.filter((r) => String(r[key]) === want);
    }
  }
  return out;
}

export async function mockSupabase(page: Page, fixtures: SupabaseFixtures = {}): Promise<Recorder> {
  const stakes = fixtures.stakes ?? [stakeRow()];
  const members = fixtures.members ?? defaultMembers();
  const comments = [...(fixtures.comments ?? defaultComments())]; // mutable: POSTs append
  const isAdmin = fixtures.isAdmin === true;
  const recorder = makeRecorder();

  await page.route(`${SUPABASE_URL}/**`, async (route) => {
    const request = route.request();
    const method = request.method();
    if (method === 'OPTIONS') return fulfillPreflight(route);

    const url = new URL(request.url());
    const path = url.pathname;
    recorder.push({ method, path, url: request.url(), body: parseBody(request) });

    // -- gotrue auth (canonical shapes) --
    if (path === '/auth/v1/verify' && method === 'POST') {
      const body = parseBody(request);
      const email = typeof body?.email === 'string' ? (body.email as string) : undefined;
      return fulfillJson(route, 200, fakeSession(email));
    }
    if (path === '/auth/v1/token' && method === 'POST') {
      return fulfillJson(route, 200, fakeSession());
    }
    if (path === '/auth/v1/user' && method === 'GET') {
      return fulfillJson(route, 200, fakeUser());
    }
    if (path === '/auth/v1/logout') {
      return fulfillJson(route, 204);
    }

    // -- PostgREST --
    if (path === '/rest/v1/rpc/is_admin') {
      return fulfillJson(route, 200, isAdmin);
    }
    if (path === '/rest/v1/stakes' && method === 'GET') {
      return fulfillJson(route, 200, applyEqFilters(stakes, url));
    }
    if (path === '/rest/v1/members' && method === 'GET') {
      return fulfillJson(route, 200, applyEqFilters(members, url));
    }
    if (path === '/rest/v1/member_comments') {
      if (method === 'POST') {
        const body = parseBody(request);
        const rows = Array.isArray(body) ? (body as Row[]) : body ? [body] : [];
        for (const r of rows) comments.push({ created_at: new Date().toISOString(), ...r });
        return fulfillJson(route, 201); // PostgREST return=minimal: empty body
      }
      return fulfillJson(route, 200, applyEqFilters(comments, url));
    }

    return fulfillJson(route, 404, { message: `e2e: no Supabase mock for ${method} ${path}` });
  });

  return recorder;
}

// ---- Broker mock --------------------------------------------------------------------------------

export type BrokerReply = { status?: number; json?: unknown } | 'abort';
export type BrokerRoute =
  | BrokerReply
  | ((ctx: { call: number; body: Row; request: Request }) => BrokerReply | Promise<BrokerReply>);

/** Keyed by "METHOD /path" (preferred) or bare "/path" (any method). */
export type BrokerOverrides = Record<string, BrokerRoute>;

function brokerDefaults(): Record<string, BrokerReply> {
  return {
    'GET /health': { json: { ok: true, lcr: 'ok' } },
    'POST /log': { json: {} },
    'GET /auth/enrollment-status': { json: enrollmentStatus() },
    'POST /auth/password': { json: brokerLogin() },
    'POST /auth/mfa/select': { json: { ok: true } },
    'POST /auth/mfa/verify': { json: brokerLogin() },
    'POST /auth/sync-now': { json: { coverage_complete: true, last_synced_at: new Date().toISOString() } },
    'GET /auth/schedule': { json: { eligible: false } },
    'POST /auth/schedule': { json: { ok: true } },
    'GET /auth/google/status': { json: { eligible: false } },
    'POST /auth/revoke': { json: { ok: true } },
  };
}

export async function mockBroker(page: Page, overrides: BrokerOverrides = {}): Promise<Recorder> {
  const recorder = makeRecorder();
  const counts = new Map<string, number>();
  const defaults = brokerDefaults();

  await page.route(`${BROKER_URL}/**`, async (route) => {
    const request = route.request();
    const method = request.method();
    if (method === 'OPTIONS') return fulfillPreflight(route);

    const path = new URL(request.url()).pathname;
    const key = `${method} ${path}`;
    const call = (counts.get(key) ?? 0) + 1;
    counts.set(key, call);
    const body = parseBody(request);
    recorder.push({ method, path, url: request.url(), body });

    const spec = overrides[key] ?? overrides[path] ?? defaults[key];
    if (spec === undefined) {
      return fulfillJson(route, 404, { detail: `e2e: no broker mock for ${key}` });
    }
    const reply = typeof spec === 'function' ? await spec({ call, body: body ?? {}, request }) : spec;
    if (reply === 'abort') return route.abort('failed');
    return fulfillJson(route, reply.status ?? 200, reply.json);
  });

  return recorder;
}
