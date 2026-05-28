import 'package:flutter/material.dart';

import 'golden_hour.dart';

/// Full covenant-path detail for one member, laid out like LCR's "new member" record:
/// sacrament-attendance dots, friends in the church, priesthood / calling / ministering,
/// temple ordinances & experiences, principles taught, and self-reliance classes.
///
/// Driven by `member['details']` (the rich one-work subtree the sync now keeps). When
/// that's null — a row synced before the schema change — it falls back to the flat
/// fields so the page still renders.
class PersonDetailPage extends StatelessWidget {
  const PersonDetailPage({super.key, required this.member});
  final Map<String, dynamic> member;

  Map<String, dynamic>? get _details {
    final d = member['details'];
    return d is Map ? d.cast<String, dynamic>() : null;
  }

  @override
  Widget build(BuildContext context) {
    final name = member['name']?.toString() ?? '—';
    final d = _details;
    final memberSince =
        (d?['memberSince'] ?? member['membership_duration'])?.toString();

    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
        children: [
          // header
          Row(children: [
            PhotoAvatar(name: name, photoUrl: member['photo_url']?.toString(), size: 56),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(name, style: Theme.of(context).textTheme.titleLarge),
                if (memberSince != null && memberSince.isNotEmpty)
                  Text(memberSince, style: Theme.of(context).textTheme.bodyMedium),
              ]),
            ),
          ]),
          const SizedBox(height: 16),

          // our covenant-path milestones (data LCR's view lacks: baptism/recommend/etc.)
          _Section(
            title: 'Covenant Path',
            child: GoldenHourChips(member: member, size: 30),
          ),

          if (d != null)
            _RichBody(member: member, d: d)
          else
            _FlatFallback(member: member),
        ],
      ),
    );
  }
}

/// Two columns on wide screens, stacked on narrow (phones). Mirrors LCR's layout.
class _RichBody extends StatelessWidget {
  const _RichBody({required this.member, required this.d});
  final Map<String, dynamic> member;
  final Map<String, dynamic> d;

  @override
  Widget build(BuildContext context) {
    final left = <Widget>[
      _SacramentSection(d: d),
      _FriendsSection(d: d),
      _ListTextSection(
        title: 'Priesthood Ordination',
        lines: _strings(d['priesthoodOrdinations']),
        emptyText: 'No priesthood ordination on record.',
      ),
      _ListTextSection(
        title: 'Calling',
        lines: _strings(d['callings']),
        emptyText: 'Not yet been given a calling.',
        emptyIsAlert: true,
      ),
      _ListTextSection(
        title: 'Ministering Assignment',
        lines: _strings(d['ministeringAssignments']),
        emptyText: 'Not yet received a ministering assignment.',
      ),
      _NamesSection(
        title: 'Ministering Brothers & Sisters',
        names: [..._strings(d['ministeringBrothers']), ..._strings(d['ministeringSisters'])],
        emptyText: 'No ministers assigned.',
      ),
    ];
    final right = <Widget>[
      _TempleSection(d: d),
      _PrinciplesSection(d: d),
      _TogglesSection(
        title: 'Self-Reliance Classes Completed',
        items: _toggles(d['selfReliance']),
      ),
      _TagsSection(d: d),
    ];

    return LayoutBuilder(builder: (context, c) {
      if (c.maxWidth < 720) {
        return Column(children: [...left, ...right]);
      }
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: Column(children: left)),
        const SizedBox(width: 28),
        Expanded(child: Column(children: right)),
      ]);
    });
  }
}

// ---- sections -------------------------------------------------------------

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child, this.trailing});
  final String title;
  final Widget child;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Text(title,
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold)),
          ),
          if (trailing != null) trailing!,
        ]),
        const SizedBox(height: 10),
        child,
      ]),
    );
  }
}

