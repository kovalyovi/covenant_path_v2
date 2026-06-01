part of '../dashboard_page.dart';

enum _Period { month, year, all }

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
  _Period _period = _Period.month;
  String? _unit; // null = whole stake; else drill into one unit
  bool _compare = false; // overlay the previous equal period

  (String, String) get _compareLabels => switch (_period) {
        _Period.month => ('Last month', 'This month'),
        _Period.year => ('Last year', 'This year'),
        _Period.all => ('Prev. month', 'This month'),
      };

  /// The date range the chart's x-axis currently spans, so a selected Month/Year isn't ambiguous
  /// (#range). Null for "All" (data-driven span, already labeled on the axis).
  String? _periodRangeLabel() {
    final now = DateTime.now();
    switch (_period) {
      case _Period.month:
        final from = now.subtract(const Duration(days: 35)); // 5 weeks of buckets
        return '${DateFormat('MMM d').format(from)} – ${DateFormat('MMM d, y').format(now)}';
      case _Period.year:
        final from = DateTime(now.year, now.month - 11, 1); // 12 months of buckets
        return '${DateFormat('MMM y').format(from)} – ${DateFormat('MMM y').format(now)}';
      case _Period.all:
        return null;
    }
  }

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
      _BaptismsCard(baptized: baptized, allUnits: allUnits, onOpen: onOpen),
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
        ('Lessons w/ member present', '$lessonsWithMember',
            () => _showLessonsDrill(context, _membersWithMemberLessons(rows), onOpen)), // #38
        ('New members tracked', '${baptized.length}', () => _showDrill(context,
            title: 'New members tracked', events: evs(baptized, 'baptism_date'),
            allUnits: allUnits, onOpen: onOpen)),
        ('Golden Hour', '${(completion * 100).round()}%',
            () => _showGoldenHourBreakdown(context, baptized, onOpen)), // #5: per-category summary
      ]),
      // #26: which unit integrates converts best — only meaningful stake-wide across ≥2 units.
      if (_unit == null && units.length > 1)
        _UnitCompletionCard(rows: baptized, onSelectUnit: (u) => setState(() => _unit = u)),
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
              ButtonSegment(value: _Period.month, label: Text('Month')),
              ButtonSegment(value: _Period.year, label: Text('Year')),
              ButtonSegment(value: _Period.all, label: Text('All')),
            ],
            selected: {_period},
            onSelectionChanged: (s) => setState(() => _period = s.first),
          ),
        ),
        if (_periodRangeLabel() != null) ...[
          const SizedBox(height: 6),
          Center(child: _RangePill(_periodRangeLabel()!)),
        ],
        if (_period != _Period.all) ...[
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
        ],
      ]),
      child: _Columns(cols: _cols(widget.tier).clamp(1, 2), children: cards),
    );
  }
}

/// #1/#2: baptized-convert cohort counted by baptism month over YTD / 12 mo / 24 mo / All, with the
/// best month named and a by-unit drill. Its own window selector (independent of the page period).
class _BaptismsCard extends StatefulWidget {
  const _BaptismsCard({required this.baptized, required this.allUnits, required this.onOpen});
  final List<Map<String, dynamic>> baptized;
  final Set<String> allUnits;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_BaptismsCard> createState() => _BaptismsCardState();
}

class _BaptismsCardState extends State<_BaptismsCard> {
  _BWindow _w = _BWindow.m12;
  static const _color = Color(0xFF0277BD); // baptisms blue (matches the nav accent)

