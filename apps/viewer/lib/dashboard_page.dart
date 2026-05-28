import 'package:flutter/material.dart';

import 'admin_page.dart';
import 'golden_hour.dart';
import 'invite_page.dart';
import 'main.dart';
import 'person_detail_page.dart';

/// Reads `members` from Supabase — RLS returns ONLY what the signed-in user's calling
/// allows. Four tabs matching the reference iOS app (+ our spreadsheet):
///  • On Date     — new members grouped by baptismal date (or unit).
///  • Golden Hour — milestone chips, filtered by recency + grouped by unit/date.
///  • KPIs        — stake metrics (LCR dashboard) + new-member stats we compute.
///  • Table       — every covenant-path field in a scrollable grid.
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});
  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

const _columns =
    'name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, '
    'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, '
    'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance, details, photo_url';

class _DashboardPageState extends State<DashboardPage> {
  late Future<List<Map<String, dynamic>>> _future;
  int _tab = 1; // default to Golden Hour
  bool _isAdmin = false;

  @override
  void initState() {
    super.initState();
    _future = _load();
    _checkAdmin();
  }

  Future<void> _checkAdmin() async {
    try {
      final v = await supabase.rpc('is_admin');
      if (mounted && v == true) setState(() => _isAdmin = true);
    } catch (_) {
      // is_admin RPC missing or unreachable — just don't show the admin entry point.
    }
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
          if (_isAdmin)
            IconButton(
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute(builder: (_) => const AdminPage())),
              icon: const Icon(Icons.admin_panel_settings),
              tooltip: 'Admin · Ops console',
            ),
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
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.event), label: 'On Date'),
          NavigationDestination(icon: Icon(Icons.timelapse), label: 'Golden Hour'),
          NavigationDestination(icon: Icon(Icons.insights), label: 'KPIs'),
          NavigationDestination(icon: Icon(Icons.grid_on), label: 'Table'),
        ],
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
          if (rows.isEmpty && _tab != 2) {
            return const Center(child: Padding(padding: EdgeInsets.all(24),
                child: Text('No members visible for your account.\n\nAccess is derived from '
                    'your LCR calling — sign in with the email your stake has on file.',
                    textAlign: TextAlign.center)));
          }
          return RefreshIndicator(
            onRefresh: _refresh,
            child: switch (_tab) {
              0 => _OnDateView(rows: rows, onTap: _open),
              1 => _GoldenHourView(rows: rows, onTap: _open),
              2 => _KpiView(rows: rows),
              _ => _SpreadsheetView(rows: rows, onTap: _open),
            },
          );
        },
      ),
    );
  }
}

// ---- On Date: members grouped by baptismal date (or unit) ----

class _OnDateView extends StatefulWidget {
  const _OnDateView({required this.rows, required this.onTap});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onTap;
  @override
  State<_OnDateView> createState() => _OnDateViewState();
}

class _OnDateViewState extends State<_OnDateView> {
  bool _byDate = true;

  @override
  Widget build(BuildContext context) {
    final groups = _byDate
        ? _groupByDate(widget.rows)
        : _groupByUnit(widget.rows);
    return ListView(children: [
      Padding(
        padding: const EdgeInsets.all(12),
        child: SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: true, label: Text('By date'), icon: Icon(Icons.event)),
            ButtonSegment(value: false, label: Text('By unit'), icon: Icon(Icons.groups)),
          ],
          selected: {_byDate},
          onSelectionChanged: (s) => setState(() => _byDate = s.first),
        ),
      ),
      for (final g in groups)
        ExpansionTile(
          title: Text(g.$1),
          subtitle: Text('${g.$2.length} new member${g.$2.length == 1 ? '' : 's'}'),
          initiallyExpanded: groups.length <= 4,
          children: [for (final m in g.$2) _PersonRow(m: m, onTap: widget.onTap)],
        ),
      const SizedBox(height: 24),
    ]);
  }
}

// ---- Golden Hour: recency filter + group, milestone chips ----

enum _Window { week, month, year, all }

class _GoldenHourView extends StatefulWidget {
  const _GoldenHourView({required this.rows, required this.onTap});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onTap;
  @override
  State<_GoldenHourView> createState() => _GoldenHourViewState();
}

class _GoldenHourViewState extends State<_GoldenHourView> {
  _Window _window = _Window.all;
  bool _byUnit = true;

