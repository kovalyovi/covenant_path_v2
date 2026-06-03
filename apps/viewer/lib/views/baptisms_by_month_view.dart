part of '../dashboard_page.dart';

/// Dedicated "By Month" tab (the last tab): baptized-convert counts by baptism month, with its own
/// window filter that defaults to year-to-date. Adds a stake-wide unit filter on top of the card's
/// own YTD / 12 mo / 24 mo / All window. The chart, stats and by-unit drill come from the reusable
/// `_BaptismsCard` (so this view and any other consumer stay in sync).
class _BaptismsByMonthView extends StatefulWidget {
  const _BaptismsByMonthView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_BaptismsByMonthView> createState() => _BaptismsByMonthViewState();
}

class _BaptismsByMonthViewState extends State<_BaptismsByMonthView> {
  String? _unit; // null = whole stake; else drill into one unit

  @override
  Widget build(BuildContext context) {
    final units = (widget.rows
        .map((m) => '${m['unit_name'] ?? ''}')
        .where((u) => u.isNotEmpty)
        .toSet()
        .toList()
      ..sort());
    final scoped =
        _unit == null ? widget.rows : widget.rows.where((m) => m['unit_name'] == _unit).toList();
    final baptized = scoped.where((m) => m['kind'] != 'investigator').toList();
    final allUnits = scoped.map((m) => '${m['unit_name'] ?? '—'}').toSet();

    return _Page(
      tier: widget.tier,
      header: Row(children: [
        const Expanded(
            child: _BigHeader(
                text: 'Baptisms by Month', subtitle: 'Baptized & confirmed converts')),
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
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          // _BaptismsCard owns the window selector (defaults to YTD) + chart + by-unit drill.
          child: _BaptismsCard(baptized: baptized, allUnits: allUnits, onOpen: widget.onOpen),
        ),
      ),
    );
  }
}
