import 'package:flutter/material.dart';

/// Not-an-official-Church-app disclaimers, in one place so every surface stays consistent.
const kDisclaimerShort =
    'Independent tool · not affiliated with or endorsed by the Church · built by ILYA Kovalyov.';

const kDisclaimerLong =
    "Covenant Path is an independent tool built by ILYA Kovalyov to help leaders track new and "
    "prospective members' covenant path. It is NOT an official product of The Church of Jesus "
    "Christ of Latter-day Saints.";

const kPrivacyNote =
    "Sign in with your Church (LCR) account is used to retrieve your stake's data on your behalf. "
    "Your session is stored encrypted — your password is never stored — access is scoped to your "
    "calling, and you can revoke it at any time.";

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
