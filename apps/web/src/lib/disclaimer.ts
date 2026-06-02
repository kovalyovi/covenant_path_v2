// Not-an-official-Church-app disclaimers + the Rules & definitions content, in one place so every
// surface stays consistent. Ported verbatim from apps/viewer/lib/disclaimer.dart.

export const kDisclaimerShort =
  'Independent tool · not affiliated with or endorsed by the Church · built by ILYA Kovalyov.';

export const kDisclaimerLong =
  'Covenant Path is an independent tool built by ILYA Kovalyov to help leaders track new and ' +
  "prospective members' covenant path. It is NOT an official product of The Church of Jesus " +
  'Christ of Latter-day Saints.';

export const kPrivacyNote =
  "You only ever see the data your calling allows. Your stake's data is gathered through one " +
  "connected leader's Church (LCR) session — the one with the most access — so your Church login " +
  'is used for syncing only when your stake has no equal-or-better connection yet. Stored sessions ' +
  'are encrypted (never your password) and you can revoke access anytime in Settings.';

/** The consent note shown under the Church-account password field (mirrors login_page.dart). */
export const kChurchSyncNote =
  "Your stake syncs through one connected leader's Church session — whichever has the most " +
  'access. Signing in connects yours only if your stake has no equal-or-better link yet; if so ' +
  "it's stored encrypted (never your password) to refresh data daily. Pause or revoke anytime in " +
  'Settings → Sync settings.';

/** The N2 no-access message shown when a Church login's calling grants no data access. */
export const kNoAccessMessage =
  "This account doesn't have access to Covenant Path. Access is granted by your calling — " +
  'if you should have access, ask your stake leadership.';

export interface RulesSection {
  title: string;
  points: string[];
}

/** "Rules & definitions" (#4) — a plain-language summary. Full reference: docs/RULES.md. */
export const rulesSections: RulesSection[] = [
  {
    title: 'Who can see the data',
    points: [
      'Access is rebuilt from LCR callings every sync — no manual setup.',
      'A calling can see covenant-path data if it has the progress record, member list, or member profiles (stake presidency / clerks / high council always can).',
      'Stake callings see the whole stake; ward/branch callings see their unit only.',
      "Released leaders lose access automatically next sync. Power users get an exact copy of someone's access.",
    ],
  },
  {
    title: 'Priesthood & ordinance eligibility',
    points: [
      'Calling applies at 12+, giving ministering at 14+.',
      'Aaronic Priesthood: brothers 12+. Melchizedek: brothers 18+ who have been members 1+ year.',
      'Friends and assigned ministers apply to everyone.',
      'People who don\'t qualify (age / sex / tenure) show N/A, not "No", so stats aren\'t skewed.',
    ],
  },
  {
    title: 'Who watches over a convert',
    points: [
      'First year after baptism: the full-time missionaries + ward mission leader.',
      'After a year: Elders Quorum (brothers) / Relief Society (sisters).',
    ],
  },
  {
    title: 'Who shows where',
    points: [
      'People being taught (not yet baptized) appear only in Baptisms and Golden Hour\'s "Being Taught".',
      "Baptised & confirmed counts use the convert's baptism month.",
    ],
  },
];
