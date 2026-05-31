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
          // extra bottom clearance on mobile so the last card isn't hidden behind the glass nav (#41)
          padding: EdgeInsets.fromLTRB(14, 16, 14, tier == ScreenTier.mobile ? 96 : 32),
          children: [header, const SizedBox(height: 8), child],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.count, required this.byDate,
      required this.onToggle, this.ascending, this.onAscToggle});
  final String title;
  final int count;
  final bool byDate;
  final ValueChanged<bool> onToggle;
  final bool? ascending; // when set with onAscToggle, shows an asc/desc sort toggle
  final VoidCallback? onAscToggle;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Flexible(
        child: Text(title,
            style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
            overflow: TextOverflow.ellipsis),
      ),
      const SizedBox(width: 8),
      _CountBadge(count),
      const Spacer(),
      if (onAscToggle != null)
        IconButton(
          tooltip: ascending == true ? 'Oldest first (tap for newest)' : 'Newest first (tap for oldest)',
          visualDensity: VisualDensity.compact,
          icon: Icon(ascending == true ? Icons.arrow_upward : Icons.arrow_downward, size: 18),
          onPressed: onAscToggle,
        ),
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

/// AppBar chip showing data freshness. Shows "Updated 2h ago" (icon-only when [compact]); while a
/// scrape is running it shows a spinner + "Syncing…". Tapping opens a dialog with the exact local
/// time and — when [onSyncNow] is provided — a "Sync now" button (or in-progress state). (#freshness)
class _LastUpdated extends StatelessWidget {
  const _LastUpdated({required this.iso, this.compact = false, this.onSyncNow, this.syncing = false});
  final String iso;
  final bool compact;
  final VoidCallback? onSyncNow; // triggers a sync; closes the dialog itself
  final bool syncing;

