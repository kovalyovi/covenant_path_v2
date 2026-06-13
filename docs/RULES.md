# Rules & definitions (who-can-see-what, eligibility, ownership)

The relationship rules that drive the app — **priesthood/ordinance eligibility** (by age, sex,
tenure), **who can see covenant-path data** (calling → access), and **who owns a convert's care**
(by tenure) — in one place. Each rule has a single source of truth in code (linked below); this
doc explains them and is surfaced in-app under **Settings → Rules & definitions** (and via ⓘ icons).

> One-source-of-truth note: change a rule in the file named, and every view follows. The React web
> app (`apps/web`) and the two native ports (`native/ios`, `native/android`) mirror these — see
> `.llm/CROSS_SURFACE_UI.md`.

---

## 1. Priesthood & ordinance eligibility (age · sex · tenure)

A milestone is only counted for the people it can actually apply to, so completion stats never
penalize someone who isn't eligible. **Eligibility ≠ completion** — eligibility decides whether the
row is even asked; completion is whether they've done it.

Source: `apps/web/src/logic/milestones.ts` (`milestones`, eligibility predicates) and the backend
mirror `backend/milestones.py` (`turns_at_least` / `is_at_least_now` / `member_one_year`), applied
in `covenant_path/report.py` (`_apply_profile`). Native mirrors:
`native/ios/Sources/CovenantPathKit/Logic/Milestones.swift` + `native/android/.../logic/Milestones.kt`.

| Milestone / field | Who is eligible | Rule |
|---|---|---|
| **Friends in the Church** | Everyone | — |
| **Has ministers** (ministers assigned) | Everyone | — |
| **Calling** | Turns **≥ 12** this year | by-year age |
| **Gives ministering** (ministering assignment) | Turns **≥ 14** this year | by-year age |
| **Aaronic Priesthood** | **Male** AND turns **≥ 12** this year | sex + by-year age |
| **Melchizedek Priesthood** | **Male** AND **≥ 18 now** AND **member ≥ 1 year** | sex + actual age + tenure |

Definitions:
- **"Turns N this year" (by-year)** — `currentYear − birthYear ≥ N`. Matches the Church's by-year
  quorum/advancement rule (an 11-year-old who turns 12 this calendar year counts). Unknown birth
  date → **not** eligible for age-gated milestones (we don't ding someone we can't assess).
- **"≥ N now" (actual age)** — uses the full birth date when present (else by-year).
- **"member ≥ 1 year" (tenure)** — baptized ≥ 365 days ago, OR `membership_duration` says "N years"
  with N ≥ 1.
- **Sex** — `M` / `F` from the LCR member record (authoritative); the one-work progress record has
  no sex, which is why it's pulled from the profile/member list.

Priesthood **office → (Aaronic, Melchizedek)** mapping (the authoritative source is the member
profile's current office; `covenant_path/report.py`):
- **Melchizedek offices** — Elder, High Priest, Bishop, Seventy, Patriarch, Apostle → Aaronic **Yes**, Melchizedek **Yes**.
- **Aaronic offices** — Deacon, Teacher, Priest → Aaronic **Yes**, Melchizedek **No**.
- The *displayed* value is gated to the eligible (table above); ineligible rows show **N/A**, not a
  misleading "No".

---

## 2. Who can see covenant-path data (calling → access)

Access is **rebuilt from LCR callings every sync** — no manual role assignment. Source:
`backend/roles.py` (`provision_roles`) + the RLS policies in `backend/migrations/*.sql`. The client
does **no** access filtering; the database returns only the rows a login may see (`CLAUDE.md` rule 3).

**A calling grants covenant-path data access when** its LCR role is granted **any** of these menu
features (union — not just member-profiles):
- `menu.progress.record` — the new-member / covenant-path list per unit (the core data),
- `menu.member.list` — the roster + birth dates,
- `menu.view.member.profiles` — the detailed member profile.

**Always-allowed safety net** (stake stewardship callings get access even if the LCR menu matrix is
incomplete): Stake President, Stake Presidency & Counselors, Stake Clerk / Assistant Clerk, Stake
Executive Secretary / Assistant, High Council.

**Scope** (what they see):
| Calling scope | Role | Sees |
|---|---|---|
| Stake / District / Mission / Area calling | `stake_leader` | the **whole stake** |
| Ward / branch calling | `ward_leader` | **their unit only** |

- **Re-evaluated every run:** a released leader's row is revoked; a calling that loses feature
  access loses data access. (Guarded so an empty/failed fetch never mass-revokes.)
- **Power users:** `invite_power_user(email)` clones the caller's *exact* roles to any email
  (escalation-safe — you can only clone what you already hold); recursive; audited; revocable.
- **Login gate (N2):** signing in with a Church account whose calling grants **no** data access and
  who holds **no** role/power-user grant is told at login they don't have access and is not signed
  in. Sync enrollment uses **most-elevated-wins-if-incomplete** — your Church session gathers your
  stake's data only when the stake has no equal-or-better connection yet.

---

## 3. Who owns a convert's care (by tenure)

The stake's hand-off policy for a new member's integration. Single source:
`apps/web/src/logic/milestones.ts` (`responsibleOrg` / `orgInfo` / `OrgBucket`). Native mirrors:
`native/ios/Sources/CovenantPathKit/Logic/OrgBucket.swift` + `native/android/.../logic/OrgBucket.kt`.

| Time since baptism | Responsible org | Who |
|---|---|---|
| **< 12 months** | **Missionaries / WML** | full-time missionaries + the **ward mission leader** watch over each new member's progress |
| **≥ 12 months** (men) | **Elders Quorum** | the EQ presidency watches over each brother's continued integration |
| **≥ 12 months** (women) | **Relief Society** | the RS presidency watches over each sister's continued integration |
| no baptism date | **Unassigned** | can't reckon tenure |

---

## 4. Cohorts (who shows where)

- **New member / convert** — baptized (`kind = new_member`); has a baptism date. Appears in the
  master lists, Golden Hour, Needs, Table, and the Baptisms-by-month stat.
- **Investigator / being taught** — not yet baptized (`kind = investigator`); has a *planned*
  baptism date. Appears **only** in **Baptisms** (planned timeline) and Golden Hour's **Being
  Taught** section — filtered out of the master lists (Table/Needs). (N7.)
- **"Baptised and confirmed"** counts = the convert cohort counted by **baptism month**
  (confirmation follows within days), per the agreed approach (#1/#2).

---

_When you change any rule above, update the linked source file (and its native mirrors) — this doc
points to where, it does not duplicate the logic._
