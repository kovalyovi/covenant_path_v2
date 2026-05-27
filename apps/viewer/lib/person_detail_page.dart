import 'package:flutter/material.dart';

import 'golden_hour.dart';

/// Full covenant-path detail for one member — every field we have (more than the
/// reference iOS app, which lacks baptism/recommend/etc.).
class PersonDetailPage extends StatelessWidget {
  const PersonDetailPage({super.key, required this.member});
  final Map<String, dynamic> member;

  static const _fields = <(String, String)>[
    ('Unit', 'unit_name'),
    ('Baptism date', 'baptism_date'),
    ('Member for', 'membership_duration'),
    ('Birth date', 'birth_date'),
    ('Friends', 'friends'),
    ('Aaronic Priesthood', 'aaronic_priesthood'),
    ('Melchizedek Priesthood', 'melchizedek_priesthood'),
    ('Calling', 'calling'),
    ('Ministering brothers/sisters', 'ministering_brothers_sisters'),
    ('Ministering assignment', 'ministering_assignment'),
    ('Temple recommend', 'temple_recommend'),
    ('Patriarchal blessing', 'patriarchal_blessing'),
    ('Living ordinance', 'living_ordinance'),
  ];

  @override
  Widget build(BuildContext context) {
    final name = member['name']?.toString() ?? '—';
    final done = milestonesFor(member).where((x) => x.complete(member)).length;
    final total = milestonesFor(member).length;
    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: ListView(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(children: [
              InitialsAvatar(name: name, size: 48),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(name, style: Theme.of(context).textTheme.titleLarge),
                  Text('Golden Hour: $done / $total milestones',
                      style: Theme.of(context).textTheme.bodySmall),
                ]),
              ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: GoldenHourChips(member: member, size: 30),
          ),
          const Divider(height: 24),
          for (final f in _fields)
            ListTile(
              dense: true,
              title: Text(f.$1),
              trailing: Text('${member[f.$2] ?? '—'}',
                  style: const TextStyle(fontWeight: FontWeight.w500)),
            ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}
