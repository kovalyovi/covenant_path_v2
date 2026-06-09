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
  bool _ascending = true; // baptism date order: oldest-baptized (most overdue) first by default
  // Org-ownership filter (same model as Golden Hour): which orgs' converts to show, all on by
  // default; tap a chip to toggle, "Clear filters" restores all. (#needs-org)
  final Set<OrgBucket> _orgs = {...OrgBucket.values};

  void _toggleOrg(OrgBucket b) => setState(() {
        if (_orgs.contains(b)) {
          if (_orgs.length > 1) _orgs.remove(b);
        } else {
          _orgs.add(b);
        }
      });

  /// Sort the "still need" list by baptism date, then unit (#feedback), honoring asc/desc.
  int _cmp(Map<String, dynamic> a, Map<String, dynamic> b) {
    final da = parseMemberDate(a['baptism_date']), db = parseMemberDate(b['baptism_date']);
    int c;
    if (da == null && db == null) {
      c = 0;
    } else if (da == null) {
      c = 1;
    } else if (db == null) {
      c = -1;
    } else {
      c = da.compareTo(db);
    }
    if (c == 0) c = '${a['unit_name'] ?? ''}'.compareTo('${b['unit_name'] ?? ''}');
    return _ascending ? c : -c;
  }

  @override
  Widget build(BuildContext context) {
    final all = widget.rows.where((m) => m['kind'] != 'investigator').toList();
    // Org-ownership filter (same buckets/colors as Golden Hour): a convert's integration is owned
    // by missionaries/WML (first year) then EQ/RS — so a leader can see who needs Friends among the
    // people THEIR org now watches over, per unit. All orgs on by default. (#needs-org)
    final allOrgs = _orgs.length == OrgBucket.values.length;
    final baptized =
        allOrgs ? all : all.where((m) => _orgs.contains(responsibleOrg(m))).toList();
    final missingByMs = [
      for (final ms in milestones)
        baptized.where((m) => ms.eligible(m) && !ms.complete(m)).toList()..sort(_cmp),
    ];
    final total = missingByMs.fold<int>(0, (a, l) => a + l.length);

    // Shown in BOTH the empty + populated states, so a filter is never a dead end.
    final orgFilter = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SizedBox(height: 10),
      _OrgFilterBar(selected: _orgs, onToggle: _toggleOrg,
          onClear: () => setState(() => _orgs..clear()..addAll(OrgBucket.values))),
      if (!allOrgs && _orgs.length == 1) ...[
        const SizedBox(height: 6),
        _SubtleNote(orgResponsibilityNote(_orgs.first)),
      ],
    ]);

    if (total == 0) {
      return _Page(
        tier: widget.tier,
        header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const _BigHeader(
              text: 'Needs Action', subtitle: 'Eligible members still missing each integration step'),
          orgFilter,
        ]),
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Center(
              child: Text(
                  allOrgs
                      ? 'Nothing outstanding — everyone eligible is on track. 🎉'
                      : 'Nothing outstanding for the selected orgs. 🎉',
                  textAlign: TextAlign.center)),
        ),
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
        orgFilter,
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
        Row(children: [
          Icon(Icons.sort, size: 15, color: Colors.grey.shade600),
          const SizedBox(width: 6),
          Text('Baptism date, then unit',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          IconButton(
            tooltip: _ascending ? 'Oldest first (tap for newest)' : 'Newest first (tap for oldest)',
            visualDensity: VisualDensity.compact,
            icon: Icon(_ascending ? Icons.arrow_upward : Icons.arrow_downward, size: 18),
            onPressed: () => setState(() => _ascending = !_ascending),
          ),
        ]),
      ]),
      child: _Columns(cols: 1,
          children: [_categorySection(context, ms, missing, _assignUnitColors(widget.rows))]),
    );
  }

  Widget _categorySection(BuildContext context, Milestone ms, List<Map<String, dynamic>> missing,
      Map<String, Color> unitColors) {
    final byUnit = <String, int>{};
    for (final m in missing) {
      final u = (m['unit_name'] ?? '—').toString();
      byUnit[u] = (byUnit[u] ?? 0) + 1;
    }
    final units = byUnit.entries.toList()..sort((a, b) => b.value.compareTo(a.value));
    return SectionCard(
      title: 'Needs ${ms.label}',
      leadingIcon: ms.icon,
      iconColor: ms.color, // category identity color on the card icon
      trailing: _CountBadge(missing.length),
      child: missing.isEmpty
          ? const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Text('Everyone eligible has this. 🎉'))
          : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // per-unit breakdown as colored chips (each ward a stable color) (#ward-colors)
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final e in units)
                  _UnitCountChip(unit: e.key, count: e.value,
                      color: unitColors[e.key] ?? _unitColor(e.key)),
              ]),
              const Divider(),
              for (var i = 0; i < missing.length; i++) ...[
                if (i > 0) const Divider(height: 1),
                _MemberRow(m: missing[i], onOpen: widget.onOpen, showUnit: true, showResp: true),
              ],
            ]),
    );
  }
}

