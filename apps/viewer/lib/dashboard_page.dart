import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'admin_page.dart';
import 'golden_hour.dart';
import 'invite_page.dart';
import 'main.dart';
import 'person_detail_page.dart';

/// RLS-scoped dashboard. Four tabs mirroring the reference iOS app (+ our spreadsheet):
///  • On Date     — members with a baptismal date, grouped by unit or sorted by date.
///  • Golden Hour — integration milestones, recency-filtered, by unit or by date.
///  • KPIs        — stake metrics as line-chart cards.
///  • Table       — every covenant-path field, color-coded like the master sheet.
///
/// Responsive: bottom nav on phones; a side NavigationRail + multi-column cards on
/// tablet/desktop so the browser feels like a real app, not a stretched phone.
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});
  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

const _columns =
    'name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, '
    'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, '
    'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance, details, photo_url';

const _tabs = [
  (icon: Icons.event, label: 'On Date'),
  (icon: Icons.timelapse, label: 'Golden Hour'),
  (icon: Icons.insights, label: 'KPIs'),
  (icon: Icons.grid_on, label: 'Table'),
];

class _DashboardPageState extends State<DashboardPage> {
  late Future<List<Map<String, dynamic>>> _future;
  int _tab = 0;
  bool _isAdmin = false;
  String? _stakeName;

  @override
  void initState() {
    super.initState();
    _future = _load();
    _checkAdmin();
    _loadStakeName();
  }

  Future<void> _checkAdmin() async {
    try {
      if (await supabase.rpc('is_admin') == true && mounted) setState(() => _isAdmin = true);
    } catch (_) {}
  }

  Future<void> _loadStakeName() async {
    try {
      final rows = await supabase.from('stakes').select('name').limit(1);
      if ((rows as List).isNotEmpty && mounted) setState(() => _stakeName = rows.first['name']);
    } catch (_) {}
  }

  Future<List<Map<String, dynamic>>> _load() async {
    final rows = await supabase.from('members').select(_columns).order('unit_name').order('name');
    return (rows as List).cast<Map<String, dynamic>>();
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
  }

  void _open(Map<String, dynamic> m) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => PersonDetailPage(member: m)));

  List<Widget> _appBarActions() => [
        if (_isAdmin)
          IconButton(
            tooltip: 'Admin · Ops console',
            onPressed: () =>
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AdminPage())),
            icon: const Icon(Icons.admin_panel_settings),
          ),
        IconButton(
          tooltip: 'Invite a power user',
          onPressed: () =>
              Navigator.of(context).push(MaterialPageRoute(builder: (_) => const InvitePage())),
          icon: const Icon(Icons.person_add_alt),
        ),
        IconButton(tooltip: 'Refresh', onPressed: _refresh, icon: const Icon(Icons.refresh)),
        IconButton(
          tooltip: 'Sign out (${supabase.auth.currentUser?.email ?? ''})',
          onPressed: () => supabase.auth.signOut(),
          icon: const Icon(Icons.logout),
        ),
      ];

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final tier = tierFor(c.maxWidth);
      final appBar = AppBar(title: Text(_stakeName ?? 'Covenant Path'), actions: _appBarActions());
      final body = _Body(tab: _tab, tier: tier, future: _future, onRefresh: _refresh, onOpen: _open);

      if (tier == ScreenTier.mobile) {
        return Scaffold(
          appBar: appBar,
          body: body,
          bottomNavigationBar: NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: [
              for (final t in _tabs) NavigationDestination(icon: Icon(t.icon), label: t.label),
            ],
          ),
        );
      }
      // tablet / desktop: side rail (no full-width bottom bar), app-like.
      return Scaffold(
        appBar: appBar,
        body: Row(children: [
          NavigationRail(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            extended: tier == ScreenTier.desktop,
            labelType: tier == ScreenTier.desktop ? null : NavigationRailLabelType.all,
            destinations: [
              for (final t in _tabs)
                NavigationRailDestination(icon: Icon(t.icon), label: Text(t.label)),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: body),
        ]),
      );
    });
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.tab, required this.tier, required this.future,
      required this.onRefresh, required this.onOpen});
  final int tab;
  final ScreenTier tier;
  final Future<List<Map<String, dynamic>>> future;
  final Future<void> Function() onRefresh;
  final void Function(Map<String, dynamic>) onOpen;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Center(child: Padding(padding: const EdgeInsets.all(24),
              child: Text('Could not load data:\n${snap.error}', textAlign: TextAlign.center)));
        }
        final rows = snap.data ?? [];
        if (rows.isEmpty && tab != 2) {
          return const Center(child: Padding(padding: EdgeInsets.all(24),
              child: Text('No members visible for your account.\n\nAccess is derived from your '
                  'LCR calling — sign in with the email your stake has on file.',
                  textAlign: TextAlign.center)));
        }
        final view = switch (tab) {
          0 => _OnDateView(rows: rows, tier: tier, onOpen: onOpen),
          1 => _GoldenHourView(rows: rows, tier: tier, onOpen: onOpen),
          2 => _KpiView(rows: rows, tier: tier),
          _ => _SpreadsheetView(rows: rows, onOpen: onOpen),
        };
        return RefreshIndicator(onRefresh: onRefresh, child: view);
      },
    );
  }
}