  @override
  Widget build(BuildContext context) {
    final d = _baptismsByMonth(widget.baptized, _w);
    return SectionCard(
      title: 'Baptisms by month',
      leadingIcon: Icons.water_drop_outlined,
      iconColor: _color,
      onTap: d.events.isEmpty
          ? null
          : () => _showDrill(context, title: 'Baptisms', events: d.events,
              allUnits: widget.allUnits, onOpen: widget.onOpen),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Center(
          child: SegmentedButton<_BWindow>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: _BWindow.ytd, label: Text('YTD')),
              ButtonSegment(value: _BWindow.m12, label: Text('12 mo')),
              ButtonSegment(value: _BWindow.m24, label: Text('24 mo')),
              ButtonSegment(value: _BWindow.all, label: Text('All')),
            ],
            selected: {_w},
            onSelectionChanged: (s) => setState(() => _w = s.first),
          ),
        ),
        const SizedBox(height: 14),
        IntrinsicHeight(
          child: Row(children: [
            Expanded(child: _kv(context, 'Baptized in window', '${d.total}')),
            Container(
                width: 1,
                color: Theme.of(context).colorScheme.outlineVariant,
                margin: const EdgeInsets.symmetric(horizontal: 14)),
            Expanded(
                child: _kv(context, 'Best month',
                    d.bestLabel == null ? '—' : '${d.bestLabel!}  ·  ${d.bestCount}')),
          ]),
        ),
        const SizedBox(height: 14),
        SizedBox(
          height: 170,
          child: _Line(
            values: d.counts,
            labels: d.labels,
            color: _color,
            onBucketTap: (i) => _showDrill(context,
                title: 'Baptisms',
                events: d.events.where((e) => e.bucket == i).toList(),
                allUnits: widget.allUnits,
                onOpen: widget.onOpen,
                bucketLabel: i < d.labels.length ? d.labels[i] : null),
          ),
        ),
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
            child: Text('Baptized & confirmed converts, counted by baptism month.',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          ),
          TextButton.icon(
            onPressed: d.events.isEmpty
                ? null
                : () => _showDrill(context, title: 'Baptisms', events: d.events,
                    allUnits: widget.allUnits, onOpen: widget.onOpen),
            icon: const Icon(Icons.groups, size: 16),
            label: const Text('By unit'),
            style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
          ),
        ]),
      ]),
    );
  }

  Widget _kv(BuildContext context, String label, String value) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          const SizedBox(height: 2),
          Text(value,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
        ],
      );
}

class _MetricChartCard extends StatefulWidget {
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
  State<_MetricChartCard> createState() => _MetricChartCardState();
}

class _MetricChartCardState extends State<_MetricChartCard> {
  int? _hovered; // bucket index the pointer is over (per-unit summary below the chart)

