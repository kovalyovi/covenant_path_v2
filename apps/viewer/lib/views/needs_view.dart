part of '../dashboard_page.dart';

/// What's left to do: a category selector along the top (one milestone selected at a time, each
/// with its own icon + outstanding count), then the *eligible* members still missing that step
/// (eligibility from golden_hour, so a child isn't listed as "needs a calling"), with a per-unit
/// summary line. Unit shown as metadata so leaders see both stake-wide and per-unit gaps.
class _NeedsView extends StatefulWidget {
  const _NeedsView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_NeedsView> createState() => _NeedsViewState();
}

class _NeedsViewState extends State<_NeedsView> {
  int? _selected; // milestone index; null until defaulted to the first category with outstanding members

  @override
  Widget build(BuildContext context) {
    final baptized = widget.rows.where((m) => m['kind'] != 'investigator').toList();
    final missingByMs = [
      for (final ms in milestones)
        baptized.where((m) => ms.eligible(m) && !ms.complete(m)).toList()
          ..sort((a, b) => '${a['name']}'.compareTo('${b['name']}')),
    ];
    final total = missingByMs.fold<int>(0, (a, l) => a + l.length);
    if (total == 0) {
      return _Page(
        tier: widget.tier,
        header: const _BigHeader(
            text: 'Needs Action', subtitle: 'Eligible members still missing each integration step'),
        child: const Padding(
            padding: EdgeInsets.all(32),
            child: Center(child: Text('Nothing outstanding — everyone eligible is on track. 🎉'))),
      );
    }
    final firstNonEmpty = missingByMs.indexWhere((l) => l.isNotEmpty);
    final sel = _selected ?? (firstNonEmpty < 0 ? 0 : firstNonEmpty);
    final ms = milestones[sel];
    final missing = missingByMs[sel];

    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const _BigHeader(
            text: 'Needs Action', subtitle: 'Eligible members still missing each integration step'),
        const SizedBox(height: 12),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (var i = 0; i < milestones.length; i++) ...[
              if (i > 0) const SizedBox(width: 8),
              _CategoryChip(
                ms: milestones[i],
                count: missingByMs[i].length,
                selected: i == sel,
                onTap: () => setState(() => _selected = i),
              ),
            ],
          ]),
        ),
      ]),
      child: _Columns(cols: 1, children: [_categorySection(context, ms, missing)]),
    );
  }

  Widget _categorySection(BuildContext context, Milestone ms, List<Map<String, dynamic>> missing) {
    final byUnit = <String, int>{};
    for (final m in missing) {
      final u = (m['unit_name'] ?? '—').toString();
      byUnit[u] = (byUnit[u] ?? 0) + 1;
    }
    final unitParts = (byUnit.entries.toList()..sort((a, b) => b.value.compareTo(a.value)))
        .map((e) => '${e.key} ${e.value}')
        .join('   ·   ');
    return SectionCard(
      title: 'Needs ${ms.label}',
      leadingIcon: ms.icon,
      trailing: _CountBadge(missing.length),
      child: missing.isEmpty
          ? const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Text('Everyone eligible has this. 🎉'))
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(unitParts,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
              const Divider(),
              for (var i = 0; i < missing.length; i++) ...[
                if (i > 0) const Divider(height: 1),
                _MemberRow(m: missing[i], onOpen: widget.onOpen, showUnit: true),
              ],
            ]),
    );
  }
}

/// A category selector chip for the Needs view: icon + label + outstanding-count badge; filled
/// when selected. Count 0 renders dimmed (that category is fully done).
class _CategoryChip extends StatelessWidget {
  const _CategoryChip(
      {required this.ms, required this.count, required this.selected, required this.onTap});
  final Milestone ms;
  final int count;
  final bool selected;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final done = count == 0;
    final fg = selected ? c.onPrimary : (done ? c.onSurfaceVariant.withValues(alpha: 0.6) : c.onSurfaceVariant);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          color: selected ? c.primary : c.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(done ? Icons.check_circle : ms.icon, size: 17, color: fg),
          const SizedBox(width: 7),
          Text(ms.label, style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: 13)),
          if (!done) ...[
            const SizedBox(width: 7),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1),
              decoration: BoxDecoration(
                color: selected ? c.onPrimary.withValues(alpha: 0.25) : c.primary.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text('$count',
                  style: TextStyle(
                      color: selected ? c.onPrimary : c.primary,
                      fontWeight: FontWeight.bold,
                      fontSize: 12)),
            ),
          ],
        ]),
      ),
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
