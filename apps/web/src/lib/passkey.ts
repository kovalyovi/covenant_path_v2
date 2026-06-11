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

  /** The browser ceremony throws DOMExceptions whose texts are written for developers
   *  ("The operation either timed out or was not allowed…") — map them to what the member can
   *  act on. A cancelled/no-passkey prompt previously surfaced raw (or, worse, silently). */
  private static friendlyCeremonyError(e: unknown, verb: string): BrokerError {
    const name = (e as { name?: string })?.name ?? '';
    if (name === 'NotAllowedError' || name === 'AbortError') {
      return new BrokerError(
        `Passkey ${verb} was cancelled or no passkey is set up on this device. ` +
          'You can sign in another way, or add a passkey later from Settings.',
      );
    }
    if (name === 'InvalidStateError') {
      return new BrokerError('A passkey for this account already exists on this device.');
    }
    return new BrokerError(`Passkey ${verb} failed: ${e instanceof Error ? e.message : String(e)}`);
  }

  /** Passwordless login: returns a verifiable Supabase session ({email, otp}) to verifyOtp. */
  async login(): Promise<BrokerResult> {
    const b = bridge();
    if (!b) throw new BrokerError('Passkeys are not available in this browser.');
    const begin = await this.post('/webauthn/login/begin', {});
    let credJson: string;
    try {
      credJson = await b.get(JSON.stringify(begin['options']));
    } catch (e) {
      throw PasskeyClient.friendlyCeremonyError(e, 'sign-in');
    }
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
    let credJson: string;
    try {
      credJson = await b.create(JSON.stringify(begin['options']));
    } catch (e) {
      throw PasskeyClient.friendlyCeremonyError(e, 'setup');
    }
    await this.post('/webauthn/register/complete', {
      handle: begin['handle'],
      credential: JSON.parse(credJson),
    }, true);
  }
}

export const passkey = new PasskeyClient();
