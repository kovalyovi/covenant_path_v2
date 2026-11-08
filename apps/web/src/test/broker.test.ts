// Regression tests for the broker client's cold-start WARM GATE.
//
// Root cause of the "sign-in took forever / timed out" report: the free-tier broker sleeps after
// ~15 min idle and restarts on every deploy, so the heavy /auth/password Okta call could land on a
// cold container and absorb the whole ~50s wake. The fix: ensureWarm() pings /health (with cold-start
// retry) BEFORE any login-completing POST, so the expensive call always hits a warm broker. These
// tests pin that behaviour so it can never silently regress.

import { describe, it, expect, vi, beforeEach } from 'vitest';

// brokerUrl must be non-empty for `available` to be true.
vi.mock('../lib/config', () => ({ brokerUrl: 'https://broker.test' }));
vi.mock('../lib/supabase', () => ({ currentAccessToken: async () => 'token' }));

import { BrokerClient } from '../lib/broker';

const HEALTH = 'https://broker.test/health';
const PASSWORD = 'https://broker.test/auth/password';

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  } as unknown as Response;
}

describe('broker warm gate (cold-start fix)', () => {
  let calls: string[];

  beforeEach(() => {
    calls = [];
  });

  it('pings /health BEFORE the /auth/password POST (so Okta never eats the cold start)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url === HEALTH) return jsonResponse({ ok: true });
      return jsonResponse({ session: { email: 'a@b.c', otp: '123456' } });
    }));

    const client = new BrokerClient();
    const r = await client.password('user', 'pass');

    // The very first network call must be the health wake-up, and only then the login POST.
    expect(calls[0]).toBe(HEALTH);
    expect(calls).toContain(PASSWORD);
    expect(calls.indexOf(HEALTH)).toBeLessThan(calls.indexOf(PASSWORD));
    expect(r.email).toBe('a@b.c');
    expect(r.otp).toBe('123456');
  });

  it('retries /health while the broker is cold, then proceeds once it wakes', async () => {
    vi.useFakeTimers();
    let healthHits = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url === HEALTH) {
        healthHits += 1;
        if (healthHits < 3) throw new Error('cold: failed to fetch'); // container still waking
        return jsonResponse({ ok: true });
      }
      return jsonResponse({ session: { email: 'a@b.c', otp: '123456' } });
    }));

    const client = new BrokerClient();
    const statuses: string[] = [];
    client.onStatus = (m) => statuses.push(m);

    const p = client.password('user', 'pass');
    // Drive the cold-start retry backoff (3s + 6s between health attempts) to completion.
    await vi.runAllTimersAsync();
    const r = await p;

    expect(healthHits).toBe(3); // failed twice, succeeded on the third
    expect(statuses.some((s) => /waking up/i.test(s))).toBe(true);
    expect(r.otp).toBe('123456'); // login still completes after the wake
    vi.useRealTimers();
  });

  it('shares a single in-flight warm-up between an early warmUp() and the submit', async () => {
    let healthHits = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url === HEALTH) {
        healthHits += 1;
        return jsonResponse({ ok: true });
      }
      return jsonResponse({ session: { email: 'a@b.c', otp: '123456' } });
    }));

    const client = new BrokerClient();
    client.warmUp(); // fired on login-screen mount
    await client.password('user', 'pass'); // submit immediately after

    // Both should ride ONE health wake, not two racing cold-start pings.
    expect(healthHits).toBe(1);
  });

  it('skips the redundant /health when the broker proved awake under 2 minutes ago', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url === HEALTH) return jsonResponse({ ok: true });
      return jsonResponse({ session: { email: 'a@b.c', otp: '123456' } });
    }));

    const client = new BrokerClient();
    await client.password('user', 'pass'); // first login: health gate runs
    await client.password('user', 'pass'); // immediate retry: the response itself proved it's awake

    expect(calls.filter((u) => u === HEALTH).length).toBe(1);
    expect(calls.filter((u) => u === PASSWORD).length).toBe(2);
  });
});

describe('broker enroll mapping (0068 highest-wins)', () => {
  it('maps stored_as_backup + effective_provider so the dialog can show the backup note', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === HEALTH) return jsonResponse({ ok: true });
      return jsonResponse({
        session: { email: 'junior@x.org', otp: '123456' },
        enroll: {
          stored: true, authorized: true, stored_as_backup: true,
          effective_provider: 'Boss', would_downgrade: true,
        },
      });
    }));

    const r = await new BrokerClient().password('user', 'pass');
    expect(r.stored).toBe(true);
    expect(r.storedAsBackup).toBe(true);
    expect(r.effectiveProvider).toBe('Boss');
    // The R4 warning is still computed, but it no longer blocks storage.
    expect(r.wouldDowngrade).toBe(true);
  });

  it('maps is_credential_holder + holders from enrollment-status', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === HEALTH) return jsonResponse({ ok: true });
      return jsonResponse({
        stake_name: 'Test Stake', stake_id: 'stake-1', unit_number: 503991,
        member_count: 42, has_data: true, patriarchal_pending: 0,
        credential: {
          state: 'active', complete: false, principal_name: 'Boss',
          is_provider: false, is_credential_holder: true, holders: 2,
        },
      });
    }));

    const s = await new BrokerClient().enrollmentStatus();
    expect(s.credential.isProvider).toBe(false);
    expect(s.credential.isCredentialHolder).toBe(true);
    expect(s.credential.holders).toBe(2);
  });
});
