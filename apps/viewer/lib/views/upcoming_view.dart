part of '../dashboard_page.dart';

/// People being taught who have a *planned* (future) baptism date — the missionary
/// "baptismGoalDate". Sorted soonest-first; the date shown is the goal, not an actual baptism.
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
    final dated = widget.rows
        .where((m) => m['kind'] == 'investigator' && parseMemberDate(m['baptism_goal_date']) != null)
        .toList();
    return _Page(
      tier: widget.tier,
      header: _SectionTitle(title: 'Prospective Baptisms', count: dated.length, byDate: _byDate,
          onToggle: (v) => setState(() => _byDate = v)),
      child: dated.isEmpty
          ? const Padding(padding: EdgeInsets.all(32),
              child: Center(child: Text('No prospective baptisms with a planned date.')))
          : (_byDate
              ? _UpcomingCalendar(rows: dated, onOpen: widget.onOpen)
              : _UnitGrid(rows: dated, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                  dateField: 'baptism_goal_date', ascending: true)),
    );
  }
}

/// Prospective baptisms as a calendar (this month + next, if any) with today highlighted and
/// baptism days marked, then a compact list. Dates beyond the two months go in a "Later" list.
/// Kept narrow on purpose.
class _UpcomingCalendar extends StatelessWidget {
  const _UpcomingCalendar({required this.rows, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onOpen;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final items = <({Map<String, dynamic> m, DateTime date})>[];
    for (final m in rows) {
      final d = parseMemberDate(m['baptism_goal_date']);
      if (d != null) items.add((m: m, date: DateTime(d.year, d.month, d.day)));
    }
    items.sort((a, b) => a.date.compareTo(b.date));
    final thisM = DateTime(now.year, now.month);
    final nextM = DateTime(now.year, now.month + 1);
    bool inMonth(DateTime d, DateTime mo) => d.year == mo.year && d.month == mo.month;
    final inCal = items.where((i) => inMonth(i.date, thisM) || inMonth(i.date, nextM)).toList();
    final later = items.where((i) => !inCal.contains(i)).toList();
    final byDay = <DateTime, int>{};
    for (final i in inCal) {
      byDay[i.date] = (byDay[i.date] ?? 0) + 1;
    }
    final showNext = inCal.any((i) => inMonth(i.date, nextM));

    Widget row(({Map<String, dynamic> m, DateTime date}) i) => ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: PhotoAvatar(
              name: i.m['name']?.toString() ?? '?', photoUrl: i.m['photo_url']?.toString(), size: 38),
          title: Text(i.m['name']?.toString() ?? '—',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text('${i.m['unit_name'] ?? ''} · ${fmtLong(i.date)}',
              style: Theme.of(context).textTheme.bodySmall),
          onTap: () => onOpen(i.m),
        );

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Column(children: [
          _MonthGrid(month: thisM, today: today, byDay: byDay),
          if (showNext) _MonthGrid(month: nextM, today: today, byDay: byDay),
          if (inCal.isNotEmpty)
            SectionCard(
                title: 'This & next month',
                leadingIcon: Icons.event_available,
                child: Column(children: [for (final i in inCal) row(i)])),
          if (later.isNotEmpty)
            SectionCard(
                title: 'Later',
                leadingIcon: Icons.update,
                child: Column(children: [for (final i in later) row(i)])),
        ]),
      ),
    );
  }
}

/// A compact month grid; days with a baptism are tinted (with a count dot), today gets a ring.
class _MonthGrid extends StatelessWidget {
  const _MonthGrid({required this.month, required this.today, required this.byDay});
  final DateTime month; // year/month (day ignored)
  final DateTime today;
  final Map<DateTime, int> byDay;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final daysInMonth = DateTime(month.year, month.month + 1, 0).day;
    final lead = DateTime(month.year, month.month, 1).weekday % 7; // Sun=0 .. Sat=6
    final cells = <Widget?>[for (var i = 0; i < lead; i++) null];
    for (var d = 1; d <= daysInMonth; d++) {
      cells.add(_dayCell(context, DateTime(month.year, month.month, d)));
    }
    while (cells.length % 7 != 0) {
      cells.add(null);
    }
    return SectionCard(
      title: DateFormat('MMMM y').format(month),
      leadingIcon: Icons.calendar_month,
      child: Column(children: [
        Row(children: [
          for (final w in const ['S', 'M', 'T', 'W', 'T', 'F', 'S'])
            Expanded(
                child: Center(
                    child: Text(w,
                        style: TextStyle(fontSize: 11, color: c.onSurfaceVariant)))),
        ]),
        const SizedBox(height: 4),
        for (var r = 0; r < cells.length / 7; r++)
          Row(children: [
            for (var k = 0; k < 7; k++)
              Expanded(child: cells[r * 7 + k] ?? const SizedBox(height: 40)),
          ]),
      ]),
    );
  }

  Widget _dayCell(BuildContext context, DateTime day) {
    final c = Theme.of(context).colorScheme;
    final count = byDay[day] ?? 0;
    final isToday = day == today;
    return Container(
      height: 40,
      margin: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: count > 0 ? c.primary.withValues(alpha: 0.14) : null,
        borderRadius: BorderRadius.circular(8),
        border: isToday ? Border.all(color: c.primary, width: 1.6) : null,
      ),
      child: Stack(alignment: Alignment.center, children: [
        Text('${day.day}',
            style: TextStyle(
                fontWeight: count > 0 || isToday ? FontWeight.bold : FontWeight.normal,
                color: count > 0 ? c.primary : null)),
        if (count > 0)
          Positioned(
            bottom: 3,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 5),
              decoration: BoxDecoration(color: c.primary, borderRadius: BorderRadius.circular(8)),
              child: Text('$count',
                  style: TextStyle(color: c.onPrimary, fontSize: 9, fontWeight: FontWeight.bold)),
            ),
          ),
      ]),
    );
  }
}

// ---- Golden Hour ------------------------------------------------------------