// ---- On Date ----------------------------------------------------------------

class _OnDateView extends StatefulWidget {
  const _OnDateView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_OnDateView> createState() => _OnDateViewState();
}

class _OnDateViewState extends State<_OnDateView> {
  bool _byDate = false;

  @override
  Widget build(BuildContext context) {
    final dated = widget.rows.where((m) => parseMemberDate(m['baptism_date']) != null).toList();
    return _Page(
      tier: widget.tier,
      header: _SectionTitle(title: 'Has Baptismal Date', count: dated.length, byDate: _byDate,
          onToggle: (v) => setState(() => _byDate = v)),
      child: _byDate
          ? _DateList(rows: dated, tier: widget.tier, onOpen: widget.onOpen, chips: false)
          : _UnitGrid(rows: dated, tier: widget.tier, onOpen: widget.onOpen, chips: false),
    );
  }
}

// ---- Golden Hour ------------------------------------------------------------

enum _Window { week, month, year, all }

class _GoldenHourView extends StatefulWidget {
  const _GoldenHourView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_GoldenHourView> createState() => _GoldenHourViewState();
}

class _GoldenHourViewState extends State<_GoldenHourView> {
  _Window _window = _Window.all;
  bool _byDate = false;

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
    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Center(
          child: SegmentedButton<_Window>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: _Window.week, label: Text('Week')),
              ButtonSegment(value: _Window.month, label: Text('Month')),
              ButtonSegment(value: _Window.year, label: Text('Year')),
              ButtonSegment(value: _Window.all, label: Text('All')),
            ],
            selected: {_window},
            onSelectionChanged: (s) => setState(() => _window = s.first),
          ),
        ),
        const SizedBox(height: 8),
        _SectionTitle(title: 'Recently Baptized', count: rows.length, byDate: _byDate,
            onToggle: (v) => setState(() => _byDate = v)),
        _CompletionCard(rows: rows),
      ]),
      child: rows.isEmpty
          ? const Padding(padding: EdgeInsets.all(32),
              child: Center(child: Text('No new members in this window.')))
          : (_byDate
              ? _DateList(rows: rows, tier: widget.tier, onOpen: widget.onOpen, chips: true)
              : _UnitGrid(rows: rows, tier: widget.tier, onOpen: widget.onOpen, chips: true)),
    );
  }
}

class _CompletionCard extends StatelessWidget {
  const _CompletionCard({required this.rows});
  final List<Map<String, dynamic>> rows;
  @override
  Widget build(BuildContext context) {
    final n = rows.length;
    if (n == 0) return const SizedBox.shrink();
    return SectionCard(
      title: 'Golden Hour completion',
      child: Wrap(spacing: 18, runSpacing: 12, children: [
        for (final ms in milestones)
          _PctStat(label: ms.label, pct: rows.where(ms.complete).length / n),
      ]),
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
      width: 120,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${(pct * 100).round()}%', style: Theme.of(context).textTheme.titleLarge),
        Text(label, style: Theme.of(context).textTheme.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
        const SizedBox(height: 4),
        ClipRRect(borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: pct, minHeight: 5)),
      ]),
    );
  }
}

// ---- shared list layouts ----------------------------------------------------

/// Cards grouped by unit (unit name as the card title) — laid out in 1/2/3 columns by tier.
class _UnitGrid extends StatelessWidget {
  const _UnitGrid({required this.rows, required this.tier, required this.onOpen, required this.chips});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;

