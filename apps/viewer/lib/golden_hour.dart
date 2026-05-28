import 'package:flutter/material.dart';

/// "Golden Hour" = a new member's first-year integration milestones. Modeled after the
/// reference iOS app's circle-chip row, extended with the data we have that it lacks
/// (baptism, recommend, patriarchal, endowment). Filled chip = complete.
class Milestone {
  final String label; // full name (detail + accessibility)
  final String abbr;  // chip label (1-2 chars)
  final bool Function(Map<String, dynamic>) complete;
  final bool maleOnly;
  const Milestone(this.label, this.abbr, this.complete, {this.maleOnly = false});
}

bool _filled(dynamic v) =>
    v != null &&
    v.toString().trim().isNotEmpty &&
    !{'N/A', 'No', 'needs-profile-api', 'blocked: insufficient calling access'}
        .contains(v.toString());

final milestones = <Milestone>[
  Milestone('Friends', 'F', (m) => m['friends'] == 'Yes'),
  Milestone('Calling', 'C', (m) => m['calling'] == 'Yes'),
  Milestone('Has ministers', 'M', (m) => m['ministering_brothers_sisters'] == 'Yes'),
  Milestone('Ministers to others', 'MA', (m) => m['ministering_assignment'] == 'Yes'),
  Milestone('Aaronic Priesthood', 'AP', (m) => m['aaronic_priesthood'] == 'Yes', maleOnly: true),
  Milestone('Melchizedek Priesthood', 'MP', (m) => m['melchizedek_priesthood'] == 'Yes', maleOnly: true),
  Milestone('Baptized', 'B', (m) => _filled(m['baptism_date'])),
  Milestone('Temple recommend', 'R', (m) => m['temple_recommend'] == 'Active'),
  Milestone('Patriarchal blessing', 'P', (m) => m['patriarchal_blessing'] == 'Yes'),
  Milestone('Endowed', 'E', (m) => m['living_ordinance'] == 'Yes'),
];

List<Milestone> milestonesFor(Map<String, dynamic> m) =>
    milestones.where((x) => !x.maleOnly || m['sex'] == 'M').toList();

/// Row of small circle chips for one member (the iOS Golden Hour pattern).
class GoldenHourChips extends StatelessWidget {
  const GoldenHourChips({super.key, required this.member, this.size = 24});
  final Map<String, dynamic> member;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Wrap(spacing: 5, runSpacing: 5, children: [
      for (final ms in milestonesFor(member)) _chip(context, ms, ms.complete(member)),
    ]);
  }

  Widget _chip(BuildContext context, Milestone ms, bool done) {
    final green = Colors.green.shade600;
    return Tooltip(
      message: '${ms.label}: ${done ? "done" : "not yet"}',
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: done ? green : Colors.transparent,
          border: Border.all(color: done ? green : Colors.grey.shade400, width: 1.2),
        ),
        child: Text(
          ms.abbr,
          style: TextStyle(
            fontSize: ms.abbr.length >= 2 ? 8.5 : 11,
            fontWeight: FontWeight.bold,
            color: done ? Colors.white : Colors.grey.shade600,
          ),
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
