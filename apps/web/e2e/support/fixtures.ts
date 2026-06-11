// FICTIONAL fixtures only — this repo is public, so nothing here may resemble real member data.
// People are "Avery Example" / "Jordan Sample" / etc., the stake is "Testvale North Stake"
// (unit 999001). Dates are computed relative to "now" so eligibility logic (age / tenure /
// recency windows) stays stable as the calendar moves.

// ---- Identity ----------------------------------------------------------------------------------

export const TEST_EMAIL = 'leader@example.test';
export const TEST_USER_ID = '00000000-0000-4000-8000-00000000e2e1';

export const STAKE_ID = '00000000-0000-4000-8000-000000999001';
export const STAKE_NAME = 'Testvale North Stake';
export const UNIT_NUMBER = 999001;

export const AVERY_UUID = 'e2e-person-avery';
export const JORDAN_UUID = 'e2e-person-jordan';
export const BLANK_UUID = 'e2e-person-blank';
export const RILEY_UUID = 'e2e-person-riley';

// ---- Date helpers ------------------------------------------------------------------------------

const isoDay = (d: Date): string => d.toISOString().slice(0, 10);

export function daysAgoIso(n: number): string {
  return new Date(Date.now() - n * 86_400_000).toISOString();
}

function monthsAgo(n: number): Date {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d;
}

function yearsAgo(n: number): Date {
  const d = new Date();
  d.setFullYear(d.getFullYear() - n);
  return d;
}

function daysFromNow(n: number): Date {
  return new Date(Date.now() + n * 86_400_000);
}

// ---- Supabase rows -----------------------------------------------------------------------------

export type Row = Record<string, unknown>;

/** One `stakes` row (the shape STAKE_COLS in useDashboard selects). */
export function stakeRow(over: Row = {}): Row {
  return {
    id: STAKE_ID,
    name: STAKE_NAME,
    last_synced_at: daysAgoIso(0.1), // ~2.4h ago
    sync_state: 'idle',
    sync_started_at: null,
    missionaries: {
      'Testvale 1st Ward': [{ name: 'Elder Sampleton', phone: '555-0100', email: 'sampleton@example.test' }],
    },
    ...over,
  };
}

/** Base member row with every MEMBER_COLUMNS key present (null by default). */
function baseMember(over: Row): Row {
  return {
    person_uuid: null,
    stake_id: STAKE_ID,
    unit_id: 9990011,
    name: null,
    unit_name: null,
    baptism_date: null,
    birth_date: null,
    membership_duration: null,
    sex: null,
    friends: null,
    friends_count: null,
    aaronic_priesthood: null,
    melchizedek_priesthood: null,
    calling: null,
    ministering_brothers_sisters: null,
    ministering_assignment: null,
    temple_recommend: null,
    patriarchal_blessing: null,
    living_ordinance: null,
    family_name_prepared: null,
    first_temple_visit: null,
    details: null,
    photo_url: null,
    kind: 'member',
    baptism_goal_date: null,
    field_meta: null,
    ...over,
  };
}

/** Adult convert with ALL 13 covenant-path fields populated + a rich `details` subtree. */
export function averyExample(over: Row = {}): Row {
  return baseMember({
    person_uuid: AVERY_UUID,
    name: 'Avery Example',
    unit_name: 'Testvale 1st Ward',
    baptism_date: isoDay(monthsAgo(8)),
    birth_date: isoDay(yearsAgo(30)),
    membership_duration: 'Member for 8 months',
    sex: 'M',
    friends: 'Yes',
    friends_count: 2,
    aaronic_priesthood: 'Yes',
    melchizedek_priesthood: 'No',
    calling: 'Yes',
    ministering_brothers_sisters: 'Yes',
    ministering_assignment: 'No',
    temple_recommend: 'Active',
    patriarchal_blessing: 'No',
    living_ordinance: 'No',
    family_name_prepared: 'Yes',
    first_temple_visit: 'No',
    field_meta: { temple_recommend: { f: daysAgoIso(1), t: daysAgoIso(1) } },
    details: {
      memberSince: 'Member for 8 months',
      sacrament: [
        { label: '1 Jun', attended: true },
        { label: '25 May', attended: false },
        { label: '18 May', attended: true },
      ],
      sacramentMissed: 1,
      friends: [
        { name: 'Casey Sample', unit: 'Testvale 1st Ward', inStake: true },
        { name: 'Robin Placeholder', unit: 'Testvale 2nd Ward', inStake: true },
      ],
      priesthoodOrdinations: ['Aaronic Priesthood — Priest'],
      callings: ['Sunday School Teacher'],
      ministeringAssignments: [],
      ministeringBrothers: ['Robin Placeholder'],
      ministeringSisters: [],
      templeExperiences: [
        { name: 'Prepare a Family Name for the Temple', done: true },
        { name: 'Perform Baptisms for Deceased Ancestors', done: false },
      ],
      templeOrdinances: [],
      lessons: [
        {
          name: 'The Restoration',
          principles: [
            { name: 'The First Vision', taughtLevel: '1', memberPresent: true },
            { name: 'Priesthood Restoration', taughtLevel: '0', memberPresent: false },
          ],
        },
      ],
      selfReliance: [{ name: 'Personal Finances', done: false }],
      tags: ['Recent convert'],
    },
    ...over,
  });
}