  @override
  Widget build(BuildContext context) {
    final groups = _groupByUnit(rows);
    final cards = [
      for (final g in groups)
        SectionCard(
          title: g.$1,
          trailing: _CountBadge(g.$2.length),
          child: Column(children: [
            for (var i = 0; i < g.$2.length; i++) ...[
              if (i > 0) const Divider(height: 1),
              _MemberRow(m: g.$2[i], onOpen: onOpen, chips: chips),
            ],
          ]),
        ),
    ];
    return _Columns(cols: _cols(tier), children: cards);
  }
}

/// Flat list sorted by date (newest first); the unit is shown as right-side metadata.
class _DateList extends StatelessWidget {
  const _DateList({required this.rows, required this.tier, required this.onOpen, required this.chips});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;

  @override
  Widget build(BuildContext context) {
    final sorted = [...rows]..sort((a, b) {
        final da = parseMemberDate(a['baptism_date']), db = parseMemberDate(b['baptism_date']);
        if (da == null) return 1;
        if (db == null) return -1;
        return db.compareTo(da);
      });
    final card = SectionCard(
      title: 'By date',
      child: Column(children: [
        for (var i = 0; i < sorted.length; i++) ...[
          if (i > 0) const Divider(height: 1),
          _MemberRow(m: sorted[i], onOpen: onOpen, chips: chips, showUnit: true),
        ],
      ]),
    );
    // a flat list reads best in a single capped column even on wide screens
    return _Columns(cols: 1, children: [card]);
  }
}

class _MemberRow extends StatelessWidget {
  const _MemberRow({required this.m, required this.onOpen, this.chips = false, this.showUnit = false});
  final Map<String, dynamic> m;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final bool showUnit;

  @override
  Widget build(BuildContext context) {
    final name = m['name']?.toString() ?? '—';
    final date = parseMemberDate(m['baptism_date']);
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      onTap: () => onOpen(m),
      leading: PhotoAvatar(name: name, photoUrl: m['photo_url']?.toString(), size: 44),
      title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (date != null)
          Text(fmtLong(date), style: Theme.of(context).textTheme.bodySmall),
        if (chips) ...[const SizedBox(height: 6), GoldenHourChips(member: m, size: 22)],
      ]),
      trailing: showUnit
          ? SizedBox(
              width: 130,
              child: Text(m['unit_name']?.toString() ?? '',
                  textAlign: TextAlign.right,
                  style: TextStyle(color: Colors.grey.shade600, fontSize: 12)))
          : const Icon(Icons.chevron_right),
      isThreeLine: chips,
    );
  }
}

// ---- KPIs (line-chart cards) ------------------------------------------------

class _KpiView extends StatefulWidget {
  const _KpiView({required this.rows, required this.tier});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  @override
  State<_KpiView> createState() => _KpiViewState();
}

class _KpiViewState extends State<_KpiView> {
  late Future<Map<String, dynamic>?> _kpis;

  @override
  void initState() {
    super.initState();
    _kpis = _load();
  }

  Future<Map<String, dynamic>?> _load() async {
    final rows = await supabase.from('stakes').select('name, kpis, kpis_updated_at');
    final list = (rows as List).cast<Map<String, dynamic>>();
    for (final s in list) {
      if (s['kpis'] is Map) return s;
    }
    return list.isNotEmpty ? list.first : null;
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>?>(
      future: _kpis,
      builder: (context, snap) {
        final stake = snap.data;
        final kpis = (stake?['kpis'] as Map?)?.cast<String, dynamic>();
        final sacrament = _weeklySacrament(widget.rows); // (labels, attended counts)
        final members = widget.rows.length;
        final taught = kpis?['peopleBeingTaught'];
        final newMembers = kpis?['newMemberCount'];
        final completion = _avgCompletion(widget.rows);

        final cards = <Widget>[
          if (sacrament.$1.isNotEmpty)
            _LineCard(
              title: 'New Members at Sacrament',
              icon: Icons.favorite,
              color: Colors.redAccent.shade200,
              labels: sacrament.$1,
              values: sacrament.$2,
              suffix: 'attended (last ${sacrament.$1.length} weeks)',
            ),
          if (kpis?['sacramentByMonth'] is List && (kpis!['sacramentByMonth'] as List).isNotEmpty)
            _LineCard(
              title: 'Sacrament Attendance (stake)',
              icon: Icons.groups,
              color: Colors.indigo.shade400,
              labels: [for (final m in kpis['sacramentByMonth']) '${m['month']}'],
              values: [for (final m in kpis['sacramentByMonth']) ((m['attended'] as num?) ?? 0).toDouble()],
              suffix: 'attended per month',
            ),
          _StatGridCard(items: [
            if (newMembers != null) ('New members', '$newMembers'),
            if (taught != null) ('Being taught', '$taught'),
            ('Tracked here', '$members'),
            ('Golden Hour', '${(completion * 100).round()}%'),
          ]),
          if (kpis != null) _RecommendCard(kpis: kpis),
          if (kpis != null) _MinisteringCard(kpis: kpis),
        ];

        return _Page(
          tier: widget.tier,
          header: _BigHeader(text: 'KPIs', subtitle: stake?['kpis_updated_at'] != null
              ? 'Stake metrics · updated ${_ago(stake!['kpis_updated_at'])}'
              : 'Stake metrics'),
          child: kpis == null && snap.connectionState == ConnectionState.waiting
              ? const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
              : _Columns(cols: _cols(widget.tier).clamp(1, 2), children: cards),
        );
      },
    );
  }
}

