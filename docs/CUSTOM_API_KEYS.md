# Bring-your-own API keys (per-stake quota isolation)

The platform sends email via **Resend**. The free tier is shared (~100 emails/day,
3,000/month), so as more stakes onboard, a single shared key would hit the cap. To avoid
that, **each stake can supply its own Resend API key** — its emails then draw on *its*
quota, not ours. If a stake has no key set, the shared `RESEND_API_KEY` is used.

## How it works

- `stake_settings.resend_api_key_enc` holds the stake's key, **Fernet-encrypted** (same
  `CP_TOKEN_KEY` as the rest of the backend). The table is RLS-locked with no policies, so
  only the backend (postgres role) can read it — never the client.
- `backend/mailer.stake_key(conn, stake_id)` resolves the key: the stake's own if present,
  else the shared env key. All sends (`send_pending_invitations`, `send_digests`) use it.

## Set a stake's own Resend key

1. The stake admin creates a free Resend account at https://resend.com and an **API key**
   (Dashboard → API Keys → Create). For real-recipient delivery they should also **verify a
   sending domain** (Dashboard → Domains) and set their `email_from` to that domain — the
   shared `onboarding@resend.dev` test sender only delivers to the Resend account owner.
2. Store it (run from the repo, with `CP_TOKEN_KEY` + `SUPABASE_DB_URL` in `.env`):

   ```bash
   python -m backend.set_stake_key --stake <unit_number> \
       --resend-key re_xxx --from "Stake Name <noreply@yourdomain.org>"
   ```

3. Done — that stake's invitations + digests now use its key/quota and `from` address.

## Limits & guidance (free tiers)

| Service | Free tier | Our guardrail |
|---|---|---|
| Resend  | 100 email/day, 3k/mo | per-run cap (`DEFAULT_DAILY_CAP=90`); per-stake keys |
| Supabase | 500MB DB, 50k MAU | small text rows; RLS; pooler |
| GitHub Actions | 2,000 min/mo | ~10 min/day; incremental cache |

If you expect to exceed a tier, set a per-stake key (above) or upgrade that single service.

## Future (same pattern for other providers)

The `stake_settings` table is the place to add other per-stake keys (e.g. a future SMS or
storage provider). Keep the same shape: `*_enc` (Fernet) + a resolver in the relevant module
that prefers the stake key and falls back to the shared env key.
