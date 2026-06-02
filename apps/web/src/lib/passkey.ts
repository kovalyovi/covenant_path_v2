// Passwordless passkey (WebAuthn) login + registration, against the broker's /webauthn/* routes.
// Login is unauthenticated (it's how you sign in); registration requires the current Supabase
// session. Ported from apps/viewer/lib/passkey_client.dart — same endpoints (/webauthn/login/*,
// /webauthn/register/*). The base64url↔ArrayBuffer ceremony lives in public/passkey.js (window.cpPasskey).

import { brokerUrl } from './config';
import { BrokerError, type BrokerResult } from './broker';
import { currentAccessToken } from './supabase';

function bridge() {
  return typeof window !== 'undefined' ? window.cpPasskey : undefined;
}

export class PasskeyClient {
  get available(): boolean {
    const b = bridge();
    try {
      return brokerUrl.length > 0 && b != null && b.supported();
    } catch {
      return false;
    }
  }

  private async post(path: string, body: unknown, authed = false): Promise<Record<string, unknown>> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (authed) {
      const token = await currentAccessToken();
      if (!token) throw new BrokerError('Not signed in.');
      headers['Authorization'] = `Bearer ${token}`;
    }
    const resp = await fetch(`${brokerUrl}${path}`, { method: 'POST', headers, body: JSON.stringify(body) });
    let data: Record<string, unknown> = {};
    const text = await resp.text();
    if (text.length > 0) {
      try {
        data = JSON.parse(text) as Record<string, unknown>;
      } catch {
        if (resp.status >= 400) throw new BrokerError(`Passkey error (${resp.status}).`);
      }
    }
    if (resp.status >= 400) throw new BrokerError(String(data['detail'] ?? 'Passkey request failed.'));
    return data;
  }

  /** Passwordless login: returns a verifiable Supabase session ({email, otp}) to verifyOtp. */
  async login(): Promise<BrokerResult> {
    const b = bridge();
    if (!b) throw new BrokerError('Passkeys are not available in this browser.');
    const begin = await this.post('/webauthn/login/begin', {});
    const credJson = await b.get(JSON.stringify(begin['options']));
    const done = await this.post('/webauthn/login/complete', {
      handle: begin['handle'],
      credential: JSON.parse(credJson),
    });
    const session = (done['session'] as Record<string, unknown>) ?? {};
    return {
      email: (session['email'] as string) ?? undefined,
      otp: (session['otp'] as string) ?? undefined,
      factors: [],
    };
  }

  /** Register a passkey for the signed-in user (requires a current session). */
  async register(): Promise<void> {
    const b = bridge();
    if (!b) throw new BrokerError('Passkeys are not available in this browser.');
    const begin = await this.post('/webauthn/register/begin', {}, true);
    const credJson = await b.create(JSON.stringify(begin['options']));
    await this.post('/webauthn/register/complete', {
      handle: begin['handle'],
      credential: JSON.parse(credJson),
    }, true);
  }
}

export const passkey = new PasskeyClient();