  @override
  Widget build(BuildContext context) {
    final series = widget.series;
    final values = series.current;
    final last = values.isNotEmpty ? values.last : null;
    final prior = values.length >= 2 ? values[values.length - 2] : null;
    final delta = (last != null && prior != null) ? (last - prior) : null;
    return SectionCard(
      title: widget.title,
      leadingIcon: widget.icon,
      iconColor: widget.color,
      trailing: delta == null ? null : _DeltaBadge(delta: delta),
      onTap: widget.events.isEmpty
          ? null
          : () => _showDrill(context, title: widget.title, events: widget.events,
              allUnits: widget.allUnits, onOpen: widget.onOpen, bucketLabel: null), // whole card → full drill (#37)
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (last != null && prior != null) ...[
          IntrinsicHeight(
            child: Row(children: [
              Expanded(child: _bigStat(context, widget.compare.$1, prior)),
              Container(
                  width: 1,
                  color: Theme.of(context).colorScheme.outlineVariant,
                  margin: const EdgeInsets.symmetric(horizontal: 14)),
              Expanded(child: _bigStat(context, widget.compare.$2, last)),
            ]),
          ),
          const SizedBox(height: 16),
        ],
        SizedBox(
          height: 170,
          child: _Line(
            values: values,
            labels: series.labels,
            color: widget.color,
            prev: widget.showCompare ? series.prev : const [],
            onHover: (i) {
              if (i != _hovered) setState(() => _hovered = i);
            },
            onBucketTap: (i) => _showDrill(context,
                title: widget.title,
                events: widget.events.where((e) => e.bucket == i).toList(),
                allUnits: widget.allUnits,
                onOpen: widget.onOpen,
                bucketLabel: i < series.labels.length ? series.labels[i] : null),
          ),
        ),
        _hoverSummary(context), // #3: per-unit breakdown for the hovered point
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
            child: Text(widget.suffix,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          ),
          TextButton.icon(
            onPressed: () => _showDrill(context,
                title: widget.title, events: widget.events, allUnits: widget.allUnits, onOpen: widget.onOpen),
            icon: const Icon(Icons.groups, size: 16),
            label: const Text('By unit'),
            style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
          ),
        ]),
      ]),
    );
  }

  /// Fixed-height strip under the chart: hovering a point (#3) shows that bucket's per-unit counts;
  /// otherwise a hint. Fixed height so the card doesn't jump as the pointer moves.
  Widget _hoverSummary(BuildContext context) {
    final i = _hovered;
    final hint = Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade500);
    Widget body;
    if (i == null || i >= widget.series.labels.length) {
      body = Text('Hover a point for the per-unit breakdown', style: hint);
    } else {
      final byUnit = <String, Set<String>>{};
      for (final e in widget.events.where((e) => e.bucket == i)) {
        (byUnit[(e.m['unit_name'] ?? '—').toString()] ??= {})
            .add((e.m['person_uuid'] ?? e.m['name'] ?? '').toString());
      }
      final total = byUnit.values.fold<int>(0, (a, s) => a + s.length);
      final parts = (byUnit.entries.toList()..sort((a, b) => b.value.length.compareTo(a.value.length)))
          .map((e) => '${e.key} ${e.value.length}')
          .join('  ·  ');
      body = Text(
        total == 0 ? '${widget.series.labels[i]} · none' : '${widget.series.labels[i]} · $total  —  $parts',
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w500),
      );
    }
    return Container(
      width: double.infinity,
      height: 38,
      alignment: Alignment.centerLeft,
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: i == null ? Colors.transparent : widget.color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: body,
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
      this.prev = const [], this.onBucketTap, this.onHover});
  final List<double> values;
  final List<String> labels;
  final Color color;
  final List<double> prev; // previous-period overlay (drawn faded/dashed when non-empty)
  final void Function(int bucketIndex)? onBucketTap;
  final void Function(int? bucketIndex)? onHover; // null = pointer left the chart

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
        enabled: onBucketTap != null || onHover != null,
        handleBuiltInTouches: false, // don't draw a built-in tooltip (keeps the always-on labels)
        // #4: show the click cursor when the pointer is over a data point.
        mouseCursorResolver: (event, resp) => (resp?.lineBarSpots?.isNotEmpty ?? false)
            ? SystemMouseCursors.click
            : SystemMouseCursors.basic,
        touchCallback: (event, resp) {
          final spot = resp?.lineBarSpots?.isNotEmpty ?? false ? resp!.lineBarSpots!.first : null;
          // #3: report the hovered bucket (and clear it when the pointer leaves).
          if (event is FlPointerExitEvent || spot == null) {
            onHover?.call(null);
          } else {
            onHover?.call(spot.x.toInt());
          }
          if (onBucketTap != null && event is FlTapUpEvent && spot != null) {
            onBucketTap!(spot.x.toInt());
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

/// #5: Golden Hour completion broken out per category, eligible-only (matches the GH tab). Each row
/// expands to the eligible members still missing that milestone, tappable to open them.
void _showGoldenHourBreakdown(BuildContext context, List<Map<String, dynamic>> rows,
    void Function(Map<String, dynamic>) onOpen) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    constraints: const BoxConstraints(maxWidth: 640),
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scroll) => ListView(
        controller: scroll,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          Text('Golden Hour by category',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          Text('Eligible-only — members who don\'t qualify (age, sex, tenure) are excluded so the % '
              'reflects who actually still needs it.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          const SizedBox(height: 8),
          for (final ms in milestones)
            () {
              final eligible = rows.where(ms.eligible).toList();
              if (eligible.isEmpty) return const SizedBox.shrink();
              final missing = eligible.where((m) => !ms.complete(m)).toList()
                ..sort((a, b) => '${a['name']}'.compareTo('${b['name']}'));
              final done = eligible.length - missing.length;
              final pct = done / eligible.length;
              return Card(
                elevation: 0,
                margin: const EdgeInsets.symmetric(vertical: 4),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                    side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant)),
                child: ExpansionTile(
                  title: Text(ms.label),
                  initiallyExpanded: missing.isNotEmpty, // #40: open the actionable categories
                  subtitle: Padding(
                    padding: const EdgeInsets.only(top: 6, right: 40),
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: LinearProgressIndicator(value: pct, minHeight: 5),
                    ),
                  ),
                  trailing: Text('${(pct * 100).round()}%  ·  $done/${eligible.length}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  children: missing.isEmpty
                      ? [const Padding(padding: EdgeInsets.all(16), child: Text('Everyone eligible has this. 🎉'))]
                      : [
                          for (final m in missing)
                            ListTile(
                              dense: true,
                              leading: PhotoAvatar(
                                  name: m['name']?.toString() ?? '?',
                                  photoUrl: m['photo_url']?.toString(),
                                  size: 32),
                              title: Text(m['name']?.toString() ?? '—'),
                              subtitle: Text('${m['unit_name'] ?? ''}'),
                              onTap: () {
                                Navigator.pop(context);
                                onOpen(m);
                              },
                            ),
                        ],
                ),
              );
            }(),
        ],
      ),
    ),
  );
}