class _LineCard extends StatelessWidget {
  const _LineCard({required this.title, required this.icon, required this.color,
      required this.labels, required this.values, required this.suffix});
  final String title;
  final IconData icon;
  final Color color;
  final List<String> labels;
  final List<double> values;
  final String suffix;

  @override
  Widget build(BuildContext context) {
    final last = values.isNotEmpty ? values.last : null;
    final prev = values.length >= 2 ? values[values.length - 2] : null;
    final delta = (last != null && prev != null) ? (last - prev) : null;
    return SectionCard(
      title: title,
      leadingIcon: icon,
      trailing: delta == null
          ? null
          : _DeltaBadge(delta: delta),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (prev != null) _bigNum(context, 'prior', prev),
          if (prev != null) const SizedBox(width: 28),
          if (last != null) _bigNum(context, 'latest', last),
        ]),
        const SizedBox(height: 12),
        SizedBox(height: 150, child: _Line(values: values, labels: labels, color: color)),
        const SizedBox(height: 4),
        Text(suffix, style: Theme.of(context).textTheme.bodySmall),
      ]),
    );
  }

  Widget _bigNum(BuildContext context, String label, double v) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.bodySmall),
          Text(v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(1),
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
        ],
      );
}

class _Line extends StatelessWidget {
  const _Line({required this.values, required this.labels, required this.color});
  final List<double> values;
  final List<String> labels;
  final Color color;
  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) return const Center(child: Text('No data'));
    final maxY = (values.reduce((a, b) => a > b ? a : b)) * 1.25 + 1;
    return LineChart(LineChartData(
      minY: 0,
      maxY: maxY,
      gridData: const FlGridData(show: false),
      borderData: FlBorderData(show: false),
      lineTouchData: const LineTouchData(enabled: false),
      titlesData: FlTitlesData(
        leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: 1,
            getTitlesWidget: (x, meta) {
              final i = x.toInt();
              if (i < 0 || i >= labels.length) return const SizedBox.shrink();
              // thin out labels if many points
              if (labels.length > 6 && i % 2 != 0) return const SizedBox.shrink();
              return Padding(padding: const EdgeInsets.only(top: 6),
                  child: Text(labels[i], style: const TextStyle(fontSize: 10)));
            },
          ),
        ),
      ),
      lineBarsData: [
        LineChartBarData(
          spots: [for (var i = 0; i < values.length; i++) FlSpot(i.toDouble(), values[i])],
          isCurved: true,
          curveSmoothness: 0.3,
          color: color,
          barWidth: 3,
          dotData: FlDotData(show: values.length <= 12),
          belowBarData: BarAreaData(show: true, color: color.withValues(alpha: 0.12)),
        ),
      ],
    ));
  }
}

class _DeltaBadge extends StatelessWidget {
  const _DeltaBadge({required this.delta});
  final double delta;
  @override
  Widget build(BuildContext context) {
    final up = delta >= 0;
    final c = up ? Colors.green.shade700 : Colors.red.shade700;
    final v = delta == delta.roundToDouble() ? delta.abs().round().toString() : delta.abs().toStringAsFixed(1);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(20)),
      child: Text('${up ? '+' : '−'}$v', style: TextStyle(color: c, fontWeight: FontWeight.w600, fontSize: 12)),
    );
  }
}

