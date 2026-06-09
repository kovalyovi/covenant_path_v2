part of '../dashboard_page.dart';

/// People being taught who have a *planned* (future) baptism date — the missionary
/// "baptismGoalDate". Two presentations (the header toggle): a combined date timeline, or the same
/// timeline split per unit. Either way, dates already passed (still not baptized) surface in a
/// "needs attention — overdue" block on top; genuinely upcoming dates follow.
class _OnDateView extends StatefulWidget {
  const _OnDateView(
      {required this.rows, required this.tier, required this.onOpen, this.missionaries = const {}});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final Map<String, List<Map<String, dynamic>>> missionaries; // unit name → assigned missionaries
  @override
  State<_OnDateView> createState() => _OnDateViewState();
}

typedef _Dated = ({Map<String, dynamic> m, DateTime date});

class _OnDateViewState extends State<_OnDateView> {
  bool _byUnit = false; // header toggle: combined timeline (false) vs per-unit timelines (true)

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final items = <_Dated>[];
    for (final m in widget.rows) {
      if (m['kind'] != 'investigator') continue;
      final d = parseMemberDate(m['baptism_goal_date']);
      if (d != null) items.add((m: m, date: DateTime(d.year, d.month, d.day)));
    }
    items.sort((a, b) => a.date.compareTo(b.date));

    return _Page(
      tier: widget.tier,
      // _SectionTitle's toggle is Unit(false)/Date(true); map it to _byUnit.
      header: _SectionTitle(
          title: 'Prospective Baptisms',
          count: items.length,
          byDate: !_byUnit,
          onToggle: (v) => setState(() => _byUnit = !v)),
      child: items.isEmpty
          ? const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: Text('No prospective baptisms with a planned date.')))
          : (_byUnit ? _perUnit(today, items) : _combined(today, items)),
    );
  }

  Widget _combined(DateTime today, List<_Dated> items) => Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: _Timeline(items: items, today: today, onOpen: widget.onOpen),
        ),
      );

  Widget _perUnit(DateTime today, List<_Dated> items) {
    final byUnit = <String, List<_Dated>>{};
    for (final i in items) {
      (byUnit[(i.m['unit_name'] ?? '—').toString()] ??= []).add(i);
    }
    final units = byUnit.keys.toList()..sort();
    return _Columns(
      cols: _cols(widget.tier).clamp(1, 2),
      children: [
        for (final u in units)
          SectionCard(
            title: u,
            leadingIcon: Icons.groups,
            trailing: _CountBadge(byUnit[u]!.length),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if ((widget.missionaries[u] ?? const []).isNotEmpty) ...[
                _MissionaryStrip(missionaries: widget.missionaries[u]!),
                const Divider(height: 18),
              ],
              _Timeline(items: byUnit[u]!, today: today, onOpen: widget.onOpen, embedded: true),
            ]),
          ),
      ],
    );
  }
}

/// The baptism timeline: an overdue block ("needs attention") then an upcoming block, each a
/// date-rail list (month/day on the left, the people on that date on the right). [embedded] drops
/// the outer cards so it can live inside a per-unit card.
class _Timeline extends StatelessWidget {
  const _Timeline(
      {required this.items, required this.today, required this.onOpen, this.embedded = false});
  final List<_Dated> items;
  final DateTime today;
  final void Function(Map<String, dynamic>) onOpen;
  final bool embedded;

  @override
  Widget build(BuildContext context) {
    final overdue = items.where((i) => i.date.isBefore(today)).toList();
    final upcoming = items.where((i) => !i.date.isBefore(today)).toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (overdue.isNotEmpty)
        _DateSection(
          title: 'Needs attention — date passed',
          icon: Icons.warning_amber_rounded,
          color: Colors.orange.shade800,
          items: overdue,
          today: today,
          overdue: true,
          onOpen: onOpen,
          embedded: embedded,
        ),
      if (upcoming.isNotEmpty)
        _DateSection(
          title: 'Scheduled',
          icon: Icons.event_available,
          color: Theme.of(context).colorScheme.primary,
          items: upcoming,
          today: today,
          overdue: false,
          onOpen: onOpen,
          embedded: embedded,
        ),
      if (upcoming.isEmpty && overdue.isEmpty)
        const Padding(padding: EdgeInsets.all(16), child: Text('No planned dates.')),
    ]);
  }
}