/// #38: the members behind "Lessons with a member present" — who had member-supported lessons, and
/// how many — ranked. (A time plot isn't possible; our stored lessons carry no per-lesson date.)
void _showLessonsDrill(BuildContext context, List<({Map<String, dynamic> m, int count})> people,
    void Function(Map<String, dynamic>) onOpen) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    constraints: const BoxConstraints(maxWidth: 640),
    builder: (_) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.6,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scroll) => ListView(
        controller: scroll,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          Text('Lessons with a member present',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          Text('${people.length} ${people.length == 1 ? 'person' : 'people'} · ranked by count',
              style: Theme.of(context).textTheme.bodySmall),
          const Divider(),
          if (people.isEmpty)
            const Padding(
                padding: EdgeInsets.all(20),
                child: Center(child: Text('No member-present lessons recorded yet.')))
          else
            for (final p in people)
              ListTile(
                dense: true,
                leading: PhotoAvatar(
                    name: p.m['name']?.toString() ?? '?',
                    photoUrl: p.m['photo_url']?.toString(),
                    size: 34),
                title: Text(p.m['name']?.toString() ?? '—'),
                subtitle: Text('${p.m['unit_name'] ?? ''}'),
                trailing: _CountBadge(p.count),
                onTap: () {
                  Navigator.pop(context);
                  onOpen(p.m);
                },
              ),
        ],
      ),
    ),
  );
}

/// #26: a ranked bar list of each unit's average Golden Hour completion — which unit integrates its
/// converts best. Tapping a unit scopes the KPI page to it.
class _UnitCompletionCard extends StatelessWidget {
  const _UnitCompletionCard({required this.rows, required this.onSelectUnit});
  final List<Map<String, dynamic>> rows; // baptized members in scope
  final void Function(String unit) onSelectUnit;
  @override
  Widget build(BuildContext context) {
    final ranked = _unitCompletion(rows);
    if (ranked.length < 2) return const SizedBox.shrink();
    return SectionCard(
      title: 'Golden Hour by unit',
      leadingIcon: Icons.leaderboard_outlined,
      child: Column(children: [
        for (final r in ranked)
          InkWell(
            onTap: () => onSelectUnit(r.unit),
            borderRadius: BorderRadius.circular(8),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
              child: Row(children: [
                Expanded(
                    flex: 4,
                    child: Text(r.unit, maxLines: 1, overflow: TextOverflow.ellipsis)),
                const SizedBox(width: 8),
                Expanded(
                  flex: 5,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(value: r.pct, minHeight: 8),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 62,
                  child: Text('${(r.pct * 100).round()}% · ${r.n}',
                      textAlign: TextAlign.right,
                      style: Theme.of(context).textTheme.bodySmall),
                ),
              ]),
            ),
          ),
      ]),
    );
  }
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
                    initiallyExpanded: true, // #2: units expanded on open, not collapsed
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
