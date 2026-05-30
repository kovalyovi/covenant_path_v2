part of '../dashboard_page.dart';

enum _Period { week, month, year }

/// KPIs computed from this stake's own covenant-path data (not LCR membership stats):
///   • New Members at Sacrament — baptized members attending, bucketed by the selected period
///   • Friends at Sacrament     — people being taught attending
///   • New friends being taught / Lessons with member present — current counts
/// Each chart overlays the most recent window against the immediately-preceding window in a
/// contrasting color, so you can see the change. Calendar week / month / year toggle.
class _KpiView extends StatefulWidget {
  const _KpiView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_KpiView> createState() => _KpiViewState();
}

class _KpiViewState extends State<_KpiView> {
  _Period _period = _Period.week;
  String? _unit; // null = whole stake; else drill into one unit
  bool _compare = false; // overlay the previous equal period

  (String, String) get _compareLabels => switch (_period) {
        _Period.week => ('2 weeks ago', 'Last week'),
        _Period.month => ('Last month', 'This month'),
        _Period.year => ('Last year', 'This year'),
      };

  @override
  Widget build(BuildContext context) {
    final units = (widget.rows.map((m) => '${m['unit_name'] ?? ''}').where((u) => u.isNotEmpty).toSet().toList()
      ..sort());
    final rows = _unit == null
        ? widget.rows
        : widget.rows.where((m) => m['unit_name'] == _unit).toList();
    final baptized = rows.where((m) => m['kind'] != 'investigator').toList();
    final investigators = rows.where((m) => m['kind'] == 'investigator').toList();
    final allUnits = rows.map((m) => '${m['unit_name'] ?? '—'}').toSet();
    final onOpen = widget.onOpen;
    // unique people per period (a member attending several Sundays in a month counts once)
    final friendsAtSac = _metricData(investigators, datesOf: _attendedDates, period: _period);
    final newAtSac = _metricData(baptized, datesOf: _attendedDates, period: _period);
    final newFriends = _metricData(investigators, datesOf: _firstLessonDate, period: _period);
    final lessonsWithMember = _lessonsWithMember(rows);
    final completion = _avgCompletion(baptized);
    // overview drills: list the people behind a number (one entry each, dated for the chrono view)
    List<_Ev> evs(Iterable<Map<String, dynamic>> ms, String dateField) =>
        [for (final m in ms) _Ev(m, parseMemberDate(m[dateField]) ?? DateTime.now(), 0)];

    final cards = <Widget>[
      _MetricChartCard(
        title: 'Investigators at Sacrament',
        icon: Icons.groups,
        color: Colors.orange.shade700,
        series: friendsAtSac.series,
        events: friendsAtSac.events,
        allUnits: allUnits,
        onOpen: onOpen,
        compare: _compareLabels,
        showCompare: _compare,
        suffix: 'people being taught who attended sacrament',
      ),
      _MetricChartCard(
        title: 'New Members at Sacrament',
        icon: Icons.favorite,
        color: const Color(0xFFB5532A),
        series: newAtSac.series,
        events: newAtSac.events,
        allUnits: allUnits,
        onOpen: onOpen,
        compare: _compareLabels,
        showCompare: _compare,
        suffix: 'baptized members who attended sacrament',
      ),
      _MetricChartCard(
        title: 'New Friends Being Taught',
        icon: Icons.local_library,
        color: Colors.teal.shade600,
        series: newFriends.series,
        events: newFriends.events,
        allUnits: allUnits,
        onOpen: onOpen,
        compare: _compareLabels,
        showCompare: _compare,
        suffix: 'people who started lessons in the period',
      ),
      _StatGridCard(items: [
        ('Being taught now', '${investigators.length}', () => _showDrill(context,
            title: 'Being taught now', events: evs(investigators, 'baptism_goal_date'),
            allUnits: allUnits, onOpen: onOpen)),
        ('Lessons w/ member present', '$lessonsWithMember', null),
        ('New members tracked', '${baptized.length}', () => _showDrill(context,
            title: 'New members tracked', events: evs(baptized, 'baptism_date'),
            allUnits: allUnits, onOpen: onOpen)),
        ('Golden Hour', '${(completion * 100).round()}%', null),
      ]),
    ];

    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
              child: _BigHeader(text: 'KPIs', subtitle: "From this stake's covenant-path data")),
          if (units.length > 1)
            DropdownButton<String?>(
              value: _unit,
              hint: const Text('All units'),
              items: [
                const DropdownMenuItem(value: null, child: Text('All units')),
                for (final u in units) DropdownMenuItem(value: u, child: Text(u)),
              ],
              onChanged: (v) => setState(() => _unit = v),
            ),
        ]),
        const SizedBox(height: 10),
        Center(
          child: SegmentedButton<_Period>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: _Period.week, label: Text('Week')),
              ButtonSegment(value: _Period.month, label: Text('Month')),
              ButtonSegment(value: _Period.year, label: Text('Year')),
            ],
            selected: {_period},
            onSelectionChanged: (s) => setState(() => _period = s.first),
          ),
        ),
        const SizedBox(height: 8),
        Center(
          child: FilterChip(
            avatar: Icon(Icons.compare_arrows,
                size: 18, color: _compare ? Theme.of(context).colorScheme.primary : null),
            label: const Text('Compare to previous'),
            selected: _compare,
            onSelected: (v) => setState(() => _compare = v),
          ),
        ),
      ]),
      child: _Columns(cols: _cols(widget.tier).clamp(1, 2), children: cards),
    );
  }
}

