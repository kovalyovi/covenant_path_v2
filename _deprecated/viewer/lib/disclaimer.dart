import 'package:flutter/material.dart';

/// Not-an-official-Church-app disclaimers, in one place so every surface stays consistent.
const kDisclaimerShort =
    'Independent tool · not affiliated with or endorsed by the Church · built by ILYA Kovalyov.';

const kDisclaimerLong =
    "Covenant Path is an independent tool built by ILYA Kovalyov to help leaders track new and "
    "prospective members' covenant path. It is NOT an official product of The Church of Jesus "
    "Christ of Latter-day Saints.";

const kPrivacyNote =
    "You only ever see the data your calling allows. Your stake's data is gathered through one "
    "connected leader's Church (LCR) session — the one with the most access — so your Church login "
    "is used for syncing only when your stake has no equal-or-better connection yet. Stored sessions "
    "are encrypted (never your password) and you can revoke access anytime in Settings.";

/// Small grey footer line for the bottom of a page.
class DisclaimerFooter extends StatelessWidget {
  const DisclaimerFooter({super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Text(kDisclaimerShort,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade500)),
      );
}

/// "About & privacy" dialog — the full disclaimer + how credentials are handled.
Future<void> showAboutDisclaimer(BuildContext context) => showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('About & privacy'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text(kDisclaimerLong),
            const SizedBox(height: 12),
            Text('Privacy', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 4),
            const Text(kPrivacyNote),
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
      ),
    );

/// "Rules & definitions" (#4) — a plain-language summary of the eligibility / access / convert-care
/// rules. Full reference: docs/RULES.md. Surfaced from Settings; the same content is mirrored on iOS
/// and Android.
Future<void> showRulesDialog(BuildContext context) => showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Rules & definitions'),
        content: const SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              _RulesSection('Who can see the data', [
                'Access is rebuilt from LCR callings every sync — no manual setup.',
                'A calling can see covenant-path data if it has the progress record, member list, or '
                    'member profiles (stake presidency / clerks / high council always can).',
                'Stake callings see the whole stake; ward/branch callings see their unit only.',
                'Released leaders lose access automatically next sync. Power users get an exact copy '
                    'of someone\'s access.',
              ]),
              _RulesSection('Priesthood & ordinance eligibility', [
                'Calling applies at 12+, giving ministering at 14+.',
                'Aaronic Priesthood: brothers 12+. Melchizedek: brothers 18+ who have been members 1+ year.',
                'Friends and assigned ministers apply to everyone.',
                'People who don\'t qualify (age / sex / tenure) show N/A, not "No", so stats aren\'t skewed.',
              ]),
              _RulesSection('Who watches over a convert', [
                'First year after baptism: the full-time missionaries + ward mission leader.',
                'After a year: Elders Quorum (brothers) / Relief Society (sisters).',
              ]),
              _RulesSection('Who shows where', [
                'People being taught (not yet baptized) appear only in Baptisms and Golden Hour\'s "Being Taught".',
                'Baptised & confirmed counts use the convert\'s baptism month.',
              ]),
            ]),
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
      ),
    );

class _RulesSection extends StatelessWidget {
  const _RulesSection(this.title, this.points);
  final String title;
  final List<String> points;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          for (final p in points)
            Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('•  '),
                Expanded(child: Text(p, style: Theme.of(context).textTheme.bodySmall)),
              ]),
            ),
        ]),
      );
}
