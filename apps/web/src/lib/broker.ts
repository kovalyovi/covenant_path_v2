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
  /** Whether the broker STORED this session as the stake credential (only when the leader authorized). */
  stored?: boolean;
  /** Higher-access transfer offer: the stake already has an insufficient credential this session improves. */
  canImprove?: boolean;
  /** #8: the stake has NO usable credential yet and this authorized leader could set one up — drives
   *  the POST-login "Authorize daily sync?" offer (consent moved off the login form). */
  canEnroll?: boolean;
  stake?: string | null;
  missing?: string[];
  /** When the server-side login eval failed (e.g. LCR outage), its error — so a consented enroll
   *  can say WHY nothing was stored instead of pretending it succeeded. */
  enrollError?: string;
  /** This session is a WARD/BRANCH-level leader's — enrollment is refused (a ward leader sees their
   *  unit via their role; daily sync is set up per stake). Carries a friendly reason. (Green Level
   *  Ward incident, 2026-06-13.) */
  wardScoped?: boolean;
  enrollBlockReason?: string;
  /** The stake already has a credential and THIS session is strictly weaker — re-authorizing with it
   *  would reduce coverage, so the UI warns first (R4). existingProvider names who currently provides it. */
  wouldDowngrade?: boolean;
  existingProvider?: string | null;
  existingComplete?: boolean;
}

export function mfaRequired(r: BrokerResult): boolean {
  return r.loginId != null && r.otp == null;
}

export interface CredentialInfo {
  state: 'none' | 'active' | 'stale' | 'revoked' | string;
  complete: boolean;
  principalName?: string | null;
  isProvider: boolean;
  enrolledAt?: string | null;
  /** When state === 'stale', the last sync error (e.g. "SSO did not complete…"). */
  lastError?: string | null;
  /** This calling can read the member-profile patriarchal flag — gates the "refresh patriarchal" banner. */
  canRefreshPatriarchal?: boolean;
}

export interface EnrollmentStatus {
  stakeName?: string | null;
  stakeId?: string | null;
  /** LCR stake unit number — the stable ID shown to users (stakes get renamed). */
  unitNumber?: number | null;
  lastSyncedAt?: string | null;
  memberCount: number;
  hasData: boolean;
  /** Real (baptized, in-directory) members still missing the patriarchal blessing flag — the one field
   *  absent from the daily Member Tools sync. >0 ⇒ a re-authorize-to-refresh nudge is worthwhile. */
  patriarchalPending: number;
  noRole: boolean;
  /** This viewer holds a STAKE-level role here — so they may take over the sync with their own
   *  (equal-or-higher) Church account even when another leader currently provides it. Ward leaders
   *  and no-role members can't enroll, so they're never offered take-over. */
  viewerIsStakeLeader: boolean;
  credential: CredentialInfo;
}

/** "Name · ID 503991" — ID is the stable LCR unit number, preferred since stakes get renamed (#9). */
export function stakeLabel(s: EnrollmentStatus): string {
  const parts: string[] = [];
  if (s.stakeName) parts.push(s.stakeName);
  if (s.unitNumber != null) parts.push(`ID ${s.unitNumber}`);
  return parts.length === 0 ? '—' : parts.join('  ·  ');
}

function credFromJson(j: Record<string, unknown>): CredentialInfo {
  return {
    state: (j['state'] as string) ?? 'none',
    complete: j['complete'] === true,
    principalName: (j['principal_name'] as string) ?? null,
    isProvider: j['is_provider'] === true,
    enrolledAt: (j['enrolled_at'] as string) ?? null,
    lastError: (j['last_error'] as string) ?? null,
    canRefreshPatriarchal: j['can_refresh_patriarchal'] === true,
  };
}

function enrollmentFromJson(j: Record<string, unknown>): EnrollmentStatus {
  return {
    stakeName: (j['stake_name'] as string) ?? null,
    stakeId: (j['stake_id'] as string) ?? null,
    unitNumber: (j['unit_number'] as number) ?? null,
    lastSyncedAt: (j['last_synced_at'] as string) ?? null,
    memberCount: Number(j['member_count'] ?? 0) || 0,
    hasData: j['has_data'] === true,
    patriarchalPending: Number(j['patriarchal_pending'] ?? 0) || 0,
    noRole: j['status'] === 'no_role',
    viewerIsStakeLeader: j['viewer_is_stake_leader'] === true,
    credential: credFromJson((j['credential'] as Record<string, unknown>) ?? {}),
  };
}

// Free hosting sleeps when idle; the first request after a sleep can fail (no CORS header on the
// holding page → "Failed to fetch"). Retry across ~63s so a cold start resolves itself.
const RETRY_DELAYS_MS = [3000, 6000, 9000, 12000, 15000, 18000];

