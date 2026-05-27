import 'package:flutter/material.dart';

import 'main.dart';

/// Reads `members` from Supabase — RLS returns ONLY what the signed-in user's calling
/// allows (whole stake for stake leaders, their unit for ward leaders). Two views:
///  • Golden Hour — at-a-glance integration milestones per new member (the chips).
///  • All data — every covenant-path field we have (the full spreadsheet).
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});
  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

// every covenant-path field we store; pulled in full so the "All data" view = spreadsheet.
const _columns =
    'name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, '
    'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, '
    'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance';

/// The Golden Hour milestones (label, field, "complete" predicate). Order = priority.
final _milestones = <(String, String, bool Function(Map<String, dynamic>))>[
  ('Friends', 'friends', (m) => m['friends'] == 'Yes'),
  ('Calling', 'calling', (m) => m['calling'] == 'Yes'),
  ('Has ministers', 'ministering_brothers_sisters', (m) => m['ministering_brothers_sisters'] == 'Yes'),
  ('Ministers', 'ministering_assignment', (m) => m['ministering_assignment'] == 'Yes'),
  ('Baptized', 'baptism_date', (m) => _has(m['baptism_date'])),
  ('Recommend', 'temple_recommend', (m) => m['temple_recommend'] == 'Active'),
  ('Patriarchal', 'patriarchal_blessing', (m) => m['patriarchal_blessing'] == 'Yes'),
  ('Endowed', 'living_ordinance', (m) => m['living_ordinance'] == 'Yes'),
];

bool _has(dynamic v) => v != null && v.toString().trim().isNotEmpty &&
    !{'N/A', 'No', 'needs-profile-api'}.contains(v.toString());

class _DashboardPageState extends State<DashboardPage> {
  late Future<List<Map<String, dynamic>>> _future;
  bool _goldenHour = true;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<Map<String, dynamic>>> _load() async {
    final rows = await supabase.from('members').select(_columns).order('unit_name').order('name');
    return (rows as List).cast<Map<String, dynamic>>();
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Covenant Path'),
        actions: [
          IconButton(onPressed: _refresh, icon: const Icon(Icons.refresh)),
          IconButton(
            onPressed: () => supabase.auth.signOut(),
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out (${supabase.auth.currentUser?.email ?? ''})',
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: SegmentedButton<bool>(
              segments: const [
                ButtonSegment(value: true, label: Text('Golden Hour'), icon: Icon(Icons.timelapse)),
                ButtonSegment(value: false, label: Text('All data'), icon: Icon(Icons.table_rows)),
              ],
              selected: {_goldenHour},
              onSelectionChanged: (s) => setState(() => _goldenHour = s.first),
            ),
          ),
        ),
      ),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Padding(padding: const EdgeInsets.all(24),
                child: Text('Could not load data:\n${snap.error}', textAlign: TextAlign.center)));
          }
          final rows = snap.data ?? [];
          if (rows.isEmpty) {
            return const Center(child: Padding(padding: EdgeInsets.all(24),
                child: Text('No members visible for your account.\n\nAccess is derived from '
                    'your LCR calling — sign in with the email your stake has on file.',
                    textAlign: TextAlign.center)));
          }
          return RefreshIndicator(
            onRefresh: _refresh,
            child: _goldenHour ? _GoldenHourView(rows: rows) : _AllDataView(rows: rows),
          );
        },
      ),
    );
  }
}

// ---- Golden Hour view: milestone chips per member + completion summary ----

class _GoldenHourView extends StatelessWidget {
  const _GoldenHourView({required this.rows});
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    final byUnit = <String, List<Map<String, dynamic>>>{};
    for (final r in rows) {
      (byUnit[(r['unit_name'] ?? '—').toString()] ??= []).add(r);
    }
    return ListView(
      children: [
        _CompletionSummary(rows: rows),
        for (final unit in byUnit.keys)
          ExpansionTile(
            title: Text(unit),
            subtitle: Text('${byUnit[unit]!.length} new members'),
            initiallyExpanded: byUnit.length <= 2,
            children: [for (final m in byUnit[unit]!) _MemberGoldenHourTile(m: m)],
          ),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _MemberGoldenHourTile extends StatelessWidget {
  const _MemberGoldenHourTile({required this.m});
  final Map<String, dynamic> m;

  @override
  Widget build(BuildContext context) {
    final done = _milestones.where((x) => x.$3(m)).length;
    return ListTile(
      title: Row(children: [
        Expanded(child: Text(m['name']?.toString() ?? '—')),
        Text('$done/${_milestones.length}', style: Theme.of(context).textTheme.labelMedium),
      ]),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Wrap(spacing: 6, runSpacing: 6, children: [
          for (final ms in _milestones) _MilestoneChip(label: ms.$1, complete: ms.$3(m)),
        ]),
      ),
    );
  }
}

class _MilestoneChip extends StatelessWidget {
  const _MilestoneChip({required this.label, required this.complete});
  final String label;
  final bool complete;
  @override
  Widget build(BuildContext context) {
    final c = complete ? Colors.green : Colors.grey;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.withOpacity(0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: c.withOpacity(0.4)),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(complete ? Icons.check_circle : Icons.radio_button_unchecked, size: 14, color: c),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(fontSize: 12, color: c.shade800)),
      ]),
    );
  }
}

class _CompletionSummary extends StatelessWidget {
  const _CompletionSummary({required this.rows});
  final List<Map<String, dynamic>> rows;
  @override
  Widget build(BuildContext context) {
    final n = rows.length;
    return Card(
      margin: const EdgeInsets.all(12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$n new members — Golden Hour completion',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 10),
          Wrap(spacing: 16, runSpacing: 10, children: [
            for (final ms in _milestones)
              _PctStat(label: ms.$1, pct: n == 0 ? 0 : rows.where(ms.$3).length / n),
          ]),
        ]),
      ),
    );
  }
}

class _PctStat extends StatelessWidget {
  const _PctStat({required this.label, required this.pct});
  final String label;
  final double pct;
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 92,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${(pct * 100).round()}%', style: Theme.of(context).textTheme.titleMedium),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 2),
        LinearProgressIndicator(value: pct, minHeight: 4),
      ]),
    );
  }
}

// ---- All-data view: every field (the spreadsheet) ----

class _AllDataView extends StatelessWidget {
  const _AllDataView({required this.rows});
  final List<Map<String, dynamic>> rows;

  static const _fields = <(String, String)>[
    ('Unit', 'unit_name'), ('Baptism', 'baptism_date'), ('Member for', 'membership_duration'),
    ('Birth', 'birth_date'), ('Friends', 'friends'), ('Aaronic', 'aaronic_priesthood'),
    ('Melchizedek', 'melchizedek_priesthood'), ('Calling', 'calling'),
    ('Ministers (has)', 'ministering_brothers_sisters'), ('Ministers (gives)', 'ministering_assignment'),
    ('Temple recommend', 'temple_recommend'), ('Patriarchal', 'patriarchal_blessing'),
    ('Living ordinance', 'living_ordinance'),
  ];

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      itemCount: rows.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final m = rows[i];
        return ExpansionTile(
          title: Text(m['name']?.toString() ?? '—'),
          subtitle: Text('${m['unit_name'] ?? ''}'),
          children: [
            for (final f in _fields)
              ListTile(
                dense: true,
                title: Text(f.$1),
                trailing: Text('${m[f.$2] ?? '—'}'),
              ),
          ],
        );
      },
    );
  }
}
