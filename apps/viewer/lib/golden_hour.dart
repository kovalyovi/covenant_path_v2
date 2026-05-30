import 'package:flutter/material.dart';

/// "Golden Hour" = a new member's first-year integration milestones. Modeled after the
/// reference iOS app's circle-chip row. Filled chip = complete.
class Milestone {
  final String label; // full name (detail + accessibility)
  final String abbr;  // chip label (1-2 chars)
  final bool Function(Map<String, dynamic>) complete;
  final bool Function(Map<String, dynamic>) eligible; // who this milestone can apply to
  const Milestone(this.label, this.abbr, this.complete, {this.eligible = _everyone});
}

bool _everyone(Map<String, dynamic> m) => true;

int? _yearOf(dynamic v) {
  final mt = RegExp(r'(\d{4})').firstMatch(v?.toString() ?? '');
  return mt != null ? int.parse(mt.group(1)!) : null;
}

DateTime? _dateOf(dynamic v) {
  final s = (v?.toString() ?? '').trim();
  if (s.isEmpty || s == 'N/A' || s == 'needs-profile-api') return null;
  final iso = DateTime.tryParse(s);
  if (iso != null) return iso;
  final m = RegExp(r'^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$').firstMatch(s);
  if (m != null) {
    const mo = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
    final i = mo.indexOf(m.group(2)!.toLowerCase().substring(0, 3));
    if (i >= 0) return DateTime(int.parse(m.group(3)!), i + 1, int.parse(m.group(1)!));
  }
  return null;
}

/// "Turns at least [age] by the end of this calendar year" — matches the Church's by-year
/// quorum/advancement rule (an 11-year-old turning 12 this year counts). Unknown birth →
/// not eligible for age-gated milestones (so we don't ding someone we can't assess).
bool _turnsAtLeast(Map<String, dynamic> m, int age) {
  final by = _yearOf(m['birth_date']);
  return by != null && (DateTime.now().year - by) >= age;
}

bool _memberOneYearPlus(Map<String, dynamic> m) {
  final b = _dateOf(m['baptism_date']);
  if (b != null) return DateTime.now().difference(b).inDays >= 365;
  final ym = RegExp(r'(\d+)\s*year').firstMatch((m['membership_duration'] ?? '').toString().toLowerCase());
  return ym != null && int.parse(ym.group(1)!) >= 1;
}

/// Actual current age (uses full birth date when present, else by-year). For "already N now"
/// rules (Melchizedek / endowment), distinct from the by-year `_turnsAtLeast`.
int? _ageNow(Map<String, dynamic> m) {
  final d = _dateOf(m['birth_date']);
  if (d != null) {
    final now = DateTime.now();
    var age = now.year - d.year;
    if (now.month < d.month || (now.month == d.month && now.day < d.day)) age--;
    return age;
  }
  final by = _yearOf(m['birth_date']);
  return by == null ? null : DateTime.now().year - by;
}

bool _ageNowAtLeast(Map<String, dynamic> m, int age) {
  final a = _ageNow(m);
  return a != null && a >= age;
}

bool _male(Map<String, dynamic> m) => m['sex'] == 'M';

// Golden Hour = a new member's first-year *integration* milestones, each gated to who it can
// actually apply to (age / sex / tenure) so completion stats don't penalize the ineligible.
// Baptism is intentionally NOT a milestone; the longer-horizon ordinances live on the detail page.
final milestones = <Milestone>[
  Milestone('Friends', 'F', (m) => m['friends'] == 'Yes'), // everyone
  Milestone('Calling', 'C', (m) => m['calling'] == 'Yes',
      eligible: (m) => _turnsAtLeast(m, 12)),
  Milestone('Has ministers', 'M', (m) => m['ministering_brothers_sisters'] == 'Yes'), // everyone
  Milestone('Ministering assignment', 'MA', (m) => m['ministering_assignment'] == 'Yes',
      eligible: (m) => _turnsAtLeast(m, 14)), // gives ministering: 14+ (both sexes)
  Milestone('Aaronic Priesthood', 'AP', (m) => m['aaronic_priesthood'] == 'Yes',
      eligible: (m) => _male(m) && _turnsAtLeast(m, 12)),
  Milestone('Melchizedek Priesthood', 'MP', (m) => m['melchizedek_priesthood'] == 'Yes',
      eligible: (m) => _male(m) && _ageNowAtLeast(m, 18) && _memberOneYearPlus(m)),
];

List<Milestone> milestonesFor(Map<String, dynamic> m) =>
    milestones.where((x) => x.eligible(m)).toList();