// A successful broker response within this window proves it's awake — skip the pre-POST /health
// round-trip. Render's idle sleep is ~15 min, so 2 minutes can never mask a real cold start.
const WARM_FRESH_MS = 120_000;

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

  /** Dedupes a warm-up that's already in flight so an early warmUp() and the submit-time
   *  ensureWarm() share ONE wake, instead of racing two cold-start pings. */
  private warmPromise: Promise<void> | null = null;

  /** Last time any broker call returned an HTTP response (= the container is awake). */
  private lastWarmOkAt = 0;

  /**
   * N5: wake the free-tier broker early — fire a cheap /health ping when the login screen appears,
   * so it spins up while the user types, hiding the ~30-60s cold start. Fire-and-forget.
   */
  warmUp(): void {
    if (!this.available) return;
    void this.ensureWarm();
  }

  /**
   * Ensure the broker is actually AWAKE before an expensive login call. The fire-and-forget warmUp()
   * isn't enough on its own: when the user autofills + submits within a second (or a deploy restarts
   * the container mid-login), the heavy /auth/password call lands on a cold container and absorbs the
   * whole ~30-60s wake — the "took forever / timed out" report. Awaiting a /health (with the same
   * cold-start retry) here guarantees the Okta round-trip always hits a warm broker, converting an
   * unpredictable 50-110s hang into a visible, bounded "waking up…" then a fast sign-in.
   * Resolves immediately when already warm (~0.3s health round-trip); concurrent callers share one.
   */
  async ensureWarm(): Promise<void> {
    if (!this.available) return;
    // Proven awake moments ago (e.g. the mount-time warmUp() or a prior call) — skip the ping.
    if (Date.now() - this.lastWarmOkAt < WARM_FRESH_MS) return;
    if (this.warmPromise) return this.warmPromise;
    this.warmPromise = (async () => {
      for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
        try {
          const r = await fetchWithTimeout(`${brokerUrl}/health`, { method: 'GET' }, 30_000);
          if (r.ok) {
            this.lastWarmOkAt = Date.now();
            return; // awake
          }
        } catch {
          /* still cold — retry below */
        }
        if (attempt < RETRY_DELAYS_MS.length) {
          this.onStatus?.('Waking up the sign-in service… this can take up to a minute on first use.');
          await delay(RETRY_DELAYS_MS[attempt]);
        }
      }
    })();
    try {
      await this.warmPromise;
    } finally {
      this.warmPromise = null; // clear so a later sign-in re-checks (the broker can sleep again)
    }
  }

  private async postJson(path: string, body: unknown): Promise<Record<string, unknown>> {
    if (!this.available) throw new BrokerError('Church login is not configured (BROKER_URL).');
    // Wake the broker FIRST so the expensive Okta call never eats the cold start (see ensureWarm).
    await this.ensureWarm();
    const _t0 = typeof performance !== 'undefined' ? performance.now() : Date.now();
    // Login-completing calls run the broker's access evaluation server-side, which on a FIRST enroll
    // (no usable credential yet) legitimately takes 30-60s — a 30s abort made the client give up
    // while the broker succeeded, so the enroll offer never appeared and the retry re-ran the whole
    // Okta login (the father's three 'allowed', zero 'enrolled' loop). Give those calls 95s.
    const attemptTimeout = /\/auth\/(password|mfa\/verify|session|otp\/verify)$/.test(path) ? 95_000 : 30_000;
    let _retries = 0;
    let resp: Response | null = null;
    let lastErr: unknown;
    for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
      try {
        resp = await fetchWithTimeout(
          `${brokerUrl}${path}`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
          attemptTimeout,
        );
        break; // got an HTTP response (success or error) — stop retrying
      } catch (e) {
        lastErr = e;
        _retries = attempt + 1;
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
    this.lastWarmOkAt = Date.now(); // any HTTP response (even an error) proves it's awake
    if (resp.status >= 400) {
      throw new BrokerError(String(data['detail'] ?? `Sign-in failed (${resp.status}).`));
    }
    const timing = data['timing'] as Record<string, unknown> | undefined;
    const serverMs = typeof timing?.['total_ms'] === 'number' ? (timing['total_ms'] as number) : undefined;
    this.logTiming(path, _t0, _retries, serverMs);
    return data;
  }

  /** #6 login profiling: time the login round-trip (incl. cold-start retries) → console + the broker
   *  /log endpoint (→ Axiom), so the client-EXPERIENCED latency is easy to harvest and compare with
   *  the broker's server-side `login.complete`. Fire-and-forget; never blocks login. */
  private logTiming(path: string, t0: number, retries: number, serverMs?: number): void {
    if (!/\/auth\/(password|mfa\/verify|email\/verify|otp\/verify)/.test(path)) return;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const ms = Math.round(now - t0);
    console.info(`[login-timing] ${path} ${ms}ms (cold-start retries: ${retries}, server: ${serverMs ?? '?'}ms)`);
    const context: Record<string, string | number | boolean> = { path, ms, retries };
    if (serverMs != null) context.serverMs = serverMs; // ms - serverMs = network/TLS overhead
    this.logEvent('client.login.timing', context);
  }

  /** Fire-and-forget client telemetry → broker /log → Axiom. Never blocks, never throws. */
  logEvent(event: string, context: Record<string, string | number | boolean>): void {
    if (!this.available) return;
    try {
      void fetch(`${brokerUrl}/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: 'info', event, surface: 'web', context }),
      }).catch(() => {});
    } catch {
      /* ignore */
    }
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
      stored: enroll?.['stored'] === true,
      canImprove: enroll?.['can_improve'] === true,
      canEnroll: enroll?.['can_enroll'] === true,
      stake: (enroll?.['stake'] as string) ?? null,
      missing: ((enroll?.['missing'] as unknown[]) ?? []).map((m) => String(m)),
      enrollError: typeof enroll?.['error'] === 'string' ? (enroll['error'] as string) : undefined,
      wardScoped: enroll?.['ward_scoped'] === true,
      enrollBlockReason:
        typeof enroll?.['enroll_block_reason'] === 'string'
          ? (enroll['enroll_block_reason'] as string)
          : undefined,
      wouldDowngrade: enroll?.['would_downgrade'] === true,
      existingProvider: (enroll?.['existing_provider'] as string) ?? null,
      existingComplete: enroll?.['existing_complete'] === true,
    };
  }

  password(username: string, password: string, enroll = false): Promise<BrokerResult> {
    return this.post('/auth/password', { username, password, enroll });
  }

  // Credential-capture (one-MFA) lane — drives authn → LCR authorize → MFA so a SINGLE MFA yields
  // the LCR session AND the 45-day Member Tools sync token (minted server-side, persisted at enroll).
  // Used by the web ENROLL/re-auth so a stake's unattended 45-day sync needs no stored password/TOTP.
  webStart(username: string, password: string, enroll = true): Promise<BrokerResult> {
    return this.post('/auth/web/start', { username, password, enroll });
  }

  webSelectFactor(loginId: string, factorId: string): Promise<BrokerResult> {
    return this.post('/auth/web/select', { login_id: loginId, factor_id: factorId });
  }

  webVerify(loginId: string, code: string, enroll = true): Promise<BrokerResult> {
    return this.post('/auth/web/verify', { login_id: loginId, code, enroll });
  }

  selectFactor(loginId: string, factorId: string): Promise<BrokerResult> {
    return this.post('/auth/mfa/select', { login_id: loginId, factor_id: factorId });
  }

  verifyMfa(loginId: string, code: string, enroll = false): Promise<BrokerResult> {
    return this.post('/auth/mfa/verify', { login_id: loginId, code, enroll });
  }

  // NOTE: the passwordless Church-login lane (Okta emailed code, /auth/otp/*) was REMOVED 2026-06-12 —
  // its app-scoped Okta session could never mint the 45-day daily-sync token. Church auth is now
  // username+password only (password()/webStart()). Passwordless VIEWING uses the Supabase relay below.

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

  /** Provider self-service: wipe the stake's MEMBER data (access + the sync credential stay;
   *  data re-populates on the next sync). Server-side provider gate mirrors /auth/revoke. */
  wipeData(stakeId: string): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/wipe-data', { stake_id: stakeId });
  }

  /** Provider triggers a sync for their own stake. Returns {coverage_complete, last_synced_at}. */
  syncNow(): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/sync-now');
  }

  /** Fill-data sheet: start an on-demand profile fill for the caller's stake. Returns
   *  {status: 'started'|'running'|'needs_reauth'|'nothing_to_fill', ...} — needs_reauth routes the
   *  client to the ReauthDialog, whose enroll path runs the same fill off the fresh session. */
  profileRefreshStart(): Promise<Record<string, unknown>> {
    return this.authed('POST', '/auth/profile-refresh');
  }

  /** Fill-data sheet: per-field missing counts + live worker progress for the caller's stake. */
  profileRefreshStatus(): Promise<Record<string, unknown>> {
    return this.authed('GET', '/auth/profile-refresh/status');
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

  /** Passive per-endpoint health TREND across recent sync/probe runs (calls/errors/latency + error
   *  rate by hour-of-day) — the zero-added-load read on whether the current request pace is safe. */
  endpointHealth(days = 14): Promise<Record<string, unknown>> {
    return this.authed('GET', `/admin/endpoint-health?days=${days}`);
  }

  /** Claim flow (0065) step 1: "I'm a leader but signed in with a different email". Matches the name
   *  and mails a single-use link to the address ON RECORD — the reply carries only a masked hint. */
  claimStart(firstName: string, lastName: string): Promise<Record<string, unknown>> {
    return this.authed('POST', '/claim/start', { first_name: firstName, last_name: lastName });
  }

  /** Step 2: consume the emailed link. Must be the same sign-in that started the claim. */
  claimVerify(token: string): Promise<Record<string, unknown>> {
    return this.authed('POST', '/claim/verify', { token });
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
