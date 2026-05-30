part of '../dashboard_page.dart';

class _SpreadsheetView extends StatefulWidget {
  const _SpreadsheetView({required this.rows, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onOpen;

  // (header, member key, kind). 'text' columns sort; 'yesno'/'recommend'/'gender' columns filter.
  static const _cols = <(String, String, String)>[
    ('Member', 'name', 'text'),
    ('Sex', 'sex', 'gender'),
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
  int? _sortCol; // index into _cols; null = no sort (3-state: asc → desc → none)
  bool _sortAsc = true;
  final Map<String, bool?> _filters = {}; // column key → null(all) / true(has) / false(missing)

  static const _yes = {'Yes', 'Active'};

  /// Display value — strips the redundant "Member for " prefix (header already says it). (#31)
  static String _display(Map<String, dynamic> m, String key) {
    final v = '${m[key] ?? ''}';
    return key == 'membership_duration'
        ? v.replaceFirst(RegExp(r'^Member for\s*', caseSensitive: false), '')
        : v;
  }

  bool _passes(Map<String, dynamic> m) {
    for (final e in _filters.entries) {
      if (e.value == null) continue;
      final v = '${m[e.key] ?? ''}';
      if (v.isEmpty || v == 'N/A') return false; // N/A = not applicable → in neither has nor missing
      if (_yes.contains(v) != e.value) return false;
    }
    return true;
  }

  void _cycleFilter(String key) => setState(() {
        final cur = _filters[key];
        _filters[key] = cur == null ? true : (cur ? false : null); // all → has → missing → all
      });

  void _onSort(int col) => setState(() {
        if (_sortCol == col) {
          _sortAsc ? _sortAsc = false : _sortCol = null; // asc → desc → none
        } else {
          _sortCol = col;
          _sortAsc = true;
        }
      });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context);
    // baptized only (investigators live in Upcoming / Golden Hour › Being Taught)
    var rows = widget.rows.where((m) => m['kind'] != 'investigator').where(_passes).toList();
    if (_sortCol != null) {
      final key = _SpreadsheetView._cols[_sortCol!].$2;
      rows.sort((a, b) {
        final c = _display(a, key).toLowerCase().compareTo(_display(b, key).toLowerCase());
        return _sortAsc ? c : -c;
      });
    }
    final active = _filters.values.where((v) => v != null).length;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: Row(children: [
          Text('${rows.length} member${rows.length == 1 ? '' : 's'}'
              '${active > 0 ? ' (filtered)' : ''}', style: scheme.textTheme.bodySmall),
          const Spacer(),
          if (active > 0)
            TextButton.icon(
              onPressed: () => setState(_filters.clear),
              icon: const Icon(Icons.filter_alt_off, size: 16),
              label: Text('Clear $active filter${active == 1 ? '' : 's'}'),
            ),
        ]),
      ),
      Expanded(
        child: SingleChildScrollView(
          scrollDirection: Axis.vertical,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              showCheckboxColumn: false, // #33: no bulk-select; first column is a row number
              sortColumnIndex: _sortCol == null ? null : _sortCol! + 1, // +1 for the leading # column
              sortAscending: _sortAsc,
              headingRowColor: WidgetStatePropertyAll(scheme.colorScheme.primary),
              headingTextStyle:
                  TextStyle(color: scheme.colorScheme.onPrimary, fontWeight: FontWeight.bold),
              headingRowHeight: 46,
              dataRowMinHeight: 40,
              dataRowMaxHeight: 48,
              columnSpacing: 16,
              columns: [
                const DataColumn(label: Text('#')),
                for (var i = 0; i < _SpreadsheetView._cols.length; i++)
                  DataColumn(
                    onSort: _SpreadsheetView._cols[i].$3 == 'text' ? (_, __) => _onSort(i) : null,
                    label: _headerLabel(i),
                  ),
              ],
              rows: [
                for (var r = 0; r < rows.length; r++)
                  DataRow(
                    onSelectChanged: (_) => widget.onOpen(rows[r]),
                    cells: [
                      DataCell(Text('${r + 1}', style: TextStyle(color: Colors.grey.shade500))),
                      for (final c in _SpreadsheetView._cols)
                        _cell(_display(rows[r], c.$2), c.$3),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    ]);
  }

  /// Header: sortable text columns show just the label (DataTable adds the arrow). Filterable
  /// columns show the label + a tap-to-cycle filter icon (all → has → missing). (#5/#6)
  Widget _headerLabel(int i) {
    final (label, key, kind) = _SpreadsheetView._cols[i];
    if (kind == 'text') return Text(label);
    final f = _filters[key];
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Text(label),
      const SizedBox(width: 3),
      InkWell(
        onTap: () => _cycleFilter(key),
        customBorder: const CircleBorder(),
        child: Icon(
          f == null ? Icons.filter_alt_outlined : (f ? Icons.check_circle : Icons.cancel),
          size: 15,
          color: f == null
              ? Colors.white70
              : (f ? Colors.greenAccent.shade100 : Colors.redAccent.shade100),
        ),
      ),
    ]);
  }

  DataCell _cell(String value, String kind) {
    if (kind == 'gender') {
      if (value != 'M' && value != 'F') return const DataCell(Text(''));
      final c = value == 'M' ? Colors.blue.shade100 : Colors.pink.shade100;
      return DataCell(Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(6)),
        child: Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
      ));
    }
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