  bool _within(Map<String, dynamic> m) {
    if (_window == _Window.all) return true;
    final d = parseMemberDate(m['baptism_date']);
    if (d == null) return false;
    final days = DateTime.now().difference(d).inDays;
    return switch (_window) {
      _Window.week => days <= 7,
      _Window.month => days <= 31,
      _Window.year => days <= 366,
      _Window.all => true,
    };
  }

  @override
  Widget build(BuildContext context) {
    final rows = widget.rows.where(_within).toList();
    final groups = _byUnit ? _groupByUnit(rows) : _groupByDate(rows);
    return ListView(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
        child: Column(children: [
          SegmentedButton<_Window>(
            segments: const [
              ButtonSegment(value: _Window.week, label: Text('Week')),
              ButtonSegment(value: _Window.month, label: Text('Month')),
              ButtonSegment(value: _Window.year, label: Text('Year')),
              ButtonSegment(value: _Window.all, label: Text('All')),
            ],
            selected: {_window},
            onSelectionChanged: (s) => setState(() => _window = s.first),
          ),
          const SizedBox(height: 8),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: true, label: Text('By unit'), icon: Icon(Icons.groups)),
              ButtonSegment(value: false, label: Text('By date'), icon: Icon(Icons.event)),
            ],
            selected: {_byUnit},
            onSelectionChanged: (s) => setState(() => _byUnit = s.first),
          ),
        ]),
      ),
      _CompletionSummary(rows: rows),
      if (rows.isEmpty)
        const Padding(padding: EdgeInsets.all(24),
            child: Center(child: Text('No new members in this window.'))),
      for (final g in groups)
        ExpansionTile(
          title: Text(g.$1),
          subtitle: Text('${g.$2.length} new members'),
          initiallyExpanded: groups.length <= 2,
          children: [for (final m in g.$2) _PersonRow(m: m, onTap: widget.onTap)],
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
      leading: PhotoAvatar(name: m['name']?.toString() ?? '?', photoUrl: m['photo_url']?.toString()),
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

// ---- KPIs: stake metrics (LCR dashboard) + new-member stats we compute ----

class _KpiView extends StatefulWidget {
  const _KpiView({required this.rows});
  final List<Map<String, dynamic>> rows;
  @override
  State<_KpiView> createState() => _KpiViewState();
}

class _KpiViewState extends State<_KpiView> {
  late Future<Map<String, dynamic>?> _kpis;

  @override
  void initState() {
    super.initState();
    _kpis = _loadKpis();
  }

  Future<Map<String, dynamic>?> _loadKpis() async {
    final rows = await supabase.from('stakes').select('name, kpis, kpis_updated_at');
    final list = (rows as List).cast<Map<String, dynamic>>();
    // RLS returns only the user's stake(s); take the first that has KPIs.
    for (final s in list) {
      if (s['kpis'] is Map) return s;
    }
    return list.isNotEmpty ? list.first : null;
  }

  @override
  Widget build(BuildContext context) {
    final members = widget.rows;
    return FutureBuilder<Map<String, dynamic>?>(
      future: _kpis,
      builder: (context, snap) {
        final stake = snap.data;
        final kpis = (stake?['kpis'] as Map?)?.cast<String, dynamic>();
        final memberStats = _memberKpis(members);
        return ListView(padding: const EdgeInsets.all(12), children: [
          // headline stat cards
          Wrap(spacing: 10, runSpacing: 10, children: [
            if (kpis?['newMemberCount'] != null)
              _StatCard(label: 'New members', value: '${kpis!['newMemberCount']}', icon: Icons.person_add),
            if (kpis?['peopleBeingTaught'] != null)
              _StatCard(label: 'People being taught', value: '${kpis!['peopleBeingTaught']}', icon: Icons.menu_book),
            _StatCard(label: 'Tracked here', value: '${members.length}', icon: Icons.people),
            _StatCard(
                label: 'At last sacrament',
                value: memberStats.sacramentSamples == 0 ? '—' : '${(memberStats.attendedLastPct * 100).round()}%',
                icon: Icons.event_available),
          ]),
          const SizedBox(height: 8),

          if (kpis != null) ...[
            _KpiCard(
              title: 'Sacrament attendance (stake)',
              child: _MonthTrend(months: (kpis['sacramentByMonth'] as List?)?.cast<Map>() ?? const []),
            ),
            _RecommendCard(kpis: kpis),
            _MinisteringCard(kpis: kpis),
            if (stake?['kpis_updated_at'] != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text('Stake KPIs as of ${_ago(stake!['kpis_updated_at'])}',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
          ] else
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Text(snap.connectionState == ConnectionState.waiting
                    ? 'Loading stake KPIs…'
                    : 'Stake-level KPIs populate on the next sync (or via the admin Rescrape).'),
              ),
            ),

          // new-member integration metrics, computed from the members you can see
          _KpiCard(
            title: 'New-member milestone completion',
            child: Column(children: [
              for (final s in memberStats.milestonePct)
                _BarRow(label: s.$1, fraction: s.$2, trailing: '${(s.$2 * 100).round()}%'),
            ]),
          ),
          const SizedBox(height: 24),
        ]);
      },
    );
  }
}

class _MemberKpis {
  _MemberKpis(this.attendedLastPct, this.sacramentSamples, this.milestonePct);
  final double attendedLastPct;
  final int sacramentSamples;
  final List<(String, double)> milestonePct;
}

_MemberKpis _memberKpis(List<Map<String, dynamic>> members) {
  var attendedLast = 0, samples = 0;
  for (final m in members) {
    final d = m['details'];
    final sacr = (d is Map ? d['sacrament'] : null) as List?;
    if (sacr != null && sacr.isNotEmpty) {
      samples++;
      if (sacr.first is Map && (sacr.first as Map)['attended'] == true) attendedLast++;
    }
  }
  final n = members.length;
  final milestonePct = <(String, double)>[
    for (final ms in milestones)
      (ms.label, n == 0 ? 0.0 : members.where(ms.complete).length / n),
  ];
  return _MemberKpis(samples == 0 ? 0 : attendedLast / samples, samples, milestonePct);
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.label, required this.value, required this.icon});
  final String label;
  final String value;
  final IconData icon;
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 168,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            Icon(icon, color: Colors.indigo.shade400),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                Text(label, style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

class _KpiCard extends StatelessWidget {
  const _KpiCard({required this.title, required this.child});
  final String title;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),
          child,
        ]),
      ),
    );
  }
}

