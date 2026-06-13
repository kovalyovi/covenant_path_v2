# Data-gap findings: missing member birthdays (e.g. "Falls Lake" ward)

**Date:** 2026-06-12  **Status:** root cause found; additive rescue shipped; one live confirmation pending.

## Symptom

For some units (reported: "Falls Lake"), member **birthdays are blank** in the app, and with them
every **age-gated milestone / eligibility** silently breaks (calling, Aaronic/Melchizedek priesthood,
temple recommend, patriarchal blessing, family-name, first-temple-visit — all gate on the by-year age
from `birth_date`). Other deep-profile fields can be blank for the same reason.

## How birth date is supposed to flow

```
Member Tools /api/v5/sync  ──►  covenant_path/membertools_adapter.adapt_sync   (PRIMARY, steady state)
   (45-day token, no LCR session)        └─ historically: birth_date = None      ← the gap
                                          └─ now also: birth_date from payload    ← the rescue

LCR per-member profile  ──►  covenant_path/report._apply_profile  (the "/mlt merge")
   (needs a LIVE LCR session)             └─ member.birth_date = prof["birth_date"]  (record.birth.dateDisplay)
```

- The daily sync's covenant-path CORE comes from the **Member Tools bulk API** (`build_membertools_report`).
  The adapter (`membertools_adapter.adapt_person`) historically set **`birth_date=None`** and left it
  "for the /mlt merge".
- The **/mlt merge** (`report._apply_profile`) is the ONLY thing that filled `birth_date`, and it
  requires a **live LCR session** (`profile_fields(client.session, uuid)` → `member_profile`).

## Root cause

The daily sync runs with **`auto_login=False`** and is deliberately **resilient to a dead LCR session**
(`scripts/daily_sync.py`): the LCR appSession dies within days, while the Member Tools 45-day refresh
token outlives it. When a stake's LCR session is dead but its Member Tools token is alive:

- The covenant-path core still syncs from Member Tools (so the unit looks "synced / fresh").
- But **every per-member profile fetch fails** (`profile merge failed …` → summarized as
  `profile extras: 0/N members enriched`), so **`birth_date` stays `None`** for the whole unit —
  along with the other profile-only fields (patriarchal_blessing, temple_recommend, priesthood office,
  ministering_assignment, endowment date).

This is **not** a per-unit data bug, not a missing column, and not a web display bug — the web reads
`birth_date` straight from Supabase (`apps/web/src/lib/member.ts`). It is a **sync-source gap**: the
ONLY birth-date source was the LCR profile fetch, which is exactly what dies in steady state.

A unit shows the gap specifically when its LCR session is dead (no recent re-auth) while the Member
Tools token is alive — which is the normal state of a stake more than a few days past its last
re-authorization. "Falls Lake" matches that profile.

## Fix shipped (additive, no regression)

`covenant_path/membertools_adapter.py` now also reads **`birth_date` from the bulk payload** when it
is present:

- `_birth_date(person)` — tolerant extraction (flat `birthDate`/`birthdate`/`dateOfBirth`, or a nested
  LCR-style `birth.{dateDisplay|date|display}` object), mirroring the existing tolerant `_readable_name`.
- `_birth_index(payload)` — resolves a covenant person's birth date from the **household roster** when
  their own covenant record omits it (the same fallback the friend-name index uses).
- If the payload carries **no** birth field, `birth_date` stays `None` and the /mlt merge fills it
  exactly as before — so this can only ever help, never regress. (`report._apply_profile` already only
  fills birth date `if not member.birth_date`, so a payload birth date is preserved.)

This means a stake with a **dead LCR session but a live Member Tools token** now gets birth dates (and
therefore correct age gates) on every daily sync, with no re-authorization required — *provided the
bulk payload actually carries the field*.

## The one thing to confirm live

I could not verify the exact birth-date key in the real `/api/v5/sync` payload (it needs live Church
credentials + MFA, unavailable here). `tools/membertools_probe.py` now checks for it: run

```
python tools/membertools_probe.py
```

and read the `birth_date` line under "ADAPTER on real payload" and the OUR-FIELD coverage line.

- **`birth_date : N/N`** → the rescue works; no further action. Birthdays will populate on the next
  daily sync for every stake (no re-auth needed).
- **`birth_date : 0/N`** → the bulk payload does **not** carry birth dates under any of the candidate
  keys. In that case birthdays can only come from the LCR profile fetch, so the recovery is to
  **re-authorize the affected stake** (Settings → Sync settings → Re-authorize) to re-establish a live
  LCR session for the profile merge. If the probe reveals a *different* birth key, add it to
  `_birth_date`'s candidate lists and `tools/membertools_probe.py`'s `OUR_FIELDS["birth_date"]`.

## Immediate recovery for an already-affected unit (regardless of the above)

Re-authorizing the stake re-establishes a live LCR session, so the very next sync runs the /mlt profile
merge and back-fills birth dates (and the other profile fields). The age nudge email + `/reauth` deep
link already drive this at ~day 40.
