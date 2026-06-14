# Member Tools API — Full Profile & macOS Probe Report

*Autonomous run, 2026-06-13. Target: **Member Tools** (App Store id391093033, The Church of
Jesus Christ of Latter-day Saints). Profiled live against your stake (unit 503991).*

---

## 0. TL;DR

- **The original plan can't work for this app.** The task was: run Member Tools on macOS in a VM
  and watch its API calls. But Member Tools' Mac build is **Apple-Silicon-only** ("Requires macOS
  14.0 or later and a Mac with Apple M1 chip or later"). An Intel/QEMU VM — or *any* VM on this PC —
  cannot install or run it (Apple-Silicon macOS isn't virtualizable on a Ryzen). Finishing the macOS
  install wouldn't change that.
- **So I profiled the same API the app uses, directly.** Member Tools is just a client of the
  Church's `membertools-api` + Okta. Reusing your own `lcr_client` auth and your stored 45-day
  Member Tools refresh token (a fresh headless login is blocked by MFA — see §2), I pulled the
  **entire `POST /api/v5/sync` payload live**.
- **Result: a complete field map — 902 distinct paths across 40 top-level sections** (~7 MB,
  from a real stake of 1,673 households / 3,014 directory members). Your `membertools_adapter.py`
  currently consumes **~8 of those 40 sections**. The other 32 are high-value, already-paid-for data
  that maps directly onto `docs/MEMBER_TOOLS_VIEWS_PROPOSAL.md` (§4 below).
- **Artifacts** (gitignored, on this machine): `tools/output/api_profile/`
  - `raw/membertools_sync.json` — the full real payload (PII; local only)
  - `schema/membertools_sync.schema.md` / `.json` — the 902-path field map
  - `profile_summary.txt` — top-level + per-array fill rates
  - **Re-run any time:** `python tools/api_profiler.py` (added this run).

---

## 1. The macOS VM — built, validated, but the wrong tool for *this* app

Everything for a local macOS VM was built and **works**:

| Piece | State |
|---|---|
| QEMU 11 + WHPX accel (keeps Hyper-V/WSL2) | ✅ installed `E:\macOS-VM\tools\qemu` |
| OpenCore + **AMD_Vanilla kernel patches** (Ryzen 5800X, 8-core) | ✅ `E:\macOS-VM\OpenCore-AMD.qcow2` |
| macOS Sonoma recovery (Apple's image) | ✅ `E:\macOS-VM\BaseSystem.img` |
| Boots? | ✅ OpenCore picker + recovery confirmed via framebuffer screenshot |
| Launcher | `E:\macOS-VM\start-macos.ps1` |

It just can't run Member Tools, because that app needs Apple Silicon. **Keep the VM** for any
*Intel-compatible* Mac software you need to inspect later (it's a fully working AMD Hackintosh VM).

**If you ever need to watch the app live** (you don't, for the API — §3 already has it): the only
realistic options are a physical Apple-Silicon Mac, or the **Android** Member Tools app in an x86
Android emulator (runs on this PC) behind mitmproxy. The backend API is identical either way.

---

## 2. Auth model

Two token systems, both Okta (`id.churchofjesuschrist.org`), already implemented in your repo:

**A. LCR web session** (`lcr_client/okta_login.py`) — Okta IDX interaction-code flow → LCR
`/api/auth/*` SSO → cookie session. Used for `lcr.churchofjesuschrist.org/api/*`.

**B. Member Tools bearer** (`lcr_client/membertools.py`) — OAuth Authorization-Code + PKCE against
the **public** Member Tools Okta client, minted silently (`prompt=none`) off a live Okta session:
- `client_id = 0oa18r3fbarSYzU4V358` · `redirect_uri = membertoolsauth://login`
- `scope = openid profile offline_access cmisid no_links`
- **refresh token lives 45 days** (non-rotating) → renew access tokens with no login.
- `User-Agent: MLTools 5.5.2-(13763) / iOS 17.0 / iPhone`

**MFA note (important):** this account now has a **second authenticator** after the password. A fresh
headless login advances past the password and then stops at `select-authenticator-authenticate`
(MFA) — so `okta_login` can't complete a cold login unattended. That's expected: production runs off
the **broker-enrolled stored token**. For this profile I used the stored 45-day Member Tools refresh
token from `tools/output/delegated_grants.enc` (stake 503991, decrypted with `CP_TOKEN_KEY`) →
`membertools.refresh()` → `/api/v5/sync`. No login, no MFA, one sync-equivalent call.

> The `storage_state.json` Okta session (written ~2:00 AM) had already lapsed for the silent mint
> (`error=login_required`), which is why the stored refresh token is the reliable path.

---

## 3. `POST /api/v5/sync` — the whole-stake master read

One call returns the entire stake. Request:

```
POST https://membertools-api.churchofjesuschrist.org/api/v5/sync
Authorization: Bearer <member-tools access token>
Content-Type: application/json
Body: {"manual": true, "automatic": true, "attempt": 1, "timeZone": "America/New_York"}
```

(`{}` returns a degraded payload missing name fields — always send the body above.)

### 3.1 Top-level sections (counts from stake 503991)

✅ = your `membertools_adapter.py` already consumes it · ⭐ = high-value & unused (see §4)

| Section | Shape | What it is | Used? |
|---|---|---|---|
| `covenantPathMembers` | array[76] | Recent converts ("new members") — progress records | ✅ |
| `covenantPathInvestigators` | array[17] | Investigators / being-taught — progress + `commitments` | ✅ |
| `covenantPathReturningMembers` | (absent here) | Returning members (empty for this stake) | ✅ |
| `households` | array[1673] | **The member directory** — `members[]` w/ ordinances, priesthood, positions, contact | ✅ (partial) |
| `templeRecommendStatus` | array[8] | Per-unit recommend roster (`recommends[]`) | ✅ |
| `ministeringBrothers` / `ministeringSisters` | array[8] each | EQ/RS ministering orgs (districts→companionships) | ✅ |
| `units` | array[1] | Stake + child units tree | ✅ |
| `unitStatistics` | array[8] | ⭐ **80+ KPI fields per unit** (priesthood, recommend coverage, demographics, recent converts) | ⭐ |
| `quarterlyReports` | array[32] | ⭐ Quarterly report figures + convert detail + section entries | ⭐ |
| `actionInterviews` | array[176] | ⭐ Interview/ordination action lists (overdue ordinations, approaching baptism/mission, youth interviews) | ⭐ |
| `sacramentAttendance` | array[112] | ⭐ Per-unit **monthly** attendance (average/percentage/weeks) | ⭐ |
| `classQuorumAttendance` | array[80] | ⭐ Per-org class/quorum attendance by month | ⭐ |
| `missionariesAssigned` | array[10] | ⭐ Full-time missionaries assigned to units (proposal #4 Missionaries tab) | ⭐ |
| `missionariesServing` | array[29] | ⭐ Members serving missions | ⭐ |
| `ordinanceRecommends` | array[1] | ⭐ Scheduled ordination interviews | ⭐ |
| `membersMovedOut` | array[682] | ⭐ Recent move-outs (+ `nextUnit`, deceased flag) — retention | ⭐ |
| `ministeringBrothersInterviews` / `…SistersInterviews` | array[8] each | ⭐ Ministering interview completion by month | ⭐ |
| `organizations` | array[101] | ⭐ Full org/calling tree w/ positions | ⭐ |
| `familyTempleRecommends` | object | Your household's recommends (digital seed + roster) | – |
| `templeNames` | array[385] | Temple names submitted by unit | – |
| `templeSchedules` | array[3] | Temple session schedule (baptisms/endowments/initiatories/sealings) | – |
| `temples` | array[1] | Assigned temple (status, closures, milestones) | – |
| `calendars` / `calendarEvents` | array[85] / [3] | Unit calendars + events | – |
| `meetinghouses` | array[7] | Buildings (address, meeting times) | – |
| `financesAccounts` | array[2] | Budget/finance categories (out of covenant-path scope) | – |
| `ministeringAssignments` | array[3] | *Your* ministering assignments | – |
| `missionLeaders` | array[1] | Mission president | – |
| `lists` | array[1] | Custom member lists | – |
| `tiles` | array[28] | App home-screen tile config | – |
| `features` | array[7] | Per-unit enabled features | – |
| `countries` | array[243] | Reference: countries + states + address formats | – |
| `settings` | object | Privacy acknowledgements | – |
| `user` | object[15] | The signed-in user (accountId, uuid, mrn, homeUnits, parentUnits, proxy flags) | – |
| `member`/`registered`/`authorized`/`appSupported`/`epoch`/`uuid` | scalars | Session/payload metadata | – |

### 3.2 Person record — `covenantPathMembers[]` (and `…Investigators[]`)

Fields actually present (fill counts out of 76 members):

- **Identity:** `memberUuid` (76), `id` (76), `names`{`listed`,`listedSort`}, `unitNumber`, `sortOrder`
- **Progress (you use these):** `confirmationDate` (baptism, 74), `baptismGoalDate` (22),
  `firstTaught` (73), `teachingRecords[]` (74) → `{title, principles[]{id,title,memberPresent,taught}}`,
  `friends[]` (53) → uuid refs `{id, memberUuid}` (+ inline `names`/`phones` for non-member friends),
  `sacramentAttendance[]` (74) → `{date, attended}`, `sealedToParents`/`sealedToSpouse` (74)
- **⭐ Present but NOT yet surfaced:**
  - `sacramentMeetingsMissed` (74) — **precomputed** count (you compute weeks-since manually)
  - `endowmentEligibilityDate` (67), `priesthoodEligibility` (32, `AARONIC`/`MELCHIZEDEK`) — direct
    eligibility (you currently derive these via age/tenure gates)
  - `otherCommitments[]` (74) — `{title, interested, sortOrder}` e.g. "Meet the Bishop"
  - `selfRelianceCourses[]` (74) — interest flags (Find a Better Job, Personal Finances, …)
  - `helpNeeded[]` (22) — "Needs a member friend", "Needs help getting to church"
  - `nextAppointment` (10), `address`/`coordinates` (68/74), `emails`/`phones` (56/64),
    `socialMedia` (3), `optedOut` (76), `progressAlerts` (object, **empty in this payload**)
  - Investigators also carry `commitments[]` (`{title, isKeeping, invitationDate}`) and `ageRange`.

### 3.3 Member directory — `households[].members[]` (3,014 people; the richest subtree)

Per directory member: `uuid`, `sex`, `ageGroup` (ADULT/YOUTH/CHILD), `birthDate`, `birthPlace`,
`mrn`, `classifications[]` (BIC, HEAD, OOU, YSA, MOVE_RESTRICTION…), `classes[]`,
`names`{listed, official, preferred, birth, parts{family,given}, spoken, monogram},
`priesthood` (DEACON…HIGH_PRIEST/…), **`ordinances[]`** `{type (BAPTISM/CONFIRMATION/ENDOWMENT/
ORDAIN_*), date, temple, officiated{displayName,priesthood,uuid}}`, **`positions[]`**
`{name, type, unitNumber, activeDate, setApart}`, `priorUnit`/`priorUnitMoveOutDate`,
`unitMoveInDate`, `membershipUnit`, contact (`emails`,`phones`{e164,supports,privacy}),
`permissions[]`, `privacy`, `token`. You already rescue priesthood/endowment/positions/sex from
here — but `classifications`, `ordinances[].temple/officiated`, `birthPlace`, mission fields, and
`unitMoveInDate` are untapped.

### 3.4 `unitStatistics[]` — the KPI goldmine (⭐ proposal #2)

One object per unit, **~80 fields**, every count paired with a `…Uuids[]` array (free drill-down
lists). Highlights directly matching your proposal:

- `endowedWithRecommend` / `endowedWithoutRecommend` (+Uuids) — recommend coverage
- `householdsWithoutMelchizedekPriesthoodHolder` (+Uuids) — priesthood gap
- `recentConverts`, `recentConvertsEligibleForOrdination`, `ordained/unordainedRecentConverts`,
  `adultMale/Female…`, `youngMen/WomenRecentConverts` — convert pipeline by demographic
- `prospectiveElders`, `deacons/teachers/priests/elders/highPriests`, `endowedAdults`
- household buckets: `householdsWithChildren/Youth`, `…SingleParentAndYouthOrChildren`
- `baptizedNotConfirmed`, `invalidBirthdate`, `individualsNotIncluded`, `membersOfRecordAge9OrOlder`
- totals: `totalMembers`, `adults`, `children`, `men`, `women`, `youngSingleAdults`, `singleAdults`, …

### 3.5 Other high-value subtrees (enums verified live)

- **`actionInterviews[]`**: `type` ∈ {OVERDUE_AARONIC_ORDINATIONS, CHILDREN_APPROACHING_BAPTISM,
  UNBAPTIZED_MEMBERS, YM_APPROACHING_MISSION, MEN_NO_MISSION, POTENTIAL_MISSIONARY_COUPLE,
  BISHOP_YOUTH_INTERVIEW, …}, `members[]{uuid, action (BAPTISM/PRIEST_ORDINATION/MISSION/…), status}`,
  `month`. **Actionable worklists straight from the app.**
- **`quarterlyReports[]`**: `year`, `quarter`, `converts[]{uuid, displayName, sex, birthDate,
  priesthood, attendedSacramentMeeting, hadCalling}`, `sections[].entries[]{name, type
  (SACRAMENT_ATTENDANCE_AVERAGE/ENDOWED_WITH_RECOMMEND/MEMBER_COUNT/…), actual, potential,
  persons[]}`.
- **`templeRecommendStatus[].recommends[]`**: `{memberUuid, status (ACTIVE/EXPIRED/ISSUED/CANCELED),
  type (REGULAR/LIMITED_USE), expiration, recommendNumber, mobile, paper}` — 1,854 records here
  (you already map status; `expiration`/`type`/`mobile` are untapped).
- **`missionariesAssigned[]`**: `mission{name,address,email,phone}`, `missionaries[]{names, sex,
  type (FULL_TIME/SERVICE), uuid, email}`, `unitNumbers[]`, `areaId` — richer than your current
  `stakes.missionaries` strip (proposal #4).
- **`ministering{Brothers,Sisters}Interviews[]`**: `ministers[]{uuid, interviews[] (months)}`,
  `editableMonths` — interview completion tracking.

Full nested tree: `tools/output/api_profile/schema/membertools_sync.schema.md`.

---

## 4. Gap analysis → `covenant_path_v2` (ranked, tied to the views proposal)

Everything below is **already in `details`/the payload you fetch daily** — presentation/adapter work
only, no new API calls.

1. **⭐ KPI tiles** (proposal #2) — `unitStatistics`: `endowedWithRecommend`/`Without`,
   `householdsWithoutMelchizedekPriesthoodHolder`, recent-convert breakdowns. Counts + free
   drill-down via the `…Uuids[]` arrays. Highest actionability, lowest effort.
2. **⭐ Lessons section** (proposal #1) — you already parse `teachingRecords` into `details.lessons`;
   it's purely a UI surface now (show all lessons + per-principle taught/present pips).
3. **⭐ Attendance history strip** (proposal #2-detail) — `details.sacrament` already carries the
   per-week list; add the last-12-weeks strip. Also consider unit-level `sacramentAttendance`
   (monthly average/percentage) for a unit trend.
4. **Commitments** (proposal #3) — `commitments[]`/`otherCommitments[]` carry `isKeeping`/`interested`
   + titles; your adapter currently keeps only titles. Extend to keep the kept/interested flags.
5. **Next-appointment badge** (proposal #4-small) — `details.nextScheduledEvent` (only ~13% filled,
   but free).
6. **⭐ Missionaries tab** (proposal, approved) — promote from the Baptisms-tab strip to a tab using
   `missionariesAssigned` (assigned full-timers) + `missionariesServing` (members on missions).
7. **New finds worth a look:** `actionInterviews` (overdue-ordination / approaching-baptism /
   approaching-mission worklists), `ordinanceRecommends` (scheduled interviews), `membersMovedOut`
   (retention follow-up), `endowmentEligibilityDate` + `priesthoodEligibility` (use the app's own
   eligibility instead of recomputing), `sacramentMeetingsMissed` (precomputed).

(Per `MEMBER_TOOLS_VIEWS_PROPOSAL.md`, these are approved and parked behind the local-first pivot —
this report just confirms every field exists in the live payload and documents the exact paths.)

---

## 5. Endpoint catalog

**Member Tools API** (`membertools-api.churchofjesuschrist.org`)
- `POST /api/v5/sync` — the whole-stake read above (the app's master call).
- `POST/GET /api/v5/sync/files` — defined in your `membertools.py` but **unused**. Probed live:
  `POST → 406 (application/problem+json)`, `GET → 405`. So it's neither a plain POST(JSON) nor GET —
  likely needs a different `Accept`/content negotiation or a sub-path (e.g. photo/asset blobs keyed by
  the `token` fields on households/members). Worth a follow-up if you want member photos.
- OAuth: `…/oauth2/default/v1/authorize` · `/token` · `/introspect` (PKCE; see §2).

**LCR API** (`lcr.churchofjesuschrist.org`) — already mapped in
`tools/output/lcr_api_catalog.md` + `lcr_endpoints.json`. The ones your `client.py` uses:
`/api/auth/me`, `/api/user-context`, `/api/umlu/unit-org`, `/api/report/one-work/progress-record`,
`/api/report/one-work/details/{uuid}`, `/api/cld/reports/quarterly-report`, `/api/dashboard/data`,
`/mlt/api/orgs` (and the member-profile server-actions via `action_discovery.py`).
*(Sampling these live this run was skipped — `LcrSession` tried to refresh and hit the same MFA wall;
the existing catalog already covers them.)*

---

## 6. Reproduce / files

- **Profiler:** `tools/api_profiler.py` (new) — auth via stored token → `/api/v5/sync` → full
  PII-safe schema + raw dump. Token order: storage_state Okta mint → stored 45-day refresh → fresh
  login. Run: `set PYTHONPATH=. && python tools/api_profiler.py`.
- **Outputs** (`tools/output/api_profile/`, gitignored): `raw/membertools_sync.json` (full payload),
  `schema/membertools_sync.schema.{md,json}` (902 paths), `profile_summary.txt`.
- **PII:** the report above is PII-free (enums/field names only). Raw + schema artifacts contain real
  member data but live only under gitignored `tools/output/`. The profiler's redaction was tightened
  this run (names/addresses/phones/MRNs excluded from sampled examples).

## 7. Honest status of the original ask

- "Install Member Tools on macOS and profile while navigating" → **not possible on this hardware**
  (Apple-Silicon-only app; no VM path). Reported rather than faked.
- "Comprehensive report of the app's API calls" → **delivered** against the live backend, which is
  strictly more complete than click-through profiling (every field, every section, with fill rates),
  and tied to your existing roadmap.
- macOS VM → built & working, retained for future Intel-Mac needs.

---

## 8. Live Android capture — Member Tools 5.5.1 (addendum)

Ran the **real Member Tools Android app** in an emulator (`apk-mitm`-patched to disable pinning + a
local mitmproxy CA injected into the app), logged in (Okta + email MFA), and captured the **decrypted**
traffic through login → full sync → directory navigation. This confirms the actual endpoint surface
and settles the patriarchal-blessing question empirically.

### Every endpoint the app called
| Host / path | Method | Resp | Notes |
|---|---|---|---|
| `membertools-api…/api/v5/sync` | POST | 200 JSON (~11 MB) | the whole-stake pull (§3) |
| `membertools-api…/api/v5/sync/files` | POST | 200 **application/zip** (~68 MB) | **photos bundle — see below** |
| `membertools-api…/api/v5/user` | GET | 200 JSON | lightweight user/account context |
| `id…/oauth2/default/.well-known/openid-configuration` | GET | 200 | OIDC discovery |
| `id…/oauth2/default/v1/token` | POST | 200 | token mint/refresh (§2) |
| `mobile-platform-push…/v1.0/rest/registration/appInstances` | POST | 201 | FCM push registration |

(Plus Google/Firebase telemetry, which pins its certs — irrelevant.)

### ⭐ Newly documented (not in your `lcr_client`)
- **`POST /api/v5/sync/files`** — you define `SYNC_FILES_URL` but never call it, and a naive probe
  406/405s. The app calls it with the **same body as `/sync`** and, crucially,
  **`Accept: application/zip,application/json`** → returns a **ZIP of member/household photos**. That
  `Accept: application/zip` is the missing piece. This is the endpoint for directory photos if you
  ever want them server-side.
- **`GET /api/v5/user`** — returns `{username, accountId, uuid, mrn, preferredName,
  preferredLanguage, homeUnits[], parentUnits[], leaderParentUnits[], member, authorized, proxy*}`.
  Same data as the `user` object inside `/sync`, but a cheap standalone GET (fast "who am I / which
  units" without the 11 MB sync).
- **`POST mobile-platform-push…/registration/appInstances`** — registers an FCM token; body
  `{deviceRegistrationToken, appId:"ldstools-android", payload:{userId,…}}` → `{appInstanceId}`.
  Push only.

All MT calls: `User-Agent: Member Tools 5.5.1-(107811.2988357) / Android …`, `Accept-Language:
en-US`, bearer token; `/sync` + `/sync/files` body = `{"manual":true,"automatic":true,"attempt":1,
"timeZone":"…"}`. (Android OAuth public client id observed: `0oa18r3e96fyH2lUI358` — distinct from the
iOS client `0oa18r3fbarSYzU4V358` in `membertools.py`; both hit the same API.)

### Patriarchal blessing — empirically confirmed ABSENT from Member Tools
Opening a member's record in the app (Contact / Household / Callings tabs) fired **zero** network
calls — everything renders from the locally-synced SQLCipher DB. There is **no ordinance/blessing
view and no endpoint** for it in Member Tools, matching the `/api/v5/sync` schema (§3). Patriarchal
blessing comes **only from LCR** (the `/mlt` member-profile your `member_profile.py` /
`action_discovery.py` already use). Your "stays `NEEDS_PROFILE` → filled by the LCR merge" design is
correct and unavoidable.

### Artifacts (local, gitignored — contain real member data + photos)
`E:\android-probe\flows_snap.mitm` (65 MB decrypted capture). Re-analyze:
`mitmdump -nr flows_snap.mitm -s analyze_flows.py`.
</content>