class _RecommendCard extends StatelessWidget {
  const _RecommendCard({required this.kpis});
  final Map<String, dynamic> kpis;
  @override
  Widget build(BuildContext context) {
    final r = (kpis['templeRecommend'] as Map?)?.cast<String, dynamic>() ?? const {};
    if (r.isEmpty) return const SizedBox.shrink();
    return _KpiCard(title: 'Temple recommends (stake)', child: Column(children: [
      _BarRow(label: 'Endowed with recommend', fraction: _frac(r['endowedActual'], r['endowedTotal']),
          trailing: '${r['endowedActual'] ?? '—'} / ${r['endowedTotal'] ?? '—'}'),
      _BarRow(label: 'Youth with recommend', fraction: _frac(r['youthActual'], r['youthTotal']),
          trailing: '${r['youthActual'] ?? '—'} / ${r['youthTotal'] ?? '—'}'),
    ]));
  }
}

class _MinisteringCard extends StatelessWidget {
  const _MinisteringCard({required this.kpis});
  final Map<String, dynamic> kpis;
  @override
  Widget build(BuildContext context) {
    final m = (kpis['ministering'] as Map?)?.cast<String, dynamic>() ?? const {};
    if (m.isEmpty) return const SizedBox.shrink();
    return _KpiCard(title: 'Ministering interviews (stake)', child: Column(children: [
      _BarRow(label: 'Brother companionships', fraction: _frac(m['brotherInterviewed'], m['brotherTotal']),
          trailing: '${m['brotherInterviewed'] ?? '—'} / ${m['brotherTotal'] ?? '—'}'),
      _BarRow(label: 'Sister companionships', fraction: _frac(m['sisterInterviewed'], m['sisterTotal']),
          trailing: '${m['sisterInterviewed'] ?? '—'} / ${m['sisterTotal'] ?? '—'}'),
    ]));
  }
}