  String get _exact {
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return iso;
    return '${DateFormat('MMM d, y · h:mm a').format(dt)} ${dt.timeZoneName}';
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Tooltip(
        message: syncing ? 'Sync in progress…' : 'Data last updated:\n$_exact',
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: () => showDialog<void>(
            context: context,
            builder: (dctx) => AlertDialog(
              title: const Text('Data freshness'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Last scraped from LCR:\n\n$_exact'),
                  if (syncing) ...[
                    const SizedBox(height: 18),
                    Row(children: [
                      const SizedBox(
                          width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                      const SizedBox(width: 10),
                      Text('Sync in progress — fresh data in a few minutes.',
                          style: Theme.of(context).textTheme.bodySmall),
                    ]),
                  ] else if (onSyncNow != null) ...[
                    const SizedBox(height: 16),
                    Text('Run a fresh scrape now using your stake\'s saved sync credential.',
                        style: Theme.of(context).textTheme.bodySmall),
                  ],
                ],
              ),
              actions: [
                if (onSyncNow != null && !syncing)
                  FilledButton.icon(
                      onPressed: onSyncNow, // closes the dialog + kicks off the sync
                      icon: const Icon(Icons.sync, size: 18),
                      label: const Text('Sync now')),
                TextButton(onPressed: () => Navigator.pop(dctx), child: const Text('Close')),
              ],
            ),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (syncing)
                const SizedBox(width: 15, height: 15, child: CircularProgressIndicator(strokeWidth: 2))
              else
                // #18 staleness: amber >2d, red >2w, default when fresh.
                Icon(_staleColor(iso) == null ? Icons.history : Icons.history_toggle_off,
                    size: 18, color: _staleColor(iso)),
              if (!compact) ...[
                const SizedBox(width: 5),
                Text(syncing ? 'Syncing…' : 'Updated ${_ago(iso)}',
                    style: TextStyle(fontSize: 12, color: _staleColor(iso))),
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

// Fixed windows anchored to TODAY, not "the last N buckets that happen to have data" (#1):
//   Month = the 5 WEEKS ending this week   (weekly buckets)
//   Year  = the 12 MONTHS ending this month(monthly buckets)
//   All   = first data → now, grouped by MONTH (≤3 yrs) or by YEAR (longer, so it stays readable)
// Buckets with no events render as zeros (the window is honest about quiet stretches). The prev
// overlay is the immediately-preceding equal span (this week vs last week, etc.).

DateTime _dayOnly(DateTime d) => DateTime(d.year, d.month, d.day);
DateTime _weekStart(DateTime d) => _dayOnly(d).subtract(Duration(days: d.weekday - 1)); // Monday

/// Bucket key (stable, sortable int) for an event's date under [p] — must match _windowBuckets.
int _bucketKey(DateTime dt, _Period p, {bool allByYear = false}) {
  switch (p) {
    case _Period.month:
      final w = _weekStart(dt);
      return w.year * 10000 + w.month * 100 + w.day; // per ISO week
    case _Period.year:
      return dt.year * 100 + dt.month; // per month
    case _Period.all:
      return allByYear ? dt.year : dt.year * 100 + dt.month; // per year (long spans) or per month
  }
}

/// The ordered (key, label) buckets of the window ending [today], shifted back [shift] windows
/// (shift=1 → the immediately-preceding equal span, for the compare overlay). _Period.all is data-
/// driven and handled in _metricData, so it returns empty here.
List<(int, String)> _windowBuckets(_Period p, DateTime today, int shift) {
  switch (p) {
    case _Period.month:
      final end = _weekStart(today).subtract(Duration(days: shift * 5 * 7));
      return [
        for (var i = 4; i >= 0; i--)
          () {
            final w = end.subtract(Duration(days: i * 7));
            return (w.year * 10000 + w.month * 100 + w.day, DateFormat('M/d').format(w));
          }()
      ];
    case _Period.year:
      return [
        for (var i = 11; i >= 0; i--)
          () {
            final m = DateTime(today.year, today.month - shift * 12 - i, 1);
            return (m.year * 100 + m.month, DateFormat('MMM').format(m));
          }()
      ];
    case _Period.all:
      return const [];
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
  final today = DateTime.now();
  // Collect (member, date) pairs up front so 'All' can choose its bucket granularity from the span.
  final pairs = <(Map<String, dynamic>, DateTime)>[];
  for (final m in rows) {
    for (final dt in datesOf(m)) {
      pairs.add((m, dt));
    }
  }

  // 'All' groups by month for short histories, switching to YEAR buckets once the data spans more
  // than ~3 years — so a long history reads as a few year columns, not dozens of cramped months.
  var allByYear = false;
  if (period == _Period.all && pairs.isNotEmpty) {
    final earliest = pairs.map((p) => p.$2).reduce((a, b) => a.isBefore(b) ? a : b);
    final months = (today.year - earliest.year) * 12 + (today.month - earliest.month);
    allByYear = months > 36;
  }

  final sets = <int, Set<String>>{}; // bucketKey -> unique person ids (counted once per bucket)
  final raw = <(Map<String, dynamic>, DateTime, int)>[]; // (member, date, bucketKey)
  for (final (m, dt) in pairs) {
    final id = (m['person_uuid'] ?? m['name'] ?? identityHashCode(m)).toString();
    final key = _bucketKey(dt, period, allByYear: allByYear);
    (sets[key] ??= <String>{}).add(id);
    raw.add((m, dt, key));
  }

  // The ordered current window (fixed for month/year; data-spanning for all) + prev overlay.
  List<(int, String)> cur, prev;
  if (period == _Period.all) {
    if (raw.isEmpty) return (series: (labels: [], current: [], prev: []), events: []);
    final earliest = raw.map((r) => r.$2).reduce((a, b) => a.isBefore(b) ? a : b);
    cur = [];
    if (allByYear) {
      for (var y = earliest.year; y <= today.year; y++) {
        cur.add((y, '$y'));
      }
    } else {
      var y = earliest.year, mo = earliest.month;
      while (y < today.year || (y == today.year && mo <= today.month)) {
        final lbl = DateFormat(y == today.year ? 'MMM' : "MMM ''yy").format(DateTime(y, mo));
        cur.add((y * 100 + mo, lbl));
        if (++mo > 12) {
          mo = 1;
          y++;
        }
      }
    }
    prev = const [];
  } else {
    cur = _windowBuckets(period, today, 0);
    prev = _windowBuckets(period, today, 1);
  }

  final idxOf = {for (var i = 0; i < cur.length; i++) cur[i].$1: i};
  final series = (
    labels: [for (final b in cur) b.$2],
    current: [for (final b in cur) (sets[b.$1]?.length ?? 0).toDouble()],
    prev: [for (final b in prev) (sets[b.$1]?.length ?? 0).toDouble()],
  );
  final events = [
    for (final r in raw)
      if (idxOf.containsKey(r.$3)) _Ev(r.$1, r.$2, idxOf[r.$3]!),
  ];
  return (series: series, events: events);
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

/// Average Golden Hour completion per unit (#26 "which org integrates converts best"), ranked
/// high→low. n = how many baptized members in that unit.
List<({String unit, double pct, int n})> _unitCompletion(List<Map<String, dynamic>> baptized) {
  final byUnit = <String, List<Map<String, dynamic>>>{};
  for (final m in baptized) {
    (byUnit[(m['unit_name'] ?? '—').toString()] ??= []).add(m);
  }
  final out = [
    for (final e in byUnit.entries) (unit: e.key, pct: _avgCompletion(e.value), n: e.value.length)
  ];
  out.sort((a, b) => b.pct.compareTo(a.pct));
  return out;
}

/// Members who had ≥1 lesson with a member present, with that count — the drill behind the
/// Lessons-with-member stat (#38). Sorted by most member-present lessons.
List<({Map<String, dynamic> m, int count})> _membersWithMemberLessons(
    List<Map<String, dynamic>> rows) {
  final out = <({Map<String, dynamic> m, int count})>[];
  for (final m in rows) {
    final d = m['details'];
    final lessons = (d is Map ? d['lessons'] : null) as List?;
    if (lessons == null) continue;
    var c = 0;
    for (final l in lessons) {
      if (l is! Map) continue;
      final ps = (l['principles'] as List?) ?? const [];
      if (ps.any((p) => p is Map && p['memberPresent'] == true)) c++;
    }
    if (c > 0) out.add((m: m, count: c));
  }
  out.sort((a, b) => b.count.compareTo(a.count));
  return out;
}

String _ago(dynamic iso) {
  final t = DateTime.tryParse('${iso ?? ''}');
  if (t == null) return '$iso';
  final diff = DateTime.now().toUtc().difference(t.toUtc());
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}

/// Staleness color for a last-synced timestamp (#18): amber after 2 days, red after 2 weeks,
/// null (default/fresh) otherwise. Drives the freshness chip + the OPS per-stake rows.
Color? _staleColor(dynamic iso) {
  final t = DateTime.tryParse('${iso ?? ''}');
  if (t == null) return Colors.red.shade600; // never synced reads as stale
  final days = DateTime.now().toUtc().difference(t.toUtc()).inDays;
  if (days >= 14) return Colors.red.shade600;
  if (days >= 2) return Colors.amber.shade700;
  return null;
}