class _SacramentSection extends StatelessWidget {
  const _SacramentSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final list = (d['sacrament'] as List?)?.cast<Map>() ?? const [];
    if (list.isEmpty) return const SizedBox.shrink();
    final missed = _missedCount(d, list);
    final green = Colors.green.shade700;
    return _Section(
      title: 'Attended Sacrament Meeting',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 14, runSpacing: 10, children: [
          for (final s in list)
            Column(children: [
              Text(s['label']?.toString() ?? '',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 4),
              Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: (s['attended'] == true) ? green : Colors.transparent,
                  border: Border.all(
                      color: (s['attended'] == true) ? green : Colors.grey.shade400,
                      width: 1.4),
                ),
                child: (s['attended'] == true)
                    ? const Icon(Icons.check, size: 16, color: Colors.white)
                    : null,
              ),
            ]),
        ]),
        if (missed > 0)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text('$missed sacrament meeting${missed == 1 ? '' : 's'} missed',
                style: TextStyle(color: Colors.red.shade700)),
          ),
      ]),
    );
  }

  int _missedCount(Map<String, dynamic> d, List list) {
    final msg = int.tryParse('${d['sacramentMissed'] ?? ''}');
    if (msg != null) return msg;
    return list.where((s) => s['attended'] != true).length;
  }
}

class _FriendsSection extends StatelessWidget {
  const _FriendsSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final friends = (d['friends'] as List?)?.cast<Map>() ?? const [];
    return _Section(
      title: 'Friends in the Church',
      child: friends.isEmpty
          ? _muted(context, 'No friends recorded yet.')
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (friends.any((f) => f['inStake'] == true))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('Inside the Stake',
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
                for (final f in friends)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      InitialsAvatar(name: f['name']?.toString() ?? '?', size: 30),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(f['name']?.toString() ?? '—'),
                              if ((f['unit']?.toString() ?? '').isNotEmpty)
                                Text(f['unit'].toString(),
                                    style: Theme.of(context).textTheme.bodySmall),
                            ]),
                      ),
                    ]),
                  ),
              ],
            ),
    );
  }
}

class _ListTextSection extends StatelessWidget {
  const _ListTextSection({
    required this.title,
    required this.lines,
    required this.emptyText,
    this.emptyIsAlert = false,
  });
  final String title;
  final List<String> lines;
  final String emptyText;
  final bool emptyIsAlert;
  @override
  Widget build(BuildContext context) {
    return _Section(
      title: title,
      child: lines.isEmpty
          ? Text(emptyText,
              style: TextStyle(
                  color: emptyIsAlert ? Colors.red.shade700 : Colors.grey.shade600))
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final l in lines)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(l),
                  ),
              ],
            ),
    );
  }
}

class _NamesSection extends StatelessWidget {
  const _NamesSection({required this.title, required this.names, required this.emptyText});
  final String title;
  final List<String> names;
  final String emptyText;
  @override
  Widget build(BuildContext context) {
    return _Section(
      title: title,
      child: names.isEmpty
          ? _muted(context, emptyText)
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final n in names)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      InitialsAvatar(name: n, size: 28),
                      const SizedBox(width: 10),
                      Expanded(child: Text(n)),
                    ]),
                  ),
              ],
            ),
    );
  }
}

class _TempleSection extends StatelessWidget {
  const _TempleSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final experiences = _toggles(d['templeExperiences']);
    final ordinances = _strings(d['templeOrdinances']);
    if (experiences.isEmpty && ordinances.isEmpty) return const SizedBox.shrink();
    return _Section(
      title: 'Temple Ordinances and Experiences',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final t in experiences) _ToggleRow(label: t.$1, on: t.$2),
        if (ordinances.isNotEmpty) const SizedBox(height: 8),
        for (final o in ordinances)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Text(o),
          ),
      ]),
    );
  }
}