/** Investigator (being taught) with a planned FUTURE baptism goal date. */
export function jordanSample(over: Row = {}): Row {
  return baseMember({
    person_uuid: JORDAN_UUID,
    name: 'Jordan Sample',
    unit_name: 'Testvale 2nd Ward',
    sex: 'F',
    birth_date: isoDay(yearsAgo(22)),
    kind: 'investigator',
    baptism_goal_date: isoDay(daysFromNow(10)),
    ...over,
  });
}

/** The all-null member: only identity fields set — every covenant-path value is null. */
export function blankSample(over: Row = {}): Row {
  return baseMember({
    person_uuid: BLANK_UUID,
    name: 'Blank Sample',
    ...over,
  });
}

/** New teen member mid-milestones, with details present but every list EMPTY. */
export function rileyExample(over: Row = {}): Row {
  return baseMember({
    person_uuid: RILEY_UUID,
    name: 'Riley Example',
    unit_name: 'Testvale 2nd Ward',
    baptism_date: isoDay(monthsAgo(2)),
    birth_date: isoDay(yearsAgo(15)),
    membership_duration: 'Member for 2 months',
    sex: 'F',
    friends: 'Yes',
    friends_count: 0,
    calling: 'No',
    ministering_brothers_sisters: 'Yes',
    ministering_assignment: 'No',
    temple_recommend: 'No',
    patriarchal_blessing: 'No',
    living_ordinance: 'No',
    family_name_prepared: 'No',
    first_temple_visit: 'No',
    details: {
      memberSince: 'Member for 2 months',
      sacrament: [],
      friends: [],
      priesthoodOrdinations: [],
      callings: [],
      ministeringAssignments: [],
      ministeringBrothers: [],
      ministeringSisters: [],
      templeExperiences: [],
      templeOrdinances: [],
      lessons: [],
      selfReliance: [],
      tags: [],
    },
    ...over,
  });
}

/** The default member set: every value-variant the table + detail views must survive. */
export function defaultMembers(): Row[] {
  return [averyExample(), jordanSample(), blankSample(), rileyExample()];
}

/** One pre-existing leader note on Avery (member_comments row). */
export function defaultComments(): Row[] {
  return [
    {
      stake_id: STAKE_ID,
      unit_id: 9990011,
      member_person_uuid: AVERY_UUID,
      author_email: 'clerk@example.test',
      author_name: 'Jamie Clerksample',
      body: 'Welcomed at sacrament meeting.',
      created_at: daysAgoIso(2),
    },
  ];
}

// ---- Broker response builders -------------------------------------------------------------------

export interface CredentialJson {
  state?: string;
  complete?: boolean;
  principal_name?: string | null;
  is_provider?: boolean;
  enrolled_at?: string | null;
  last_error?: string | null;
}

/** GET /auth/enrollment-status body. `status: 'no_role'` marks a viewer with no LCR role. */
export function enrollmentStatus(over: Row = {}, cred: CredentialJson = {}): Row {
  return {
    status: 'ok',
    stake_name: STAKE_NAME,
    stake_id: STAKE_ID,
    unit_number: UNIT_NUMBER,
    last_synced_at: daysAgoIso(0.1),
    member_count: 4,
    has_data: true,
    credential: {
      state: 'active',
      complete: true,
      principal_name: 'Morgan Example',
      is_provider: false,
      enrolled_at: daysAgoIso(30),
      last_error: null,
      ...cred,
    },
    ...over,
  };
}

/** A successful broker login body ({session:{email,otp}} + optional `enroll` evaluation). */
export function brokerLogin(enroll?: Row, over: Row = {}): Row {
  return {
    session: { email: TEST_EMAIL, otp: '123456' },
    identity_name: 'Morgan Example',
    ...(enroll !== undefined ? { enroll } : {}),
    timing: { total_ms: 850 },
    ...over,
  };
}

export const MFA_FACTORS = [
  { id: 'f-sms', label: 'Text message to •••1234', method: 'sms' },
  { id: 'f-totp', label: 'Authenticator app', method: 'totp' },
];

/** An MFA-required broker login body. */
export function brokerMfa(factors: Row[] = MFA_FACTORS): Row {
  return { status: 'mfa_required', login_id: 'e2e-login-1', factors };
}