/// Convert responsibility (the stake's hand-off policy, #23): the first year after baptism the
/// missionaries + ward/branch mission leader track progress; after a year it moves to the Elders
/// Quorum (men) / Relief Society (women) president. Returns a label + icon for the chip/filter.
({String label, IconData icon}) responsibleParty(Map<String, dynamic> m) {
  final b = _dateOf(m['baptism_date']);
  final months = b == null ? null : (DateTime.now().difference(b).inDays / 30.44).floor();
  if (months == null) return (label: 'Unassigned', icon: Icons.help_outline);
  if (months < 12) return (label: 'Missionaries / WML', icon: Icons.volunteer_activism);
  return _male(m)
      ? (label: 'Elders Quorum', icon: Icons.groups_2_outlined)
      : (label: 'Relief Society', icon: Icons.diversity_1_outlined);
}

/// Display age (e.g. "35 yrs") from birth_date, or null when unknown.
String? ageOf(Map<String, dynamic> m) {
  final a = _ageNow(m);
  return (a == null || a < 0) ? null : '$a yrs';
}

/// The two ownership buckets, for filtering. 'WML' = first-year (missionaries/ward mission leader);
/// 'RSEQ' = after-first-year (Relief Society / Elders Quorum).
String responsibleBucket(Map<String, dynamic> m) {
  final b = _dateOf(m['baptism_date']);
  final months = b == null ? null : (DateTime.now().difference(b).inDays / 30.44).floor();
  return (months != null && months >= 12) ? 'RSEQ' : 'WML';
}

/// Row of small circle chips for one member (the iOS Golden Hour pattern). Filled = done.
/// With [highlightNext], the first not-yet-complete milestone gets an amber ring as the
/// suggested next step.
class GoldenHourChips extends StatelessWidget {
  const GoldenHourChips(
      {super.key, required this.member, this.size = 24, this.highlightNext = false,
      this.labeled = false});
  final Map<String, dynamic> member;
  final double size;
  final bool highlightNext;
  final bool labeled; // full-text pills (person detail) vs compact circles (lists)

  @override
  Widget build(BuildContext context) {
    final list = milestonesFor(member);
    final nextIdx = highlightNext ? list.indexWhere((ms) => !ms.complete(member)) : -1;
    return Wrap(spacing: labeled ? 8 : 5, runSpacing: labeled ? 8 : 5, children: [
      for (var i = 0; i < list.length; i++)
        labeled
            ? _labeledChip(context, list[i], list[i].complete(member), isNext: i == nextIdx)
            : _chip(context, list[i], list[i].complete(member), isNext: i == nextIdx),
    ]);
  }

  Widget _labeledChip(BuildContext context, Milestone ms, bool done, {bool isNext = false}) {
    final green = Colors.green.shade600, amber = Colors.amber.shade700;
    final c = done ? green : (isNext ? amber : Colors.grey.shade500);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: done ? green.withValues(alpha: 0.12) : (isNext ? amber.withValues(alpha: 0.12) : null),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: c, width: isNext ? 1.6 : 1),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(done ? Icons.check_circle : (isNext ? Icons.arrow_forward : Icons.circle_outlined),
            size: 15, color: c),
        const SizedBox(width: 5),
        Text(ms.label, style: TextStyle(fontSize: 13, color: c, fontWeight: FontWeight.w500)),
      ]),
    );
  }

  Widget _chip(BuildContext context, Milestone ms, bool done, {bool isNext = false}) {
    final green = Colors.green.shade600;
    final amber = Colors.amber.shade700;
    final border = done ? green : (isNext ? amber : Colors.grey.shade400);
    return Tooltip(
      message: '${ms.label}: ${done ? "done" : (isNext ? "next step" : "not yet")}',
      triggerMode: TooltipTriggerMode.tap, // mobile: tap a pill to see what it means
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
      {super.key, required this.title, required this.child, this.trailing, this.leadingIcon,
      this.iconColor, this.onTap});
  final String title;
  final Widget child;
  final Widget? trailing;
  final IconData? leadingIcon;
  final Color? iconColor;
  final VoidCallback? onTap; // when set, the whole card is tappable (#37)
  @override
  Widget build(BuildContext context) {
    final accent = iconColor ?? Theme.of(context).colorScheme.primary;
    return Card(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            if (leadingIcon != null) ...[
              Container(
                padding: const EdgeInsets.all(7),
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(leadingIcon, size: 18, color: accent),
              ),
              const SizedBox(width: 10),
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
