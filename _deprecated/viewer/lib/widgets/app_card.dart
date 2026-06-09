import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// A titled card — bold title row (optional trailing) over content. The shared replacement for the
/// per-file `_Card` widgets the ops console and dashboard had duplicated (#67 style-system work).
/// Card chrome (border, margin, radius) comes from the app's cardTheme, so this only lays out.
class AppCard extends StatelessWidget {
  const AppCard({super.key, required this.title, required this.child, this.trailing});
  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: AppSpacing.cardPadding,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
                child: Text(title,
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold))),
            if (trailing != null) trailing!,
          ]),
          AppSpacing.gapSm,
          child,
        ]),
      ),
    );
  }
}
