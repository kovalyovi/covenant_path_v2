part of '../dashboard_page.dart';

/// What's left to do: for each integration milestone, the *eligible* members still missing it
/// (eligibility from golden_hour, so a child isn't listed as "needs a calling"). Unit shown as
/// metadata so leaders can see both stake-wide and per-unit gaps.
class _NeedsView extends StatelessWidget {
  const _NeedsView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;

  @override
  Widget build(BuildContext context) {
    final baptized = rows.where((m) => m['kind'] != 'investigator').toList();
    final sections = <Widget>[];
    for (final ms in milestones) {
      final missing = baptized
          .where((m) => milestonesFor(m).contains(ms) && !ms.complete(m))
          .toList()
        ..sort((a, b) => (a['name'] ?? '').toString().compareTo((b['name'] ?? '').toString()));
      if (missing.isEmpty) continue;
      sections.add(SectionCard(
        title: 'Needs ${ms.label}',
        leadingIcon: Icons.flag_outlined,
        trailing: _CountBadge(missing.length),
        child: Column(children: [
          for (var i = 0; i < missing.length; i++) ...[
            if (i > 0) const Divider(height: 1),
            _MemberRow(m: missing[i], onOpen: onOpen, showUnit: true),
          ],
        ]),
      ));
    }
    return _Page(
      tier: tier,
      header: const _BigHeader(
          text: 'Needs Action',
          subtitle: 'Eligible members still missing each integration step'),
      child: sections.isEmpty
          ? const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: Text('Nothing outstanding — everyone eligible is on track.')))
          : _Columns(cols: _cols(tier).clamp(1, 2), children: sections),
    );
  }
}

// ---- shared list layouts ----------------------------------------------------

/// Cards grouped by unit (unit name as the card title) — laid out in 1/2/3 columns by tier.
class _UnitGrid extends StatelessWidget {
  const _UnitGrid({required this.rows, required this.tier, required this.onOpen, required this.chips,
      this.dateField = 'baptism_date', this.ascending = false});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final String dateField;
  final bool ascending;

  @override
  Widget build(BuildContext context) {
    final groups = _groupByUnit(rows, dateField: dateField, ascending: ascending);
    final cards = [
      for (final g in groups)
        SectionCard(
          title: g.$1,
          trailing: _CountBadge(g.$2.length),
          child: Column(children: [
            for (var i = 0; i < g.$2.length; i++) ...[
              if (i > 0) const Divider(height: 1),
              _MemberRow(m: g.$2[i], onOpen: onOpen, chips: chips, dateField: dateField),
            ],
          ]),
        ),
    ];
    return _Columns(cols: _cols(tier), children: cards);
  }
}

/// Flat list sorted by date; the unit is shown as right-side metadata. [ascending] puts the
/// soonest planned date first (prospective baptisms); otherwise newest-first (recent baptisms).
class _DateList extends StatelessWidget {
  const _DateList({required this.rows, required this.tier, required this.onOpen, required this.chips,
      this.dateField = 'baptism_date', this.ascending = false});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final String dateField;
  final bool ascending;

  @override
  Widget build(BuildContext context) {
    final sorted = [...rows]..sort((a, b) {
        final da = parseMemberDate(a[dateField]), db = parseMemberDate(b[dateField]);
        if (da == null) return 1;
        if (db == null) return -1;
        return ascending ? da.compareTo(db) : db.compareTo(da);
      });
    final card = SectionCard(
      title: 'By date',
      child: Column(children: [
        for (var i = 0; i < sorted.length; i++) ...[
          if (i > 0) const Divider(height: 1),
          _MemberRow(m: sorted[i], onOpen: onOpen, chips: chips, showUnit: true,
              dateField: dateField),
        ],
      ]),
    );
    // a flat list reads best in a single capped column even on wide screens
    return _Columns(cols: 1, children: [card]);
  }
}

class _MemberRow extends StatelessWidget {
  const _MemberRow(
      {required this.m, required this.onOpen, this.chips = false, this.showUnit = false,
      this.dateField = 'baptism_date'});
  final Map<String, dynamic> m;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final bool showUnit;
  final String dateField;

  @override
  Widget build(BuildContext context) {
    final name = m['name']?.toString() ?? '—';
    final date = parseMemberDate(m[dateField]);
    final age = ageOf(m);
    final isBaptism = dateField == 'baptism_date';
    final resp = chips ? responsibleParty(m) : null; // ownership applies to baptized converts
    final sub = Theme.of(context).textTheme.bodySmall;
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      onTap: () => onOpen(m),
      leading: PhotoAvatar(name: name, photoUrl: m['photo_url']?.toString(), size: 44),
      title: Row(children: [
        Flexible(child: Text(name, style: const TextStyle(fontWeight: FontWeight.w600))),
        if (age != null) ...[
          const SizedBox(width: 6),
          Text('· $age', style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
        ],
      ]),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (date != null)
          Row(children: [
            Icon(isBaptism ? Icons.water_drop : Icons.event,
                size: 13, color: isBaptism ? Colors.lightBlue.shade600 : Colors.grey.shade600),
            const SizedBox(width: 4),
            Flexible(child: Text(fmtLong(date), style: sub)),
          ]),
        if (resp != null) ...[
          const SizedBox(height: 4),
          Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(resp.icon, size: 13, color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 4),
            Text(resp.label, style: sub?.copyWith(color: Theme.of(context).colorScheme.primary)),
          ]),
        ],
        if (chips) ...[const SizedBox(height: 6), GoldenHourChips(member: m, size: 22, highlightNext: true)],
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
