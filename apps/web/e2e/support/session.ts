// Seed a Supabase session straight into localStorage so dashboard tests start signed-in without
// running the whole login flow. supabase-js derives its storage key from the FIRST host label of
// the Supabase URL: http://supabase.local.test -> `sb-supabase-auth-token`. The access token is a
// structurally valid (but unsigned) JWT — auth-js decodes `exp` from it in some paths, and the
// far-future expiry keeps the auto-refresh timer quiet for the life of a test.

import type { Page } from '@playwright/test';
import { TEST_EMAIL, TEST_USER_ID } from './fixtures';

export const STORAGE_KEY = 'sb-supabase-auth-token';

function b64url(s: string): string {
  return Buffer.from(s, 'utf8').toString('base64url');
}

function fakeJwt(payload: Record<string, unknown>): string {
  const header = { alg: 'HS256', typ: 'JWT' };
  return `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(payload))}.${b64url('e2e-signature')}`;
}

/** The canonical gotrue user object (the shape /auth/v1/verify and /auth/v1/user return). */
export function fakeUser(email: string = TEST_EMAIL): Record<string, unknown> {
  const created = '2026-01-01T00:00:00.000Z';
  return {
    id: TEST_USER_ID,
    aud: 'authenticated',
    role: 'authenticated',
    email,
    email_confirmed_at: created,
    phone: '',
    confirmed_at: created,
    last_sign_in_at: created,
    app_metadata: { provider: 'email', providers: ['email'] },
    user_metadata: { email },
    identities: [],
    created_at: created,
    updated_at: created,
    is_anonymous: false,
  };
}

/** A full gotrue session/token payload (also what /auth/v1/verify responds with). */
export function fakeSession(email: string = TEST_EMAIL): Record<string, unknown> {
  const nowSec = Math.floor(Date.now() / 1000);
  const exp = nowSec + 8 * 3600;
  return {
    access_token: fakeJwt({
      sub: TEST_USER_ID,
      email,
      role: 'authenticated',
      aud: 'authenticated',
      session_id: 'e2e-session',
      exp,
    }),
    token_type: 'bearer',
    expires_in: exp - nowSec,
    expires_at: exp,
    refresh_token: 'e2e-refresh-token',
    user: fakeUser(email),
  };
}

/** Make every page in this test start with a valid signed-in Supabase session. */
export async function seedSession(page: Page, email: string = TEST_EMAIL): Promise<void> {
  const json = JSON.stringify(fakeSession(email));
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key, value);
    },
    [STORAGE_KEY, json] as const,
  );
}
