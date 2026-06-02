// Thin client for the Church-login auth broker (backend/auth_broker). The browser can't call the
// Church's Okta directly (CORS); the broker does it server-side and hands back a Supabase session
// OTP the app verifies. Ported from apps/viewer/lib/broker_client.dart — same endpoints, same
// cold-start retry (Render free tier sleeps when idle), same warm-up (N5), same N2 authorized flag.

import { brokerUrl } from './config';
import { currentAccessToken } from './supabase';

export class BrokerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BrokerError';
  }
}

/** One MFA factor offered by Okta (e.g. "Text message to •••1234"). */
export interface BrokerFactor {
  id: string;
  label: string;
  method: string;
}

export function factorFromJson(j: Record<string, unknown>): BrokerFactor {
  return {
    id: String(j['id']),
    label: String(j['label'] ?? j['method'] ?? 'Code'),
    method: String(j['method'] ?? ''),
  };
}

/** Result of a step: either a verifiable Supabase session, or an MFA challenge to continue. */
export interface BrokerResult {
  email?: string;
  otp?: string;
  loginId?: string;
  factors: BrokerFactor[];
  name?: string;
  /** N2: whether the calling has covenant-path access. null = unknown (don't block); false = block. */
  authorized?: boolean | null;
}

export function mfaRequired(r: BrokerResult): boolean {
  return r.loginId != null && r.otp == null;
}

export interface CredentialInfo {
  state: 'none' | 'active' | 'revoked' | string;
  complete: boolean;
  principalName?: string | null;
  isProvider: boolean;
  enrolledAt?: string | null;
}

export interface EnrollmentStatus {
  stakeName?: string | null;
  stakeId?: string | null;
  lastSyncedAt?: string | null;
  memberCount: number;
  hasData: boolean;
  noRole: boolean;
  credential: CredentialInfo;
}

function credFromJson(j: Record<string, unknown>): CredentialInfo {
  return {
    state: (j['state'] as string) ?? 'none',
    complete: j['complete'] === true,
    principalName: (j['principal_name'] as string) ?? null,
    isProvider: j['is_provider'] === true,
    enrolledAt: (j['enrolled_at'] as string) ?? null,
  };
}

function enrollmentFromJson(j: Record<string, unknown>): EnrollmentStatus {
  return {
    stakeName: (j['stake_name'] as string) ?? null,
    stakeId: (j['stake_id'] as string) ?? null,
    lastSyncedAt: (j['last_synced_at'] as string) ?? null,
    memberCount: Number(j['member_count'] ?? 0) || 0,
    hasData: j['has_data'] === true,
    noRole: j['status'] === 'no_role',
    credential: credFromJson((j['credential'] as Record<string, unknown>) ?? {}),
  };
}

// Free hosting sleeps when idle; the first request after a sleep can fail (no CORS header on the
// holding page → "Failed to fetch"). Retry across ~63s so a cold start resolves itself.
const RETRY_DELAYS_MS = [3000, 6000, 9000, 12000, 15000, 18000];

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function fetchWithTimeout(url: string, init: RequestInit, ms: number): Promise<Response> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

export class BrokerClient {
  /** Lets the login screen show a "waking up the sign-in service…" message during cold-start retries. */
  onStatus?: (message: string) => void;

  get available(): boolean {
    return brokerUrl.length > 0;
  }

  /**
   * N5: wake the free-tier broker early — fire a cheap /health ping when the login screen appears,
   * so it spins up while the user types, hiding the ~30-60s cold start. Fire-and-forget.
   */
  warmUp(): void {
    if (!this.available) return;
    fetchWithTimeout(`${brokerUrl}/health`, { method: 'GET' }, 30_000).catch(() => {});
  }

