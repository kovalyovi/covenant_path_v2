import 'package:flutter/material.dart';

/// "Golden Hour" = a new member's first-year integration milestones. Modeled after the
/// reference iOS app's circle-chip row. Filled chip = complete.
class Milestone {
  final String label; // full name (detail + accessibility)
  final String abbr;  // chip label (1-2 chars)
  final bool Function(Map<String, dynamic>) complete;
  final bool maleOnly;
  const Milestone(this.label, this.abbr, this.complete, {this.maleOnly = false});
}

// Golden Hour = a new member's first-year *integration* milestones. Baptism is intentionally
// NOT a milestone (a new member is already baptized; it doesn't measure integration). The
// longer-horizon ordinances (recommend / patriarchal / endowment) are shown on the detail
// page but are not part of Golden Hour completion.
final milestones = <Milestone>[
  Milestone('Friends', 'F', (m) => m['friends'] == 'Yes'),
  Milestone('Calling', 'C', (m) => m['calling'] == 'Yes'),
  Milestone('Has ministers', 'M', (m) => m['ministering_brothers_sisters'] == 'Yes'),
  Milestone('Ministers to others', 'MA', (m) => m['ministering_assignment'] == 'Yes'),
  Milestone('Aaronic Priesthood', 'AP', (m) => m['aaronic_priesthood'] == 'Yes', maleOnly: true),
  Milestone('Melchizedek Priesthood', 'MP', (m) => m['melchizedek_priesthood'] == 'Yes', maleOnly: true),
];

List<Milestone> milestonesFor(Map<String, dynamic> m) =>
    milestones.where((x) => !x.maleOnly || m['sex'] == 'M').toList();

/// Row of small circle chips for one member (the iOS Golden Hour pattern). Filled = done.
/// With [highlightNext], the first not-yet-complete milestone gets an amber ring as the
/// suggested next step.
class GoldenHourChips extends StatelessWidget {
  const GoldenHourChips({super.key, required this.member, this.size = 24, this.highlightNext = false});
  final Map<String, dynamic> member;
  final double size;
  final bool highlightNext;

  @override
  Widget build(BuildContext context) {
    final list = milestonesFor(member);
    final nextIdx = highlightNext ? list.indexWhere((ms) => !ms.complete(member)) : -1;
    return Wrap(spacing: 5, runSpacing: 5, children: [
      for (var i = 0; i < list.length; i++)
        _chip(context, list[i], list[i].complete(member), isNext: i == nextIdx),
    ]);
  }

  Widget _chip(BuildContext context, Milestone ms, bool done, {bool isNext = false}) {
    final green = Colors.green.shade600;
    final amber = Colors.amber.shade700;
    final border = done ? green : (isNext ? amber : Colors.grey.shade400);
    return Tooltip(
      message: '${ms.label}: ${done ? "done" : (isNext ? "next step" : "not yet")}',
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: done ? green : (isNext ? amber.withValues(alpha: 0.15) : Colors.transparent),
          border: Border.all(color: border, width: isNext ? 2 : 1.2),
        ),
        child: Text(
          ms.abbr,
          style: TextStyle(
            fontSize: ms.abbr.length >= 2 ? 8.5 : 11,
            fontWeight: FontWeight.bold,
            color: done ? Colors.white : (isNext ? amber : Colors.grey.shade600),
          ),
        ),
      ),
    );
  }
}

/// Layout tiers — just three breakpoints (phone / tablet / desktop) drive the responsive UI.
enum ScreenTier { mobile, tablet, desktop }

ScreenTier tierFor(double width) =>
    width < 600 ? ScreenTier.mobile : (width < 1100 ? ScreenTier.tablet : ScreenTier.desktop);

/// Centers content and caps its width so pages don't stretch edge-to-edge on wide screens.
class MaxWidthBody extends StatelessWidget {
  const MaxWidthBody({super.key, required this.child, this.maxWidth = 1000});
  final Widget child;
  final double maxWidth;
  @override
  Widget build(BuildContext context) =>
      Center(child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxWidth), child: child));
}

/// A titled section as a clean rounded card — the building block for detail + KPI pages.
class SectionCard extends StatelessWidget {
  const SectionCard(
      {super.key, required this.title, required this.child, this.trailing, this.leadingIcon});
  final String title;
  final Widget child;
  final Widget? trailing;
  final IconData? leadingIcon;
  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            if (leadingIcon != null) ...[
              Icon(leadingIcon, size: 20, color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
            ],
            Expanded(
              child: Text(title,
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.bold)),
            ),
            if (trailing != null) trailing!,
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      ),
    );
  }
}

String initialsOf(String name) {
  final parts = name.replaceAll(',', '').trim().split(RegExp(r'\s+'));
  if (parts.isEmpty || parts.first.isEmpty) return '?';
  final s = parts.length == 1
      ? parts.first.characters.first
      : '${parts.first.characters.first}${parts.last.characters.first}';
  return s.toUpperCase();
}

class InitialsAvatar extends StatelessWidget {
  const InitialsAvatar({super.key, required this.name, this.size = 36});
  final String name;
  final double size;

  @override
  Widget build(BuildContext context) {
    return CircleAvatar(
      radius: size / 2,
      backgroundColor: Colors.indigo.shade100,
      child: Text(initialsOf(name),
          style: TextStyle(fontSize: size * 0.36, color: Colors.indigo.shade900, fontWeight: FontWeight.bold)),
    );
  }
}

/// Member avatar: shows the stored LCR photo (signed URL) when present, else falls back to
/// initials (also falls back if the image fails to load). Friends/ministers use initials.
class PhotoAvatar extends StatelessWidget {
  const PhotoAvatar({super.key, required this.name, this.photoUrl, this.size = 36});
  final String name;
  final String? photoUrl;
  final double size;

  @override
  Widget build(BuildContext context) {
    final url = photoUrl;
    if (url == null || url.isEmpty) return InitialsAvatar(name: name, size: size);
    return CircleAvatar(
      radius: size / 2,
      backgroundColor: Colors.indigo.shade100,
      foregroundImage: NetworkImage(url), // child shows until it loads / if it errors
      child: Text(initialsOf(name),
          style: TextStyle(fontSize: size * 0.36, color: Colors.indigo.shade900, fontWeight: FontWeight.bold)),
    );
  }
}