class _DateSection extends StatelessWidget {
  const _DateSection(
      {required this.title,
      required this.icon,
      required this.color,
      required this.items,
      required this.today,
      required this.overdue,
      required this.onOpen,
      required this.embedded});
  final String title;
  final IconData icon;
  final Color color;
  final List<_Dated> items;
  final DateTime today;
  final bool overdue;
  final void Function(Map<String, dynamic>) onOpen;
  final bool embedded;

  @override
  Widget build(BuildContext context) {
    final byDate = <DateTime, List<_Dated>>{};
    for (final i in items) {
      (byDate[i.date] ??= []).add(i);
    }
    final dates = byDate.keys.toList()..sort(); // soonest first (overdue: oldest-passed first)
    final rail = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var di = 0; di < dates.length; di++) ...[
        if (di > 0) Divider(height: 18, color: Theme.of(context).colorScheme.outlineVariant),
        _DateRow(
            date: dates[di], people: byDate[dates[di]]!, today: today, overdue: overdue, onOpen: onOpen),
      ],
    ]);
    if (embedded) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SizedBox(height: 4),
        Row(children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 6),
          Text(title, style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 13)),
        ]),
        const SizedBox(height: 8),
        rail,
        const SizedBox(height: 6),
      ]);
    }
    return SectionCard(title: title, leadingIcon: icon, iconColor: color, child: rail);
  }
}

/// One date in the rail: a month/day block on the left, the people planned for that day on the right.
class _DateRow extends StatelessWidget {
  const _DateRow(
      {required this.date,
      required this.people,
      required this.today,
      required this.overdue,
      required this.onOpen});
  final DateTime date;
  final List<_Dated> people;
  final DateTime today;
  final bool overdue;
  final void Function(Map<String, dynamic>) onOpen;

  @override
  Widget build(BuildContext context) {
    final accent = overdue ? Colors.orange.shade800 : Theme.of(context).colorScheme.primary;
    final days = date.difference(today).inDays;
    final rel = overdue
        ? '${-days} day${days == -1 ? '' : 's'} ago'
        : (days == 0 ? 'Today' : (days == 1 ? 'Tomorrow' : 'in $days days'));
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(
        width: 54,
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(
            color: accent.withValues(alpha: 0.10), borderRadius: BorderRadius.circular(10)),
        child: Column(children: [
          Text(DateFormat('MMM').format(date).toUpperCase(),
              style: TextStyle(fontSize: 11, color: accent, fontWeight: FontWeight.w700)),
          Text('${date.day}',
              style: TextStyle(fontSize: 22, height: 1.0, color: accent, fontWeight: FontWeight.bold)),
          Text(DateFormat('EEE').format(date),
              style: TextStyle(fontSize: 10, color: Colors.grey.shade600)),
        ]),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.only(top: 3, bottom: 1),
            child: Text(rel,
                style: TextStyle(
                    fontSize: 11,
                    color: overdue ? accent : Colors.grey.shade600,
                    fontWeight: FontWeight.w600)),
          ),
          for (final p in people)
            InkWell(
              onTap: () => onOpen(p.m),
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(children: [
                  PhotoAvatar(
                      name: p.m['name']?.toString() ?? '?',
                      photoUrl: p.m['photo_url']?.toString(),
                      size: 36),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(p.m['name']?.toString() ?? '—',
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text(p.m['unit_name']?.toString() ?? '',
                          style: TextStyle(fontSize: 12, color: Colors.grey.shade600)),
                    ]),
                  ),
                  const Icon(Icons.chevron_right, size: 18),
                ]),
              ),
            ),
        ]),
      ),
    ]);
  }
}

/// The full-time missionaries assigned to a unit (#29): name chips; tap-and-hold shows phone/email.
class _MissionaryStrip extends StatelessWidget {
  const _MissionaryStrip({required this.missionaries});
  final List<Map<String, dynamic>> missionaries;
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(Icons.volunteer_activism, size: 16, color: c.primary),
      const SizedBox(width: 6),
      Expanded(
        child: Wrap(spacing: 6, runSpacing: 6, children: [
          for (final m in missionaries)
            Tooltip(
              triggerMode: TooltipTriggerMode.tap,
              message: [m['phone'], m['email']]
                  .where((x) => x != null && '$x'.isNotEmpty)
                  .join('\n'),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(
                  color: c.primary.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Text('${m['name'] ?? ''}',
                    style: TextStyle(fontSize: 12, color: c.primary, fontWeight: FontWeight.w500)),
              ),
            ),
        ]),
      ),
    ]);
  }
}

// ---- Golden Hour ------------------------------------------------------------
