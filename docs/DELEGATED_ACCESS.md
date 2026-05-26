# Delegated access & calling-based authorization

How the covenant-path script handles **who is allowed to pull which data**, and how
a higher-access leader can authorize the script on their behalf — securely, without
ever sharing a password.

> TL;DR: anyone with the right LCR access + calling can run the script and pull what
> their calling allows. If they're missing access, the script pulls what it can,
> clearly marks the rest as *blocked*, and tells you which callings unlock it. A
> higher-access leader can authorize long-term access via a **hosted login link**
> (password only ever touches Okta); the grant is encrypted, expiring, revocable, and
> re-verified against their calling on every run.

---

## 1. Access is calling-based

LCR scopes data by calling. The authoritative map lives at
`/other/access-table` (embedded in the page; parsed by `lcr_client/access.py`):
**8 sections → features → `roles:[positionTypeId]`**, plus `rolesData` (id → calling
name). The feature role IDs use the **same id-space** as `positionType.id` in
`/api/user-context`, so we intersect the runner's callings with each feature's roles.

`python -m lcr_client.access` prints, for the current user:
- their calling(s) and role id(s),
- which covenant-path features they can/can't reach,
- which callings grant anything missing ("who to ask").

**Important caveat:** the access table is *UI-menu* visibility and is **not 1:1 with
API access**. So the report (below) treats it as advisory — it always *attempts* the
pull and only marks a field blocked if the API actually denies it. The real API
ground truth is `tools/health_check.py`.

### Runner findings (Raleigh NC Stake)
- **Stake Assistant Clerk (id 53)** — the current user — can reach all covenant-path
  data (progress record, member list, member profiles, temple recommend, patriarchal
  blessing status, ward leadership). Only the *Confidential Member Information Report*
  is gated higher (Stake Clerk/President/Bishop/Ward Clerk), and the pipeline doesn't
  use it (patriarchal blessing comes from the member-profile flag).
- Leadership features are **perspective-inverted**: `menu.ward.leadership` is granted
  to *stake* roles (a stake leader's view of wards); `menu.stake.leadership` to *ward*
  roles. Don't read the names literally.

---

## 2. Graceful degradation in the report

`python -m covenant_path.report --with-profile` now:
1. runs the access pre-flight and prints the runner's calling + what's grant­ed;
2. pulls everything it can; if a profile-gated field can't be fetched, it sets the
   value to `blocked: insufficient calling access` (never a silent blank);
3. if the calling lacks "Member Profiles" **and** profile fetches keep failing, it
   stops hammering the endpoint and marks the rest blocked;
4. writes `output/covenant_path_access.json` — runner positions, per-feature access,
   **who to ask** for each missing feature, run stats, and **field coverage**
   (filled / blocked / pending per field) for troubleshooting discrepancies.

---

## 3. Delegated authorization (no password sharing)

When a lower-access person needs data only a higher-access leader (e.g. Stake
President / Stake Clerk) can pull, that leader authorizes the script:

```
python -m lcr_client.delegated_login authorize        # opens a browser
```

Flow (`lcr_client/delegated_login.py`):
1. A **real browser** opens to LCR's official login. The leader signs in on **Okta's
   own hosted page** — their password is entered only there and is **never seen or
   stored** by this script.
2. Once authenticated, we capture the session cookies (including the longer-lived
   Okta session cookie `idx`), confirm the leader's calling via the access matrix,
   record **explicit consent** and an **expiry** (default 30 days), and persist it
   **encrypted, scoped to the stake** (`lcr_client/token_store.py`, Fernet).

The capture must run on a device the leader uses (that's where their browser/password
live). A fully remote hosted page would require registering our own redirect URL on
the Church's OAuth client — only the Church can do that — so this is the secure,
equivalent-UX alternative.

### Running long-term under a grant
```
python -m lcr_client.delegated_login mint --stake 503991   # re-mint a session
python -m lcr_client.delegated_login status                # list grants (redacted)
python -m lcr_client.delegated_login revoke --stake 503991 # kill switch
```
`mint` loads the stored session, SSOs through `/api/auth/login` to mint **fresh LCR
cookies** (works while the Okta session is alive), then **re-verifies** the principal
still holds the granting calling. If the calling changed (released), the grant is
**auto-revoked**. Expiry and revocation are enforced. The minted session is written to
`storage_state.json`, so the whole pipeline then runs as the authorizing leader.

When a grant expires, the Okta session dies, or the calling changes, the leader simply
re-authorizes via the link.

---

## 4. Security model & recommendations

| Concern | How it's handled |
|---|---|
| No password sharing | Password only touches Okta's hosted page; we capture the resulting session, never credentials. |
| Secrets at rest | Session cookies stored **encrypted** (Fernet/AES). Redacted in all listings/logs. Store + key under gitignored `tools/output/`. |
| Encryption key | `CP_TOKEN_KEY` env (preferred, for prod/CI) or an auto-generated `.token_key` file (dev). Rotating the key invalidates grants. **Don't keep the key file on the same host in production** — use a secret manager. |
| Consent | Explicit `I AGREE` prompt recording who, what stake, scope, and expiry. |
| Expiry | Hard `max_lifetime_days` (default 30); past expiry → re-authorize. |
| Calling change | Re-verified on **every** mint; lost access → grant **auto-revoked**. |
| Revocation | `revoke` kill-switch; revoked grants refuse to mint (kept for audit). |
| Auditability | Append-only audit log per grant (granted / minted / reverify / expired / revoked). |
| PII handling | Output is sensitive membership data — keep `output/` private, lock the destination (Supabase RLS / scoped Sheet), set retention. |
| Governance | Aggregating confidential membership info should align with Church data-handling policy and have local leadership's awareness. |

LCR also has a **native proxy** model (`user.loggedInUser.canProxy/proxyRights`); if a
leader can proxy to your account in LCR, that keeps delegation inside the system that
owns the data and is preferable where available.

---

## 5. Testing & troubleshooting

`python tools/test_suite.py` (offline) / `--live` (needs a session). Covers the token
store crypto round-trip + redaction + key rotation, report degradation logic, access
parsing, okta building blocks, and a full delegated mint→verify→revoke round-trip
(using the current session as a simulated grant, against temp files). Persists
`tools/output/test_report.json`.

Troubleshooting artifacts (all under `tools/output/`):
- `covenant_path_access.json` — access + field coverage + who-to-ask for a report run.
- `test_report.json` — per-test pass/fail with messages.
- `logs/` — per-session logs; `debug/` — failure dumps (e.g. `report_profile_fail`).
- `health_report.json` — endpoint ground-truth (`tools/health_check.py`).
- grant audit log — `delegated_login status`.