class _StatGridCard extends StatelessWidget {
  const _StatGridCard({required this.items});
  final List<(String, String)> items;
  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Overview',
      child: Wrap(spacing: 24, runSpacing: 16, children: [
        for (final it in items)
          SizedBox(width: 120, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(it.$2, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
            Text(it.$1, style: Theme.of(context).textTheme.bodySmall),
          ])),
      ]),
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
    return SectionCard(title: 'Temple Recommends (stake)', child: Column(children: [
      _Bar(label: 'Endowed with recommend', frac: _frac(r['endowedActual'], r['endowedTotal']),
          trailing: '${r['endowedActual'] ?? '—'} / ${r['endowedTotal'] ?? '—'}'),
      _Bar(label: 'Youth with recommend', frac: _frac(r['youthActual'], r['youthTotal']),
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
    return SectionCard(title: 'Ministering Interviews (stake)', child: Column(children: [
      _Bar(label: 'Brother companionships', frac: _frac(m['brotherInterviewed'], m['brotherTotal']),
          trailing: '${m['brotherInterviewed'] ?? '—'} / ${m['brotherTotal'] ?? '—'}'),
      _Bar(label: 'Sister companionships', frac: _frac(m['sisterInterviewed'], m['sisterTotal']),
          trailing: '${m['sisterInterviewed'] ?? '—'} / ${m['sisterTotal'] ?? '—'}'),
    ]));
  }
}

class _Bar extends StatelessWidget {
  const _Bar({required this.label, required this.frac, required this.trailing});
  final String label;
  final double frac;
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
        ClipRRect(borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: frac.clamp(0, 1), minHeight: 8)),
      ]),
    );
  }
}

// ---- Table (color-coded like the master sheet) ------------------------------

class _SpreadsheetView extends StatelessWidget {
  const _SpreadsheetView({required this.rows, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onOpen;

  // (header, member key, kind) — kind drives the conditional color.
  static const _cols = <(String, String, String)>[
    ('Member', 'name', 'text'),
    ('Unit', 'unit_name', 'text'),
    ('Baptism', 'baptism_date', 'text'),
    ('Member for', 'membership_duration', 'text'),
    ('Friends', 'friends', 'yesno'),
    ('Aaronic', 'aaronic_priesthood', 'yesno'),
    ('Melch.', 'melchizedek_priesthood', 'yesno'),
    ('Calling', 'calling', 'yesno'),
    ('Has min.', 'ministering_brothers_sisters', 'yesno'),
    ('Gives min.', 'ministering_assignment', 'yesno'),
    ('Recommend', 'temple_recommend', 'recommend'),
    ('Patriarchal', 'patriarchal_blessing', 'yesno'),
    ('Endowed', 'living_ordinance', 'yesno'),
  ];

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context);
    return SingleChildScrollView(
      scrollDirection: Axis.vertical,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          headingRowColor: WidgetStatePropertyAll(scheme.colorScheme.primary),
          headingTextStyle: TextStyle(color: scheme.colorScheme.onPrimary, fontWeight: FontWeight.bold),
          headingRowHeight: 44,
          dataRowMinHeight: 40,
          dataRowMaxHeight: 48,
          columnSpacing: 18,
          columns: [for (final c in _cols) DataColumn(label: Text(c.$1))],
          rows: [
            for (final m in rows)
              DataRow(
                onSelectChanged: (_) => onOpen(m),
                cells: [for (final c in _cols) _cell('${m[c.$2] ?? ''}', c.$3)],
              ),
          ],
        ),
      ),
    );
  }

  DataCell _cell(String value, String kind) {
    final color = _cellColor(value, kind);
    if (color == null) return DataCell(Text(value));
    return DataCell(Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
      child: Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
    ));
  }

  static Color? _cellColor(String v, String kind) {
    final green = Colors.green.shade100, red = Colors.red.shade100, grey = Colors.grey.shade200;
    if (kind == 'yesno') {
      if (v == 'Yes') return green;
      if (v == 'No') return red;
      if (v == 'N/A') return grey;
    } else if (kind == 'recommend') {
      if (v == 'Active') return green;
      if (v == 'Expired') return Colors.amber.shade100;
      if (v == 'No') return red;
    }
    return null;
  }
}

// ---- shared chrome ----------------------------------------------------------