class _BarRow extends StatelessWidget {
  const _BarRow({required this.label, required this.fraction, required this.trailing});
  final String label;
  final double fraction;
  final String trailing;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(label)),
          Text(trailing, style: const TextStyle(fontWeight: FontWeight.w500)),
        ]),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(value: fraction.clamp(0, 1), minHeight: 8),
        ),
      ]),
    );
  }
}

/// Vertical bars of monthly attended/potential.
class _MonthTrend extends StatelessWidget {
  const _MonthTrend({required this.months});
  final List<Map> months;
  @override
  Widget build(BuildContext context) {
    if (months.isEmpty) return const Text('No attendance data.');
    return SizedBox(
      height: 140,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          for (final m in months)
            _Bar(
              label: '${m['month'] ?? ''}',
              attended: (m['attended'] as num?)?.toDouble() ?? 0,
              potential: (m['potential'] as num?)?.toDouble() ?? 0,
            ),
        ],
      ),
    );
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.label, required this.attended, required this.potential});
  final String label;
  final double attended;
  final double potential;
  @override
  Widget build(BuildContext context) {
    final pct = potential == 0 ? 0.0 : (attended / potential).clamp(0.0, 1.0);
    return Expanded(
      child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
        Text('${(pct * 100).round()}%', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 2),
        Container(
          margin: const EdgeInsets.symmetric(horizontal: 6),
          height: 80 * pct + 2,
          decoration: BoxDecoration(
            color: Colors.indigo.shade400,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
          ),
        ),
        const SizedBox(height: 4),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
      ]),
    );
  }
}

// ---- Table: every field, scrollable grid ----

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

// ---- grouping + date helpers ----

/// Groups by baptismal date, newest first; undated members last.
List<(String, List<Map<String, dynamic>>)> _groupByDate(List<Map<String, dynamic>> rows) {
  final byKey = <String, List<Map<String, dynamic>>>{};
  final dateOf = <String, DateTime?>{};
  for (final m in rows) {
    final d = parseMemberDate(m['baptism_date']);
    final key = d == null ? 'No baptism date' : fmtDate(d);
    (byKey[key] ??= []).add(m);
    dateOf[key] = d;
  }
  final keys = byKey.keys.toList()
    ..sort((a, b) {
      final da = dateOf[a], db = dateOf[b];
      if (da == null) return 1;
      if (db == null) return -1;
      return db.compareTo(da);
    });
  return [for (final k in keys) (k, byKey[k]!)];
}

List<(String, List<Map<String, dynamic>>)> _groupByUnit(List<Map<String, dynamic>> rows) {
  final byKey = <String, List<Map<String, dynamic>>>{};
  for (final m in rows) {
    (byKey[(m['unit_name'] ?? '—').toString()] ??= []).add(m);
  }
  final keys = byKey.keys.toList()..sort();
  return [for (final k in keys) (k, byKey[k]!)];
}

const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

/// Parses the date strings LCR emits: "6 Feb 2026", "06 Feb 2026", ISO, or "MM/dd/yy".
DateTime? parseMemberDate(dynamic v) {
  if (v == null) return null;
  final s = v.toString().trim();
  if (s.isEmpty || s == 'N/A' || s == 'needs-profile-api') return null;
  final iso = DateTime.tryParse(s);
  if (iso != null) return iso;
  final m = RegExp(r'^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$').firstMatch(s);
  if (m != null) {
    final mo = _months.indexWhere((x) => x.toLowerCase() == m.group(2)!.toLowerCase().substring(0, 3));
    if (mo >= 0) return DateTime(int.parse(m.group(3)!), mo + 1, int.parse(m.group(1)!));
  }
  final m2 = RegExp(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$').firstMatch(s);
  if (m2 != null) {
    var y = int.parse(m2.group(3)!);
    if (y < 100) y += 2000;
    return DateTime(y, int.parse(m2.group(1)!), int.parse(m2.group(2)!));
  }
  return null;
}

String fmtDate(DateTime d) => '${d.day} ${_months[d.month - 1]} ${d.year}';

double _frac(dynamic a, dynamic b) {
  final an = (a as num?)?.toDouble() ?? 0;
  final bn = (b as num?)?.toDouble() ?? 0;
  return bn == 0 ? 0 : an / bn;
}

String _ago(dynamic iso) {
  final t = DateTime.tryParse('${iso ?? ''}');
  if (t == null) return '$iso';
  final diff = DateTime.now().toUtc().difference(t.toUtc());
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}