class _MetricChartCard extends StatelessWidget {
  const _MetricChartCard({required this.title, required this.icon, required this.color,
      required this.series, required this.compare, required this.suffix,
      required this.events, required this.allUnits, required this.onOpen, this.showCompare = false});
  final String title;
  final IconData icon;
  final Color color;
  final _Series series;
  final (String, String) compare; // (prior label, latest label)
  final String suffix;
  final List<_Ev> events;
  final Set<String> allUnits;
  final void Function(Map<String, dynamic>) onOpen;
  final bool showCompare;

  @override
  Widget build(BuildContext context) {
    final values = series.current;
    final last = values.isNotEmpty ? values.last : null;
    final prior = values.length >= 2 ? values[values.length - 2] : null;
    final delta = (last != null && prior != null) ? (last - prior) : null;
    return SectionCard(
      title: title,
      leadingIcon: icon,
      iconColor: color,
      trailing: delta == null ? null : _DeltaBadge(delta: delta),
      onTap: events.isEmpty
          ? null
          : () => _showDrill(context, title: title, events: events, allUnits: allUnits,
              onOpen: onOpen, bucketLabel: null), // whole card opens the full drill (#37)
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (last != null && prior != null) ...[
          IntrinsicHeight(
            child: Row(children: [
              Expanded(child: _bigStat(context, compare.$1, prior)),
              Container(
                  width: 1,
                  color: Theme.of(context).colorScheme.outlineVariant,
                  margin: const EdgeInsets.symmetric(horizontal: 14)),
              Expanded(child: _bigStat(context, compare.$2, last)),
            ]),
          ),
          const SizedBox(height: 16),
        ],
        SizedBox(
          height: 170,
          child: _Line(
            values: values,
            labels: series.labels,
            color: color,
            prev: showCompare ? series.prev : const [],
            onBucketTap: (i) => _showDrill(context,
                title: title,
                events: events.where((e) => e.bucket == i).toList(),
                allUnits: allUnits,
                onOpen: onOpen,
                bucketLabel: i < series.labels.length ? series.labels[i] : null),
          ),
        ),
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
            child: Text(suffix,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          ),
          TextButton.icon(
            onPressed: () => _showDrill(context,
                title: title, events: events, allUnits: allUnits, onOpen: onOpen),
            icon: const Icon(Icons.groups, size: 16),
            label: const Text('By unit'),
            style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
          ),
        ]),
      ]),
    );
  }

  Widget _bigStat(BuildContext context, String label, double v) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          const SizedBox(height: 2),
          Text(v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(1),
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
        ],
      );
}