/// Page scaffold for a tab: a sticky-ish header + scrollable body, capped + centered on wide.
class _Page extends StatelessWidget {
  const _Page({required this.tier, required this.header, required this.child});
  final ScreenTier tier;
  final Widget header;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final maxW = tier == ScreenTier.mobile ? double.infinity : 1280.0;
    return Center(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxW),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 16, 14, 32),
          children: [header, const SizedBox(height: 8), child],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.count, required this.byDate, required this.onToggle});
  final String title;
  final int count;
  final bool byDate;
  final ValueChanged<bool> onToggle;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Text(title, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
      const SizedBox(width: 8),
      _CountBadge(count),
      const Spacer(),
      SegmentedButton<bool>(
        showSelectedIcon: false,
        style: const ButtonStyle(visualDensity: VisualDensity.compact),
        segments: const [
          ButtonSegment(value: false, icon: Icon(Icons.groups, size: 18), label: Text('Unit')),
          ButtonSegment(value: true, icon: Icon(Icons.event, size: 18), label: Text('Date')),
        ],
        selected: {byDate},
        onSelectionChanged: (s) => onToggle(s.first),
      ),
    ]);
  }
}

class _BigHeader extends StatelessWidget {
  const _BigHeader({required this.text, required this.subtitle});
  final String text;
  final String subtitle;
  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(text, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
      Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
    ]);
  }
}

class _CountBadge extends StatelessWidget {
  const _CountBadge(this.n);
  final int n;
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(color: c.secondaryContainer, borderRadius: BorderRadius.circular(20)),
      child: Text('$n', style: TextStyle(color: c.onSecondaryContainer, fontWeight: FontWeight.bold, fontSize: 12)),
    );
  }
}

/// Lays children into [cols] balanced columns (variable-height friendly).
class _Columns extends StatelessWidget {
  const _Columns({required this.cols, required this.children});
  final int cols;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    if (cols <= 1 || children.length <= 1) {
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
    }
    final buckets = List.generate(cols, (_) => <Widget>[]);
    for (var i = 0; i < children.length; i++) {
      buckets[i % cols].add(children[i]);
    }
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var i = 0; i < cols; i++) ...[
        if (i > 0) const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: buckets[i])),
      ],
    ]);
  }
}

// ---- responsive + date + math helpers ---------------------------------------

int _cols(ScreenTier t) => switch (t) {
      ScreenTier.mobile => 1,
      ScreenTier.tablet => 2,
      ScreenTier.desktop => 3,
    };

final _longFmt = DateFormat('EEEE, MMMM d, y');
String fmtLong(DateTime? d) => d == null ? '' : _longFmt.format(d);

List<(String, List<Map<String, dynamic>>)> _groupByUnit(List<Map<String, dynamic>> rows) {
  final by = <String, List<Map<String, dynamic>>>{};
  for (final m in rows) {
    (by[(m['unit_name'] ?? '—').toString()] ??= []).add(m);
  }
  for (final list in by.values) {
    list.sort((a, b) {
      final da = parseMemberDate(a['baptism_date']), db = parseMemberDate(b['baptism_date']);
      if (da == null) return 1;
      if (db == null) return -1;
      return db.compareTo(da);
    });
  }
  final keys = by.keys.toList()..sort();
  return [for (final k in keys) (k, by[k]!)];
}

const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

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

/// Weekly "new members at sacrament": across all members' details.sacrament, count attended
/// per week label (ordered oldest->newest). Returns (labels, counts).
(List<String>, List<double>) _weeklySacrament(List<Map<String, dynamic>> rows) {
  final order = <String>[];
  final attended = <String, int>{};
  for (final m in rows) {
    final d = m['details'];
    final sacr = (d is Map ? d['sacrament'] : null) as List?;
    if (sacr == null) continue;
    for (final s in sacr) {
      if (s is! Map) continue;
      final label = s['label']?.toString() ?? '';
      if (label.isEmpty) continue;
      if (!attended.containsKey(label)) {
        attended[label] = 0;
        order.add(label);
      }
      if (s['attended'] == true) attended[label] = attended[label]! + 1;
    }
  }
  // details.sacrament is newest-first per member; reverse to oldest->newest for the trend.
  final labels = order.reversed.toList();
  return (labels, [for (final l in labels) attended[l]!.toDouble()]);
}

double _avgCompletion(List<Map<String, dynamic>> rows) {
  if (rows.isEmpty) return 0;
  var sum = 0.0;
  for (final m in rows) {
    final applicable = milestonesFor(m);
    if (applicable.isEmpty) continue;
    sum += applicable.where((x) => x.complete(m)).length / applicable.length;
  }
  return sum / rows.length;
}

double _frac(dynamic a, dynamic b) {
  final an = (a as num?)?.toDouble() ?? 0, bn = (b as num?)?.toDouble() ?? 0;
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
