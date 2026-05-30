part of '../dashboard_page.dart';

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

/// Shown across the top while a scrape is running for the user's stake (coarse status from
/// stakes.sync_state). Covers the new-stake "first sync" case too — the row exists the moment
/// the run starts, so a freshly-onboarded stake sees this instead of an empty screen.
/// Live "syncing your stake" banner with an elapsed-time counter (item 10). Auto-dismisses when
/// the dashboard stops passing it (sync_state flips to 'done'). [startedAt] drives the timer.
class _SyncingBanner extends StatefulWidget {
  const _SyncingBanner({this.startedAt});
  final DateTime? startedAt;
  @override
  State<_SyncingBanner> createState() => _SyncingBannerState();
}

class _SyncingBannerState extends State<_SyncingBanner> {
  Timer? _t;
  @override
  void initState() {
    super.initState();
    if (widget.startedAt != null) {
      _t = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
    }
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  String get _elapsed {
    if (widget.startedAt == null) return '';
    final d = DateTime.now().toUtc().difference(widget.startedAt!.toUtc());
    final m = d.inMinutes, s = d.inSeconds % 60;
    return m > 0 ? ' · ${m}m ${s}s elapsed' : ' · ${s}s elapsed';
  }

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Material(
      color: c.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          SizedBox(
            width: 16, height: 16,
            child: CircularProgressIndicator(strokeWidth: 2, color: c.onSecondaryContainer),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text('Syncing your stake from LCR — fresh data in a few minutes$_elapsed.',
                style: TextStyle(color: c.onSecondaryContainer)),
          ),
        ]),
      ),
    );
  }
}

/// AppBar chip showing data freshness. Shows "Updated 2h ago" (icon-only when [compact]);
/// hover tooltip and tap both reveal the exact local date/time + timezone of the last scrape.
class _LastUpdated extends StatelessWidget {
  const _LastUpdated({required this.iso, this.compact = false});
  final String iso;
  final bool compact;

  String get _exact {
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return iso;
    return '${DateFormat('MMM d, y · h:mm a').format(dt)} ${dt.timeZoneName}';
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Tooltip(
        message: 'Data last updated:\n$_exact',
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: () => showDialog<void>(
            context: context,
            builder: (_) => AlertDialog(
              title: const Text('Data freshness'),
              content: Text('Last scraped from LCR:\n\n$_exact'),
              actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
            ),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.history, size: 18),
              if (!compact) ...[
                const SizedBox(width: 4),
                Text('Updated ${_ago(iso)}', style: const TextStyle(fontSize: 12)),
              ],
            ]),
          ),
        ),
      ),
    );
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

