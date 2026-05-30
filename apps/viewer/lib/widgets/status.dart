import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// A health pill: green check when [ok], else an amber error with [offText]. Shared by the ops
/// console (system health, diagnostics). Was `_Pill` duplicated in admin_page (#67).
class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label, required this.ok, this.offText = 'down'});
  final String label;
  final bool ok;
  final String offText;

  @override
  Widget build(BuildContext context) {
    final c = ok ? AppColors.successFg : AppColors.warning;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: 7),
      decoration: BoxDecoration(
        color: AppColors.tint(c),
        borderRadius: AppRadius.pillBorder,
        border: Border.all(color: c),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(ok ? Icons.check_circle : Icons.error_outline, size: 16, color: c),
        const SizedBox(width: AppSpacing.xs + 2),
        Text('$label · ${ok ? 'ok' : offText}', style: TextStyle(color: c)),
      ]),
    );
  }
}

/// A small tinted, outlined tag for a status word (e.g. "Active · partial"). Shared by the
/// enrolled-stakes ops view + anywhere a compact colored label is needed. Was `_tag` (#67).
class StatusTag extends StatelessWidget {
  const StatusTag(this.text, {super.key, required this.color});
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm, vertical: 2),
      decoration: BoxDecoration(
        color: AppColors.tint(color),
        borderRadius: const BorderRadius.all(Radius.circular(12)),
        border: Border.all(color: color),
      ),
      child: Text(text, style: TextStyle(color: color, fontSize: 12)),
    );
  }
}
