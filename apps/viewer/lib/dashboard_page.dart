import 'package:flutter/material.dart';

import 'main.dart';

/// Reads `members` from Supabase — RLS returns ONLY what the signed-in user's calling
/// allows (whole stake for stake leaders, their unit for ward leaders). The client
/// does no filtering; the database enforces scope.
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});
  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<Map<String, dynamic>>> _load() async {
    final rows = await supabase
        .from('members')
        .select('name, unit_name, baptism_date, birth_date, temple_recommend, '
            'patriarchal_blessing, ministering_assignment, calling, friends')
        .order('unit_name')
        .order('name');
    return (rows as List).cast<Map<String, dynamic>>();
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    final email = supabase.auth.currentUser?.email ?? '';
    return Scaffold(
      appBar: AppBar(
        title: const Text('Covenant Path'),
        actions: [
          IconButton(onPressed: _refresh, icon: const Icon(Icons.refresh)),
          IconButton(
            onPressed: () => supabase.auth.signOut(),
            icon: const Icon(Icons.logout),
            tooltip: 'Sign out ($email)',
          ),
        ],
      ),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return Center(child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text('Could not load data:\n${snap.error}', textAlign: TextAlign.center),
            ));
          }
          final rows = snap.data ?? [];
          if (rows.isEmpty) {
            return const Center(child: Padding(
              padding: EdgeInsets.all(24),
              child: Text('No members visible for your account.\n\nIf you hold a stake or '
                  'ward calling, your access is derived from it automatically — make sure '
                  'you signed in with the email your stake has on file.',
                  textAlign: TextAlign.center),
            ));
          }
          return RefreshIndicator(onRefresh: _refresh, child: _MemberList(rows: rows));
        },
      ),
    );
  }
}

class _MemberList extends StatelessWidget {
  const _MemberList({required this.rows});
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    // group by unit
    final byUnit = <String, List<Map<String, dynamic>>>{};
    for (final r in rows) {
      (byUnit[(r['unit_name'] ?? '—').toString()] ??= []).add(r);
    }
    final active = rows.where((r) => r['temple_recommend'] == 'Active').length;
    return ListView(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            _Stat('Members', '${rows.length}'),
            _Stat('Units', '${byUnit.length}'),
            _Stat('Active recommends', '$active'),
          ]),
        ),
        for (final unit in byUnit.keys)
          ExpansionTile(
            title: Text(unit),
            subtitle: Text('${byUnit[unit]!.length} members'),
            initiallyExpanded: byUnit.length <= 2,
            children: [
              for (final m in byUnit[unit]!)
                ListTile(
                  title: Text(m['name']?.toString() ?? '—'),
                  subtitle: Text([
                    if (m['baptism_date'] != null) 'Baptized ${m['baptism_date']}',
                    'Recommend: ${m['temple_recommend'] ?? '—'}',
                    'Patriarchal: ${m['patriarchal_blessing'] ?? '—'}',
                    'Ministering: ${m['ministering_assignment'] ?? '—'}',
                  ].join('  •  ')),
                  isThreeLine: true,
                ),
            ],
          ),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value);
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(value, style: Theme.of(context).textTheme.titleLarge),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
    );
  }
}