List<(String, List<Map<String, dynamic>>)> _groupByUnit(List<Map<String, dynamic>> rows,
    {String dateField = 'baptism_date', bool ascending = false}) {
  final by = <String, List<Map<String, dynamic>>>{};
  for (final m in rows) {
    (by[(m['unit_name'] ?? '—').toString()] ??= []).add(m);
  }
  for (final list in by.values) {
    list.sort((a, b) {
      final da = parseMemberDate(a[dateField]), db = parseMemberDate(b[dateField]);
      if (da == null) return 1;
      if (db == null) return -1;
      return ascending ? da.compareTo(db) : db.compareTo(da);
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

/// A chart series: the most recent window of buckets ([current] + [labels]) overlaid against
/// the immediately-preceding equal-length window ([prev], position-aligned; empty if none).
typedef _Series = ({List<String> labels, List<double> current, List<double> prev});

// Rolling durations, not calendar buckets (#35): Week = last 7 DAYS (daily), Month = last ~5 WEEKS
// (weekly), Year = last 12 MONTHS (monthly). The prev overlay is the immediately preceding equal
// span (handled in _metricData), so it's "this week vs last week by day", etc. (#36).
const _periodWindow = {_Period.week: 7, _Period.month: 5, _Period.year: 12};

(int, String) _bucketOf(DateTime dt, _Period p) {
  switch (p) {
    case _Period.week: // daily buckets
      return (dt.year * 10000 + dt.month * 100 + dt.day, DateFormat('E').format(dt)); // Mon, Tue…
    case _Period.month: // weekly buckets (ISO week start)
      final monday = dt.subtract(Duration(days: dt.weekday - 1));
      return (monday.year * 10000 + monday.month * 100 + monday.day, DateFormat('M/d').format(monday));
    case _Period.year: // monthly buckets
      return (dt.year * 100 + dt.month, DateFormat('MMM').format(dt));
  }
}

/// One matching event for the drill-down: a member counted toward a metric on a date, mapped to
/// the displayed-window bucket index (the x-position on the chart).
class _Ev {
  const _Ev(this.m, this.date, this.bucket);
  final Map<String, dynamic> m;
  final DateTime date;
  final int bucket;
}

/// Series for the chart (unique people per bucket, recent window vs the preceding one) PLUS the
/// underlying events so a tap can show *who* (with their unit), by unit or chronologically.
({_Series series, List<_Ev> events}) _metricData(Iterable<Map<String, dynamic>> rows,
    {required Iterable<DateTime> Function(Map<String, dynamic>) datesOf, required _Period period}) {
  final sets = <int, Set<String>>{};
  final labels = <int, String>{};
  final raw = <(Map<String, dynamic>, DateTime, int)>[]; // (member, date, bucketKey)
  for (final m in rows) {
    final id = (m['person_uuid'] ?? m['name'] ?? identityHashCode(m)).toString();
    for (final dt in datesOf(m)) {
      final (key, label) = _bucketOf(dt, period);
      labels[key] = label;
      (sets[key] ??= <String>{}).add(id);
      raw.add((m, dt, key));
    }
  }
  if (sets.isEmpty) return (series: (labels: [], current: [], prev: []), events: []);
  final keys = sets.keys.toList()..sort();
  final n = _periodWindow[period]!;
  final start = (keys.length - n).clamp(0, keys.length);
  final windowKeys = keys.sublist(start);
  final idxOf = {for (var i = 0; i < windowKeys.length; i++) windowKeys[i]: i};
  final cur = <double>[], prv = <double>[], lab = <String>[];
  for (var i = start; i < keys.length; i++) {
    cur.add(sets[keys[i]]!.length.toDouble());
    lab.add(labels[keys[i]]!);
    final pj = i - n;
    prv.add(pj >= 0 ? sets[keys[pj]]!.length.toDouble() : 0);
  }
  final events = [
    for (final r in raw)
      if (idxOf.containsKey(r.$3)) _Ev(r.$1, r.$2, idxOf[r.$3]!),
  ];
  return (series: (labels: lab, current: cur, prev: keys.length > n ? prv : []), events: events);
}

/// Sundays this person was marked present at sacrament.
Iterable<DateTime> _attendedDates(Map<String, dynamic> m) sync* {
  final d = m['details'];
  final sac = (d is Map ? d['sacrament'] : null) as List?;
  if (sac == null) return;
  for (final s in sac) {
    if (s is! Map || s['attended'] != true) continue;
    final dt = parseMemberDate(s['date']);
    if (dt != null) yield dt;
  }
}

/// The single date this person started being taught (missionary "first lesson").
Iterable<DateTime> _firstLessonDate(Map<String, dynamic> m) sync* {
  final fl = parseMemberDate((m['details'] as Map?)?['firstLesson']);
  if (fl != null) yield fl;
}

/// Count of lessons taught (across all people) where a member was present for ≥1 principle.
int _lessonsWithMember(List<Map<String, dynamic>> rows) {
  var c = 0;
  for (final m in rows) {
    final d = m['details'];
    final lessons = (d is Map ? d['lessons'] : null) as List?;
    if (lessons == null) continue;
    for (final l in lessons) {
      if (l is! Map) continue;
      final ps = (l['principles'] as List?) ?? const [];
      if (ps.any((p) => p is Map && p['memberPresent'] == true)) c++;
    }
  }
  return c;
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

String _ago(dynamic iso) {
  final t = DateTime.tryParse('${iso ?? ''}');
  if (t == null) return '$iso';
  final diff = DateTime.now().toUtc().difference(t.toUtc());
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}