/// iOS-style trend line: smooth curve, gradient fill, open dots, and a value label above
/// every point (always-on tooltips). Sparse gray x-axis labels.
class _Line extends StatelessWidget {
  const _Line(
      {required this.values, required this.labels, required this.color,
      this.prev = const [], this.onBucketTap});
  final List<double> values;
  final List<String> labels;
  final Color color;
  final List<double> prev; // previous-period overlay (drawn faded/dashed when non-empty)
  final void Function(int bucketIndex)? onBucketTap;

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) {
      return Center(child: Text('No data yet', style: TextStyle(color: Colors.grey.shade500)));
    }
    final peak = [...values, ...prev].reduce((a, b) => a > b ? a : b);
    final maxY = peak * 1.35 + 1; // headroom so the value labels above points aren't clipped
    final spots = [for (var i = 0; i < values.length; i++) FlSpot(i.toDouble(), values[i])];
    final bar = LineChartBarData(
      spots: spots,
      isCurved: true,
      curveSmoothness: 0.3,
      preventCurveOverShooting: true,
      color: color,
      barWidth: 3,
      dotData: FlDotData(
        show: true,
        getDotPainter: (spot, pct, b, i) => FlDotCirclePainter(
            radius: 3.5, color: Colors.white, strokeWidth: 2, strokeColor: color),
      ),
      belowBarData: BarAreaData(
        show: true,
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [color.withValues(alpha: 0.28), color.withValues(alpha: 0.02)],
        ),
      ),
    );
    final prevBar = prev.isEmpty
        ? null
        : LineChartBarData(
            spots: [for (var i = 0; i < prev.length; i++) FlSpot(i.toDouble(), prev[i])],
            isCurved: true,
            curveSmoothness: 0.3,
            color: Colors.grey.shade400,
            barWidth: 2,
            dashArray: const [5, 4],
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(show: false),
          );
    final step = (values.length / 3).ceil().clamp(1, 999);
    return LineChart(LineChartData(
      minY: 0,
      maxY: maxY,
      gridData: const FlGridData(show: false),
      borderData: FlBorderData(show: false),
      lineTouchData: LineTouchData(
        enabled: onBucketTap != null,
        handleBuiltInTouches: false, // don't draw a built-in tooltip (keeps the always-on labels)
        touchCallback: (event, resp) {
          if (onBucketTap != null &&
              event is FlTapUpEvent &&
              (resp?.lineBarSpots?.isNotEmpty ?? false)) {
            onBucketTap!(resp!.lineBarSpots!.first.x.toInt());
          }
        },
        touchTooltipData: LineTouchTooltipData(
          getTooltipColor: (_) => Colors.transparent,
          tooltipPadding: EdgeInsets.zero,
          tooltipMargin: 4,
          getTooltipItems: (touched) => [
            for (final t in touched)
              t.barIndex == 0 && prevBar != null
                  ? null
                  : LineTooltipItem(
                      t.y == t.y.roundToDouble() ? '${t.y.round()}' : t.y.toStringAsFixed(0),
                      TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11),
                    ),
          ],
        ),
      ),
      showingTooltipIndicators: [
        for (var i = 0; i < spots.length; i++)
          ShowingTooltipIndicators([LineBarSpot(bar, prevBar != null ? 1 : 0, spots[i])]),
      ],
      titlesData: FlTitlesData(
        leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: 1,
            reservedSize: 22,
            getTitlesWidget: (x, meta) {
              final i = x.toInt();
              if (i < 0 || i >= labels.length) return const SizedBox.shrink();
              if (i % step != 0 && i != labels.length - 1) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(labels[i], style: TextStyle(fontSize: 10, color: Colors.grey.shade500)),
              );
            },
          ),
        ),
      ),
      lineBarsData: [if (prevBar != null) prevBar, bar],
    ));
  }
}

/// Opens the people behind a metric: distribution **by unit** (every unit in scope, including
/// those with 0) expandable to names, or **chronologically** by their date (with unit shown).
void _showDrill(BuildContext context,
    {required String title,
    required List<_Ev> events,
    required Set<String> allUnits,
    required void Function(Map<String, dynamic>) onOpen,
    String? bucketLabel}) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    constraints: const BoxConstraints(maxWidth: 640),
    builder: (_) => _DrillSheet(
        title: title, events: events, allUnits: allUnits, onOpen: onOpen, bucketLabel: bucketLabel),
  );
}

class _DrillSheet extends StatefulWidget {
  const _DrillSheet(
      {required this.title,
      required this.events,
      required this.allUnits,
      required this.onOpen,
      this.bucketLabel});
  final String title;
  final List<_Ev> events;
  final Set<String> allUnits;
  final void Function(Map<String, dynamic>) onOpen;
  final String? bucketLabel;
  @override
  State<_DrillSheet> createState() => _DrillSheetState();
}

