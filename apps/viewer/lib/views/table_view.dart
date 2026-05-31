part of '../dashboard_page.dart';

class _SpreadsheetView extends StatefulWidget {
  const _SpreadsheetView({required this.rows, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onOpen;

  // (header, member key, kind). 'text' columns also sort; every column filters by value.
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
  // Google-Sheets-style filter: per column, the set of values the user UNCHECKED (hidden).
  // Empty/absent = that column shows everything. A row passes if none of its values are excluded.
  final Map<String, Set<String>> _excluded = {};

  /// Display value — strips the redundant "Member for " prefix (header already says it). (#31)
  static String _display(Map<String, dynamic> m, String key) {
    final v = '${m[key] ?? ''}';
    return key == 'membership_duration'
        ? v.replaceFirst(RegExp(r'^Member for\s*', caseSensitive: false), '')
        : v;
  }

  bool _passes(Map<String, dynamic> m) {
    for (final e in _excluded.entries) {
      if (e.value.contains(_display(m, e.key))) return false;
    }
    return true;
  }

  void _onSort(int col) => setState(() {
        if (_sortCol == col) {
          _sortAsc ? _sortAsc = false : _sortCol = null; // asc → desc → none
        } else {
          _sortCol = col;
          _sortAsc = true;
        }
      });

  /// Google-Sheets-style value picker: the distinct values in this column, each with a checkbox.
  /// Unchecking hides rows with that value; works for any column (gender, unit, Yes/No/N/A, …).
  void _openFilter(BuildContext context, String key, String label) {
    final rows = widget.rows.where((m) => m['kind'] != 'investigator');
    final counts = <String, int>{};
    for (final m in rows) {
      final v = _display(m, key);
      counts[v] = (counts[v] ?? 0) + 1;
    }
    final values = counts.keys.toList()..sort();
    final excluded = Set<String>.from(_excluded[key] ?? const <String>{});
    showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: Text('Filter · $label'),
          content: SizedBox(
            width: 320,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                TextButton(
                    onPressed: () => setLocal(excluded.clear), child: const Text('Select all')),
                TextButton(
                    onPressed: () => setLocal(() => excluded.addAll(values)),
                    child: const Text('Clear all')),
              ]),
              const Divider(height: 1),
              Flexible(
                child: ListView(shrinkWrap: true, children: [
                  for (final v in values)
                    CheckboxListTile(
                      dense: true,
                      controlAffinity: ListTileControlAffinity.leading,
                      value: !excluded.contains(v),
                      title: Text(v.isEmpty ? '(blank)' : v, overflow: TextOverflow.ellipsis),
                      secondary: Text('${counts[v]}',
                          style: Theme.of(context).textTheme.bodySmall),
                      onChanged: (on) =>
                          setLocal(() => on == true ? excluded.remove(v) : excluded.add(v)),
                    ),
                ]),
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            FilledButton(
              onPressed: () {
                setState(() {
                  if (excluded.isEmpty) {
                    _excluded.remove(key);
                  } else {
                    _excluded[key] = excluded;
                  }
                });
                Navigator.pop(ctx);
              },
              child: const Text('Apply'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context);
    var rows = widget.rows.where((m) => m['kind'] != 'investigator').where(_passes).toList();
    if (_sortCol != null) {
      final key = _SpreadsheetView._cols[_sortCol!].$2;
      rows.sort((a, b) {
        final c = _display(a, key).toLowerCase().compareTo(_display(b, key).toLowerCase());
        return _sortAsc ? c : -c;
      });
    }
    final active = _excluded.length;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: Row(children: [
          Text('${rows.length} member${rows.length == 1 ? '' : 's'}'
              '${active > 0 ? ' (filtered)' : ''}', style: scheme.textTheme.bodySmall),
          const Spacer(),
          if (active > 0)
            TextButton.icon(
              onPressed: () => setState(_excluded.clear),
              icon: const Icon(Icons.filter_alt_off, size: 16),
              label: Text('Clear $active filter${active == 1 ? '' : 's'}'),
            ),
        ]),
      ),
      Expanded(
        child: SingleChildScrollView(
          scrollDirection: Axis.vertical,
          // clear the glass bottom nav on mobile so the last rows aren't hidden (#41)
          padding: EdgeInsets.only(bottom: MediaQuery.of(context).size.width < 600 ? 92 : 12),
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              showCheckboxColumn: false, // #33: no bulk-select; first column is a row number
              headingRowColor: WidgetStatePropertyAll(scheme.colorScheme.primary),
              headingTextStyle:
                  TextStyle(color: scheme.colorScheme.onPrimary, fontWeight: FontWeight.bold),
              headingRowHeight: 48,
              dataRowMinHeight: 40,
              dataRowMaxHeight: 48,
              columnSpacing: 14,
              columns: [
                const DataColumn(label: Text('#')),
                for (var i = 0; i < _SpreadsheetView._cols.length; i++)
                  DataColumn(label: _header(i)),
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

  /// Header: label + (text columns) a 3-state sort toggle + (all columns) a value-filter icon.
  /// Both are explicit icons so sorting and the filter popup never fight over the same tap.
  Widget _header(int i) {
    final (label, key, kind) = _SpreadsheetView._cols[i];
    final sortable = kind == 'text';
    final filtered = (_excluded[key] ?? const {}).isNotEmpty;
    final fg = Theme.of(context).colorScheme.onPrimary;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Flexible(child: Text(label, overflow: TextOverflow.ellipsis)),
      if (sortable) ...[
        const SizedBox(width: 2),
        InkWell(
          onTap: () => _onSort(i),
          customBorder: const CircleBorder(),
          child: Icon(
            _sortCol == i
                ? (_sortAsc ? Icons.arrow_upward : Icons.arrow_downward)
                : Icons.unfold_more,
            size: 14,
            color: _sortCol == i ? fg : fg.withValues(alpha: 0.55),
          ),
        ),
      ],
      const SizedBox(width: 2),
      InkWell(
        onTap: () => _openFilter(context, key, label),
        customBorder: const CircleBorder(),
        child: Icon(filtered ? Icons.filter_alt : Icons.filter_alt_outlined,
            size: 15, color: filtered ? Colors.amberAccent.shade100 : fg.withValues(alpha: 0.7)),
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