/// A small colored chip for a unit's outstanding count in the Needs breakdown. Each ward gets a
/// stable color (hash → fixed palette) so a unit reads the same hue wherever it appears.
class _UnitCountChip extends StatelessWidget {
  const _UnitCountChip({required this.unit, required this.count, required this.color});
  final String unit;
  final int count;
  final Color color;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text('$unit · $count',
          style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600)),
    );
  }
}

// A fixed, calm palette for per-unit accents — distinct from the status/org/nav colors. 16 hues so a
// stake's wards each get their own color (assigned by sorted index via [_assignUnitColors], not by
// hash — hashCode % N produced near-duplicate ward colors when names collided on the modulus).
const _unitPalette = <Color>[
  Color(0xFF00695C), Color(0xFF4527A0), Color(0xFFAD1457), Color(0xFF283593),
  Color(0xFF558B2F), Color(0xFF6D4C41), Color(0xFF00838F), Color(0xFFC62828),
  Color(0xFFEF6C00), Color(0xFF1565C0), Color(0xFF8E24AA), Color(0xFF2E7D32),
  Color(0xFF827717), Color(0xFF006064), Color(0xFFBF360C), Color(0xFF37474F),
];

/// Each distinct unit → its own palette color by SORTED INDEX, so every ward reads as a different
/// hue (stable across categories/org filters). Wraps the palette only if a stake has >16 units.
Map<String, Color> _assignUnitColors(List<Map<String, dynamic>> rows) {
  final units = rows.map((m) => (m['unit_name'] ?? '—').toString()).toSet().toList()..sort();
  return {for (var i = 0; i < units.length; i++) units[i]: _unitPalette[i % _unitPalette.length]};
}

/// Fallback when the full unit set isn't handy (a lone chip).
Color _unitColor(String unit) => _unitPalette[unit.hashCode.abs() % _unitPalette.length];

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
    final done = count == 0;
    // each category carries its own identity color (ms.color); a completed category reads muted.
    final base = done ? Colors.grey.shade500 : ms.color;
    final fg = selected ? Colors.white : base;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(20),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          color: selected ? base : base.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: base.withValues(alpha: selected ? 1 : 0.35)),
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
                color: selected
                    ? Colors.white.withValues(alpha: 0.25)
                    : base.withValues(alpha: 0.16),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text('$count',
                  style: TextStyle(color: fg, fontWeight: FontWeight.bold, fontSize: 12)),
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
      this.showResp = false, this.dateField = 'baptism_date'});
  final Map<String, dynamic> m;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final bool showUnit;
  final bool showResp; // show the responsible-org chip even without the milestone chips (Needs view)
  final String dateField;

  @override
  Widget build(BuildContext context) {
    final name = m['name']?.toString() ?? '—';
    final date = parseMemberDate(m[dateField]);
    final age = ageOf(m);
    final isBaptism = dateField == 'baptism_date';
    final resp = (chips || showResp) ? responsibleParty(m) : null; // ownership applies to baptized converts
    final sub = Theme.of(context).textTheme.bodySmall;
    // #12: on a phone, the name gets the whole first row and the age drops to the line below (in the
    // subtitle) instead of riding as a cramped "second column" — sharper, more readable. On wider
    // screens the name + age stay inline.
    final isMobile = MediaQuery.sizeOf(context).width < 600;
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      onTap: () => onOpen(m),
      leading: PhotoAvatar(name: name, photoUrl: m['photo_url']?.toString(), size: 44),
      title: (isMobile || age == null)
          ? Text(name, style: const TextStyle(fontWeight: FontWeight.w600))
          : Row(children: [
              Flexible(child: Text(name, style: const TextStyle(fontWeight: FontWeight.w600))),
              const SizedBox(width: 6),
              Text('· $age', style: TextStyle(color: Colors.grey.shade600, fontSize: 13)),
            ]),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (isMobile && age != null)
          Text(age, style: TextStyle(color: Colors.grey.shade600, fontSize: 12.5)),
        if (date != null)
          Row(children: [
            Icon(isBaptism ? Icons.water_drop : Icons.event,
                size: 13, color: isBaptism ? Colors.lightBlue.shade600 : Colors.grey.shade600),
            const SizedBox(width: 4),
            // Baptism: "February 6, 2026 (2 months 3 days)" so tenure is visible at a glance.
            Flexible(
                child: Text(
                    isBaptism
                        ? '${DateFormat('MMMM d, y').format(date)}'
                            '${monthsDaysAgo(date).isNotEmpty ? ' (${monthsDaysAgo(date)})' : ''}'
                        : fmtLong(date),
                    style: sub)),
          ]),
        if (resp != null) ...[
          const SizedBox(height: 4),
          Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(resp.icon, size: 13, color: resp.color),
            const SizedBox(width: 4),
            Text(resp.label, style: sub?.copyWith(color: resp.color)),
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