class _DrillSheetState extends State<_DrillSheet> {
  bool _byUnit = true;
  String _unit(Map<String, dynamic> m) => (m['unit_name'] ?? '—').toString();
  String _id(Map<String, dynamic> m) => (m['person_uuid'] ?? m['name'] ?? '').toString();

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scroll) => ListView(
        controller: scroll,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          Text(widget.title + (widget.bucketLabel != null ? ' · ${widget.bucketLabel}' : ''),
              style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 10),
          Center(
            child: SegmentedButton<bool>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: true, icon: Icon(Icons.groups, size: 18), label: Text('By unit')),
                ButtonSegment(value: false, icon: Icon(Icons.schedule, size: 18), label: Text('By date')),
              ],
              selected: {_byUnit},
              onSelectionChanged: (s) => setState(() => _byUnit = s.first),
            ),
          ),
          const SizedBox(height: 12),
          ...(_byUnit ? _byUnitTiles(context) : _chronoTiles(context)),
        ],
      ),
    );
  }

  List<Widget> _byUnitTiles(BuildContext context) {
    final byUnit = <String, Map<String, Map<String, dynamic>>>{for (final u in widget.allUnits) u: {}};
    for (final e in widget.events) {
      (byUnit[_unit(e.m)] ??= {})[_id(e.m)] = e.m;
    }
    final units = byUnit.keys.toList()..sort();
    return [
      for (final u in units)
        Builder(builder: (context) {
          final members = byUnit[u]!.values.toList()
            ..sort((a, b) => (a['name'] ?? '').toString().compareTo((b['name'] ?? '').toString()));
          final card = Card(
            elevation: 0,
            margin: const EdgeInsets.symmetric(vertical: 4),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
                side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant)),
            child: members.isEmpty
                ? ListTile(
                    dense: true,
                    title: Text(u, style: TextStyle(color: Colors.grey.shade600)),
                    trailing: Text('0', style: TextStyle(color: Colors.grey.shade500)))
                : ExpansionTile(
                    title: Text(u),
                    trailing: _CountBadge(members.length),
                    children: [
                      for (final m in members)
                        ListTile(
                          dense: true,
                          leading: PhotoAvatar(
                              name: m['name']?.toString() ?? '?',
                              photoUrl: m['photo_url']?.toString(),
                              size: 32),
                          title: Text(m['name']?.toString() ?? '—'),
                          onTap: () {
                            Navigator.pop(context);
                            widget.onOpen(m);
                          },
                        ),
                    ],
                  ),
          );
          return card;
        }),
    ];
  }

  List<Widget> _chronoTiles(BuildContext context) {
    final sorted = [...widget.events]..sort((a, b) => b.date.compareTo(a.date));
    if (sorted.isEmpty) {
      return [Padding(padding: const EdgeInsets.all(16), child: Text('No one in this view.', style: TextStyle(color: Colors.grey.shade600)))];
    }
    return [
      for (final e in sorted)
        ListTile(
          dense: true,
          leading: PhotoAvatar(
              name: e.m['name']?.toString() ?? '?', photoUrl: e.m['photo_url']?.toString(), size: 32),
          title: Text(e.m['name']?.toString() ?? '—'),
          subtitle: Text('${_unit(e.m)} · ${fmtLong(e.date)}'),
          onTap: () {
            Navigator.pop(context);
            widget.onOpen(e.m);
          },
        ),
    ];
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
  final List<(String, String, VoidCallback?)> items; // (label, value, onTap?)
  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Overview',
      child: Wrap(spacing: 24, runSpacing: 16, children: [
        for (final it in items)
          InkWell(
            onTap: it.$3,
            borderRadius: BorderRadius.circular(8),
            child: SizedBox(
                width: 124,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Text(it.$2,
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
                    if (it.$3 != null) ...[
                      const SizedBox(width: 3),
                      Icon(Icons.chevron_right, size: 18, color: Colors.grey.shade500),
                    ],
                  ]),
                  Text(it.$1, style: Theme.of(context).textTheme.bodySmall),
                ])),
          ),
      ]),
    );
  }
}

// ---- Table (color-coded like the master sheet) ------------------------------