class _PrinciplesSection extends StatelessWidget {
  const _PrinciplesSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final lessons = (d['lessons'] as List?)?.cast<Map>() ?? const [];
    if (lessons.isEmpty) return const SizedBox.shrink();
    final green = Colors.green.shade700;
    return _Section(
      title: 'Principles Taught',
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.person, size: 16, color: green),
        const SizedBox(width: 4),
        Text('= Member Present', style: Theme.of(context).textTheme.bodySmall),
      ]),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final l in lessons)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(l['name']?.toString() ?? '',
                    style: TextStyle(color: green, fontWeight: FontWeight.w500)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final p in (l['principles'] as List?)?.cast<Map>() ?? const [])
                    _PrincipleDot(
                      taught: _taught(p['taughtLevel']),
                      memberPresent: p['memberPresent'] == true,
                      tooltip: p['name']?.toString() ?? '',
                    ),
                ]),
              ]),
            ),
        ],
      ),
    );
  }

  static bool _taught(dynamic level) {
    if (level == null) return false;
    final s = level.toString();
    return s.isNotEmpty && s != '0' && s != '0.0';
  }
}

class _PrincipleDot extends StatelessWidget {
  const _PrincipleDot({required this.taught, required this.memberPresent, required this.tooltip});
  final bool taught;
  final bool memberPresent;
  final String tooltip;
  @override
  Widget build(BuildContext context) {
    final green = Colors.green.shade700;
    return Tooltip(
      message: '$tooltip — ${taught ? 'taught' : 'not yet'}'
          '${memberPresent ? ' (member present)' : ''}',
      child: Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: taught ? green : Colors.transparent,
          border: Border.all(color: green, width: 1.4),
        ),
        child: memberPresent
            ? Icon(Icons.person, size: 13, color: taught ? Colors.white : green)
            : null,
      ),
    );
  }
}

class _TogglesSection extends StatelessWidget {
  const _TogglesSection({required this.title, required this.items});
  final String title;
  final List<(String, bool)> items;
  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    return _Section(
      title: title,
      child: Column(children: [for (final t in items) _ToggleRow(label: t.$1, on: t.$2)]),
    );
  }
}

class _ToggleRow extends StatelessWidget {
  const _ToggleRow({required this.label, required this.on});
  final String label;
  final bool on;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(child: Text(label)),
        Icon(on ? Icons.check_circle : Icons.circle_outlined,
            size: 22, color: on ? Colors.green.shade700 : Colors.grey.shade400),
      ]),
    );
  }
}

class _TagsSection extends StatelessWidget {
  const _TagsSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final tags = _strings(d['tags']);
    if (tags.isEmpty) return const SizedBox.shrink();
    return _Section(
      title: 'Flags',
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        for (final t in tags)
          Chip(
            label: Text(t),
            backgroundColor: Colors.amber.shade100,
            visualDensity: VisualDensity.compact,
          ),
      ]),
    );
  }
}

/// Pre-`details` rows: the original flat field list, so the page still works.
class _FlatFallback extends StatelessWidget {
  const _FlatFallback({required this.member});
  final Map<String, dynamic> member;

  static const _fields = <(String, String)>[
    ('Unit', 'unit_name'),
    ('Baptism date', 'baptism_date'),
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
    return Column(children: [
      const SizedBox(height: 8),
      const Divider(),
      for (final f in _fields)
        ListTile(
          dense: true,
          title: Text(f.$1),
          trailing: Text('${member[f.$2] ?? '—'}',
              style: const TextStyle(fontWeight: FontWeight.w500)),
        ),
    ]);
  }
}

// ---- helpers --------------------------------------------------------------

List<String> _strings(dynamic v) =>
    (v as List?)?.map((e) => e.toString()).where((s) => s.isNotEmpty).toList() ?? [];

List<(String, bool)> _toggles(dynamic v) =>
    (v as List?)
        ?.cast<Map>()
        .map((e) => (e['name']?.toString() ?? '', e['done'] == true))
        .where((t) => t.$1.isNotEmpty)
        .toList() ??
    [];

Widget _muted(BuildContext context, String text) =>
    Text(text, style: TextStyle(color: Colors.grey.shade600));
