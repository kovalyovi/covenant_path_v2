import 'package:flutter/material.dart';

import 'golden_hour.dart';
import 'invite_page.dart';
import 'main.dart';
import 'person_detail_page.dart';

/// Reads `members` from Supabase — RLS returns ONLY what the signed-in user's calling
/// allows. Two views, matching (and extending) the reference iOS app:
///  • Golden Hour — person rows (avatar + milestone circle-chips) grouped by ward + stats.
///  • Spreadsheet — every covenant-path field in a scrollable table (the full sheet).
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});
  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

const _columns =
    'name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, '
    'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, '
    'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance';

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

  void _open(Map<String, dynamic> m) => Navigator.of(context)
      .push(MaterialPageRoute(builder: (_) => PersonDetailPage(member: m)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Covenant Path'),
        actions: [
          IconButton(
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute(builder: (_) => const InvitePage())),
            icon: const Icon(Icons.person_add_alt),
            tooltip: 'Invite a power user',
          ),
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
                ButtonSegment(value: false, label: Text('Spreadsheet'), icon: Icon(Icons.grid_on)),
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
            child: _goldenHour
                ? _GoldenHourView(rows: rows, onTap: _open)
                : _SpreadsheetView(rows: rows, onTap: _open),
          );
        },
      ),
    );
  }
}

// ---- Golden Hour: stats + ward groups + person rows (avatar + chips) ----

class _GoldenHourView extends StatelessWidget {
  const _GoldenHourView({required this.rows, required this.onTap});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onTap;

  @override
  Widget build(BuildContext context) {
    final byUnit = <String, List<Map<String, dynamic>>>{};
    for (final r in rows) {
      (byUnit[(r['unit_name'] ?? '—').toString()] ??= []).add(r);
    }
    return ListView(children: [
      _CompletionSummary(rows: rows),
      for (final unit in byUnit.keys)
        ExpansionTile(
          title: Text(unit),
          subtitle: Text('${byUnit[unit]!.length} new members'),
          initiallyExpanded: byUnit.length <= 2,
          children: [for (final m in byUnit[unit]!) _PersonRow(m: m, onTap: onTap)],
        ),
      const SizedBox(height: 24),
    ]);
  }
}

class _PersonRow extends StatelessWidget {
  const _PersonRow({required this.m, required this.onTap});
  final Map<String, dynamic> m;
  final void Function(Map<String, dynamic>) onTap;

  @override
  Widget build(BuildContext context) {
    final done = milestonesFor(m).where((x) => x.complete(m)).length;
    final total = milestonesFor(m).length;
    final baptism = m['baptism_date'];
    return ListTile(
      onTap: () => onTap(m),
      leading: InitialsAvatar(name: m['name']?.toString() ?? '?'),
      title: Row(children: [
        Expanded(child: Text(m['name']?.toString() ?? '—')),
        Text('$done/$total', style: Theme.of(context).textTheme.labelMedium),
      ]),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (baptism != null && baptism.toString().isNotEmpty)
          Text('Baptized $baptism', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 4),
        GoldenHourChips(member: m),
      ]),
      isThreeLine: true,
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
            for (final ms in milestones)
              _PctStat(label: ms.abbr, full: ms.label, pct: n == 0 ? 0 : rows.where(ms.complete).length / n),
          ]),
        ]),
      ),
    );
  }
}

class _PctStat extends StatelessWidget {
  const _PctStat({required this.label, required this.full, required this.pct});
  final String label;
  final String full;
  final double pct;
  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: full,
      child: SizedBox(
        width: 88,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${(pct * 100).round()}%', style: Theme.of(context).textTheme.titleMedium),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 2),
          LinearProgressIndicator(value: pct, minHeight: 4),
        ]),
      ),
    );
  }
}

// ---- Spreadsheet: every field, scrollable table (the full sheet) ----

class _SpreadsheetView extends StatelessWidget {
  const _SpreadsheetView({required this.rows, required this.onTap});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onTap;

  static const _cols = <(String, String)>[
    ('Member', 'name'), ('Unit', 'unit_name'), ('Baptism', 'baptism_date'),
    ('Member for', 'membership_duration'), ('Birth', 'birth_date'), ('Friends', 'friends'),
    ('Aaronic', 'aaronic_priesthood'), ('Melch.', 'melchizedek_priesthood'), ('Calling', 'calling'),
    ('Min. (has)', 'ministering_brothers_sisters'), ('Min. (gives)', 'ministering_assignment'),
    ('Recommend', 'temple_recommend'), ('Patriarchal', 'patriarchal_blessing'),
    ('Living ord.', 'living_ordinance'),
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.vertical,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          headingRowHeight: 40,
          dataRowMinHeight: 38,
          dataRowMaxHeight: 46,
          columns: [for (final c in _cols) DataColumn(label: Text(c.$1))],
          rows: [
            for (final m in rows)
              DataRow(
                onSelectChanged: (_) => onTap(m),
                cells: [for (final c in _cols) DataCell(Text('${m[c.$2] ?? ''}'))],
              ),
          ],
        ),
      ),
    );
  }
}
