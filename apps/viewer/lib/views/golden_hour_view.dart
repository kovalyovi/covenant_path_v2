part of '../dashboard_page.dart';

enum _Window { week, month, year, all }
enum _GhSection { newMembers, beingTaught }

/// Two sections: **Being Taught** (investigators with a planned baptism date) and
/// **New Members** (baptized — integration milestone chips, next step highlighted).
class _GoldenHourView extends StatefulWidget {
  const _GoldenHourView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_GoldenHourView> createState() => _GoldenHourViewState();
}

class _GoldenHourViewState extends State<_GoldenHourView> {
  _GhSection _section = _GhSection.newMembers;
  _Window _window = _Window.all;
  bool _byDate = false;

  bool _within(Map<String, dynamic> m) {
    if (_window == _Window.all) return true;
    final d = parseMemberDate(m['baptism_date']);
    if (d == null) return false;
    final days = DateTime.now().difference(d).inDays;
    return switch (_window) {
      _Window.week => days <= 7,
      _Window.month => days <= 31,
      _Window.year => days <= 366,
      _Window.all => true,
    };
  }

  @override
  Widget build(BuildContext context) {
    final newMembers = widget.rows.where((m) => m['kind'] != 'investigator').toList();
    final beingTaught = widget.rows.where((m) => m['kind'] == 'investigator').toList();

    final sectionToggle = Center(
      child: SegmentedButton<_GhSection>(
        showSelectedIcon: false,
        segments: [
          ButtonSegment(value: _GhSection.newMembers,
              icon: const Icon(Icons.verified_user, size: 18),
              label: Text('New Members (${newMembers.length})')),
          ButtonSegment(value: _GhSection.beingTaught,
              icon: const Icon(Icons.menu_book, size: 18),
              label: Text('Being Taught (${beingTaught.length})')),
        ],
        selected: {_section},
        onSelectionChanged: (s) => setState(() => _section = s.first),
      ),
    );

    if (_section == _GhSection.beingTaught) {
      return _Page(
        tier: widget.tier,
        header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          sectionToggle,
          const SizedBox(height: 8),
          _SectionTitle(title: 'Being Taught', count: beingTaught.length, byDate: _byDate,
              onToggle: (v) => setState(() => _byDate = v)),
        ]),
        child: beingTaught.isEmpty
            ? const Padding(padding: EdgeInsets.all(32),
                child: Center(child: Text('No one currently being taught.')))
            : (_byDate
                ? _DateList(rows: beingTaught, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                    dateField: 'baptism_goal_date', ascending: true)
                : _UnitGrid(rows: beingTaught, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                    dateField: 'baptism_goal_date', ascending: true)),
      );
    }

    final rows = newMembers.where(_within).toList();
    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        sectionToggle,
        const SizedBox(height: 8),
        Center(
          child: SegmentedButton<_Window>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: _Window.week, label: Text('Week')),
              ButtonSegment(value: _Window.month, label: Text('Month')),
              ButtonSegment(value: _Window.year, label: Text('Year')),
              ButtonSegment(value: _Window.all, label: Text('All')),
            ],
            selected: {_window},
            onSelectionChanged: (s) => setState(() => _window = s.first),
          ),
        ),
        const SizedBox(height: 8),
        _SectionTitle(title: 'Recently Baptized', count: rows.length, byDate: _byDate,
            onToggle: (v) => setState(() => _byDate = v)),
        _CompletionCard(rows: rows),
      ]),
      child: rows.isEmpty
          ? const Padding(padding: EdgeInsets.all(32),
              child: Center(child: Text('No new members in this window.')))
          : (_byDate
              ? _DateList(rows: rows, tier: widget.tier, onOpen: widget.onOpen, chips: true)
              : _UnitGrid(rows: rows, tier: widget.tier, onOpen: widget.onOpen, chips: true)),
    );
  }
}

class _CompletionCard extends StatelessWidget {
  const _CompletionCard({required this.rows});
  final List<Map<String, dynamic>> rows;
  @override
  Widget build(BuildContext context) {
    final n = rows.length;
    if (n == 0) return const SizedBox.shrink();
    return SectionCard(
      title: 'Golden Hour completion',
      child: Wrap(spacing: 18, runSpacing: 12, children: [
        for (final ms in milestones)
          _PctStat(label: ms.label, pct: rows.where(ms.complete).length / n),
      ]),
    );
  }
}

class _PctStat extends StatelessWidget {
  const _PctStat({required this.label, required this.pct});
  final String label;
  final double pct;
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 120,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${(pct * 100).round()}%', style: Theme.of(context).textTheme.titleLarge),
        Text(label, style: Theme.of(context).textTheme.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
        const SizedBox(height: 4),
        ClipRRect(borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: pct, minHeight: 5)),
      ]),
    );
  }
}

// ---- Needs Action -----------------------------------------------------------