  private async postJson(path: string, body: unknown): Promise<Record<string, unknown>> {
    if (!this.available) throw new BrokerError('Church login is not configured (BROKER_URL).');
    let resp: Response | null = null;
    let lastErr: unknown;
    for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
      try {
        resp = await fetchWithTimeout(
          `${brokerUrl}${path}`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
          30_000,
        );
        break; // got an HTTP response (success or error) — stop retrying
      } catch (e) {
        lastErr = e;
        if (attempt < RETRY_DELAYS_MS.length) {
          this.onStatus?.('Waking up the sign-in service… this can take up to a minute on first use.');
          await delay(RETRY_DELAYS_MS[attempt]);
        }
      }
    }
    if (resp == null) {
      throw new BrokerError(
        'Could not reach the sign-in service after several tries. It may be starting up — ' +
          `please try again in a minute. (${String(lastErr)})`,
      );
    }
    let data: Record<string, unknown>;
    try {
      data = (await resp.json()) as Record<string, unknown>;
    } catch {
      throw new BrokerError(`Sign-in service error (${resp.status}).`);
    }
    if (resp.status >= 400) {
      throw new BrokerError(String(data['detail'] ?? `Sign-in failed (${resp.status}).`));
    }
    return data;
  }

  private async post(path: string, body: unknown): Promise<BrokerResult> {
    const data = await this.postJson(path, body);
    if (data['status'] === 'mfa_required') {
      return {
        loginId: String(data['login_id']),
        factors: ((data['factors'] as Record<string, unknown>[]) ?? []).map(factorFromJson),
      };
    }
    const session = (data['session'] as Record<string, unknown>) ?? {};
    const enroll = data['enroll'] as Record<string, unknown> | undefined;
    return {
      email: (session['email'] as string) ?? undefined,
      otp: (session['otp'] as string) ?? undefined,
      name: (data['identity_name'] as string) ?? undefined,
      factors: [],
      // N2: only a present, explicit `false` blocks; absent/errored enroll → null (don't block).
      authorized:
        enroll != null && Object.prototype.hasOwnProperty.call(enroll, 'authorized')
          ? (enroll['authorized'] as boolean | null)
          : null,
    };
  }

  password(username: string, password: string, enroll = false): Promise<BrokerResult> {
    return this.post('/auth/password', { username, password, enroll });
  }

  selectFactor(loginId: string, factorId: string): Promise<BrokerResult> {
    return this.post('/auth/mfa/select', { login_id: loginId, factor_id: factorId });
  }

  verifyMfa(loginId: string, code: string, enroll = false): Promise<BrokerResult> {
    return this.post('/auth/mfa/verify', { login_id: loginId, code, enroll });
  }

  /** Email-OTP relay (for networks that can't reach Supabase directly). */
  async emailStart(email: string): Promise<void> {
    await this.postJson('/auth/email/start', { email });
  }

  emailVerify(email: string, code: string): Promise<Record<string, unknown>> {
    return this.postJson('/auth/email/verify', { email, code });
  }

  async enrollmentStatus(): Promise<EnrollmentStatus> {
    if (!this.available) throw new BrokerError('Broker not configured.');
    const token = await currentAccessToken();
    if (!token) throw new BrokerError('Not signed in.');
    const resp = await fetchWithTimeout(
      `${brokerUrl}/auth/enrollment-status`,
      { method: 'GET', headers: { Authorization: `Bearer ${token}` } },
      20_000,
    );
    let data: Record<string, unknown>;
    try {
      data = (await resp.json()) as Record<string, unknown>;
    } catch {
      throw new BrokerError(`Enrollment status error (${resp.status}).`);
    }
    if (resp.status >= 400) throw new BrokerError(String(data['detail'] ?? 'Enrollment status failed.'));
    return enrollmentFromJson(data);
  }

  async revoke(stakeId: string): Promise<void> {
    await this.authed('POST', '/auth/revoke', { stake_id: stakeId });
  }

  /** Provider triggers a sync for their own stake. Returns {coverage_complete, last_synced_at}. */
  syncNow(): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/sync-now');
  }

  getSchedule(): Promise<Record<string, unknown>> {
    return this.authed('GET', '/auth/schedule');
  }

  setSchedule(hourEt: number, paused: boolean): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/schedule', { hour_et: hourEt, paused });
  }

  googleDriveStatus(): Promise<Record<string, unknown>> {
    return this.authed('GET', '/auth/google/status');
  }

  googleDriveStart(): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/google/start');
  }

  googleDriveDisconnect(): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/google/disconnect');
  }

  /** Support form (#74): email the owner a message from the signed-in user. */
  async contact(subject: string, message: string): Promise<void> {
    await this.authed('POST', '/contact', { subject, message });
  }

  /** Ad-hoc leader report (#73): structured convert-integration status for the caller's scope. */
  report(): Promise<Record<string, unknown>> {
    return this.authed('GET', '/report');
  }

  emailReport(toEmail?: string): Promise<Record<string, unknown>> {
    return this.authed('POST', '/report/email', toEmail ? { to_email: toEmail } : {});
  }

  /** Shared authed request carrying the signed-in user's Supabase token. */
  private async authed(method: 'GET' | 'POST', path: string, body?: unknown): Promise<Record<string, unknown>> {
    if (!this.available) throw new BrokerError('Broker not configured.');
    const token = await currentAccessToken();
    if (!token) throw new BrokerError('Not signed in.');
    const headers: Record<string, string> = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
    const resp = await fetchWithTimeout(
      `${brokerUrl}${path}`,
      method === 'GET' ? { method, headers } : { method, headers, body: JSON.stringify(body ?? {}) },
      30_000,
    );
    let data: Record<string, unknown> = {};
    const text = await resp.text();
    if (text.length > 0) {
      try {
        data = JSON.parse(text) as Record<string, unknown>;
      } catch {
        if (resp.status >= 400) throw new BrokerError(`Request failed (${resp.status}).`);
      }
    }
    if (resp.status >= 400) throw new BrokerError(String(data['detail'] ?? `Request failed (${resp.status}).`));
    return data;
  }
}

/** Shared singleton — mirrors how the Flutter app instantiates BrokerClient ad-hoc but stateless. */
export const broker = new BrokerClient();
