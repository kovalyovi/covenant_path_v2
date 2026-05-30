part of '../dashboard_page.dart';

class _SpreadsheetView extends StatefulWidget {
  const _SpreadsheetView({required this.rows, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onOpen;

  // (header, member key, kind) — kind drives the conditional color.
  static const _cols = <(String, String, String)>[
    ('Member', 'name', 'text'),
    ('Unit', 'unit_name', 'text'),
    ('Baptism', 'baptism_date', 'text'),
    ('Member for', 'membership_duration', 'text'),
    ('Friends', 'friends', 'yesno'),
    ('Aaronic', 'aaronic_priesthood', 'yesno'),
    ('Melch.', 'melchizedek_priesthood', 'yesno'),
    ('Calling', 'calling', 'yesno'),
    ('Has min.', 'ministering_brothers_sisters', 'yesno'),
    ('Gives min.', 'ministering_assignment', 'yesno'),
    ('Recommend', 'temple_recommend', 'recommend'),
    ('Patriarchal', 'patriarchal_blessing', 'yesno'),
    ('Endowed', 'living_ordinance', 'yesno'),
  ];

  @override
  State<_SpreadsheetView> createState() => _SpreadsheetViewState();
}

class _SpreadsheetViewState extends State<_SpreadsheetView> {
  String? _field; // member key to filter on (null = no filter)
  bool _has = false; // true = has it, false = missing it
  int? _sortCol; // column index to sort by (null = stable default order)
  bool _sortAsc = true;

  static const _yes = {'Yes', 'Active'};

  /// Display value — strips the redundant "Member for " prefix (header already says it). (#31)
  static String _display(Map<String, dynamic> m, String key) {
    final v = '${m[key] ?? ''}';
    return key == 'membership_duration'
        ? v.replaceFirst(RegExp(r'^Member for\s*', caseSensitive: false), '')
        : v;
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context);
    // baptized only (investigators live in Upcoming / Golden Hour › Being Taught)
    var rows = widget.rows.where((m) => m['kind'] != 'investigator').toList();
    if (_field != null) {
      rows = rows.where((m) {
        final v = '${m[_field] ?? ''}';
        if (v.isEmpty || v == 'N/A') return false; // N/A = not applicable, exclude from both
        return _has ? _yes.contains(v) : !_yes.contains(v);
      }).toList();
    }
    if (_sortCol != null) {
      final key = _SpreadsheetView._cols[_sortCol!].$2;
      rows.sort((a, b) {
        final c = _display(a, key).toLowerCase().compareTo(_display(b, key).toLowerCase());
        return _sortAsc ? c : -c;
      });
    }
    final filterable = _SpreadsheetView._cols.where((c) => c.$3 != 'text').toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
        child: Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          const Text('Filter:'),
          DropdownButton<String?>(
            value: _field,
            hint: const Text('field'),
            items: [
              const DropdownMenuItem(value: null, child: Text('All members')),
              for (final c in filterable) DropdownMenuItem(value: c.$2, child: Text(c.$1)),
            ],
            onChanged: (v) => setState(() => _field = v),
          ),
          if (_field != null)
            SegmentedButton<bool>(
              showSelectedIcon: false,
              style: const ButtonStyle(visualDensity: VisualDensity.compact),
              segments: const [
                ButtonSegment(value: false, label: Text('Missing')),
                ButtonSegment(value: true, label: Text('Has')),
              ],
              selected: {_has},
              onSelectionChanged: (s) => setState(() => _has = s.first),
            ),
          Text('${rows.length} member${rows.length == 1 ? '' : 's'}',
              style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
      Expanded(
        child: SingleChildScrollView(
          scrollDirection: Axis.vertical,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              showCheckboxColumn: false, // #33: no bulk-select / select-all; rows open individually
              sortColumnIndex: _sortCol,
              sortAscending: _sortAsc,
              headingRowColor: WidgetStatePropertyAll(scheme.colorScheme.primary),
              headingTextStyle:
                  TextStyle(color: scheme.colorScheme.onPrimary, fontWeight: FontWeight.bold),
              headingRowHeight: 44,
              dataRowMinHeight: 40,
              dataRowMaxHeight: 48,
              columnSpacing: 18,
              columns: [
                for (var i = 0; i < _SpreadsheetView._cols.length; i++)
                  DataColumn(
                    label: Text(_SpreadsheetView._cols[i].$1),
                    onSort: (col, asc) => setState(() {
                      _sortCol = col;
                      _sortAsc = asc;
                    }),
                  ),
              ],
              rows: [
                for (final m in rows)
                  DataRow(
                    onSelectChanged: (_) => widget.onOpen(m),
                    cells: [
                      for (final c in _SpreadsheetView._cols)
                        _cell(_SpreadsheetViewState._display(m, c.$2), c.$3)
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    ]);
  }

  DataCell _cell(String value, String kind) {
    final color = _cellColor(value, kind);
    if (color == null) return DataCell(Text(value));
    return DataCell(Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(6)),
      child: Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
    ));
  }

  static Color? _cellColor(String v, String kind) {
    final green = Colors.green.shade100, red = Colors.red.shade100, grey = Colors.grey.shade200;
    if (kind == 'yesno') {
      if (v == 'Yes') return green;
      if (v == 'No') return red;
      if (v == 'N/A') return grey;
    } else if (kind == 'recommend') {
      if (v == 'Active') return green;
      if (v == 'Expired') return Colors.amber.shade100;
      if (v == 'No') return red;
    }
    return null;
  }
}

// ---- shared chrome ----------------------------------------------------------
