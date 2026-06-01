# Onboarding a stake & granting access

## 1. Onboard a stake (Connect LCR)

A stake leader connects their stake once. Their LCR password only ever touches Okta's
login page; we capture the resulting session, store it encrypted per-stake, and the daily
job syncs the stake unattended thereafter.

```bash
python scripts/onboard.py --self       # this account's stake (headless)
python scripts/onboard.py --capture    # opens a browser for a stake leader to sign in
```

This: verifies the leader's calling, registers the stake + its units in Supabase, stores
the encrypted credential (`stake_credentials`), and **auto-provisions stake-leader roles
from callings**. The daily multi-stake job (`scripts/daily_sync.py`, auto/delegated mode)
then includes the stake.

**In-app onboarding is the primary path now:** when a leader signs in with their **Church account**
in the app, the auth broker enrolls the stake automatically (the consent note is inline on the
login screen; revoke lives in Settings → Sync settings). Enrollment also binds the leader's verified
email to a stake-wide `stake_leader` role (migration 0029) so they see their stake immediately. The
CLI above remains for headless/self onboarding and ops.

## 2. Who can see what (access model)

- Roles are **auto-derived from LCR callings** on every sync — no manual assignment.
  Stake-level callings → see the whole stake; ward-level callings (bishop, counselors, clerks,
  exec secs, ward mission leaders) → see only their unit (`backend/roles.py`).
- Access is enforced by Postgres **RLS**, matched to the signed-in **email** (or bound LCR
  identity). Sign in with the email your stake has on file. The leader who **enrolls** a stake is
  also bound to a stake-wide role on enrollment (migration 0029) so they see their stake right away.

## 3. Power users (share access with anyone)

Any leader can grant their access to another **email** — including emails with **no Church
account** (e.g. missionaries) — from the viewer's **"Invite a power user"** screen:

- **Everything I can see** → clones the inviter's full scope.
- **`<Ward>` only** → grants ward-only access (a stake leader onboarding a bishop, or giving
  a ward's missionaries ward-scoped access). This is the manual path for ward-level access.

Invitees sign in with that email (one-time code, no Church account needed), see exactly that
scope, and can invite others. You can only grant within a scope you hold (**no escalation**).
Revoke anytime from the same screen. Audited in the `invitations` table.

Backed by `invite_power_user(email[, unit])` / `revoke_power_user(email)` (see
`backend/migrations/0005_*`, `0007_*`; tests in `backend/test_power_users.py`).

## 4. Emails

Invitations + daily digests send via **Resend**. For delivery to real recipients you must
verify a sending domain in Resend and set `RESEND_FROM` (and, for login emails, point
Supabase Auth SMTP at Resend). Per-stake keys isolate quota — see `docs/CUSTOM_API_KEYS.md`.
