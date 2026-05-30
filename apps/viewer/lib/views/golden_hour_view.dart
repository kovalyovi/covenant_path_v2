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
  bool? _asc; // null = section default; Being Taught → soonest first, New Members → newest first
  String? _respFilter; // null=all, 'WML'=first year, 'RSEQ'=after first year

  bool get _ascending => _asc ?? (_section == _GhSection.beingTaught);

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
              onToggle: (v) => setState(() => _byDate = v),
              ascending: _ascending, onAscToggle: () => setState(() => _asc = !_ascending)),
        ]),
        child: beingTaught.isEmpty
            ? const Padding(padding: EdgeInsets.all(32),
                child: Center(child: Text('No one currently being taught.')))
            : (_byDate
                ? _DateList(rows: beingTaught, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                    dateField: 'baptism_goal_date', ascending: _ascending)
                : _UnitGrid(rows: beingTaught, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                    dateField: 'baptism_goal_date', ascending: _ascending)),
      );
    }

    final rows = newMembers
        .where(_within)
        .where((m) => _respFilter == null || responsibleBucket(m) == _respFilter)
        .toList();
    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        sectionToggle,
        const SizedBox(height: 8),
        Center(
          child: Wrap(spacing: 6, children: [
            FilterChip(
                label: const Text('All'), selected: _respFilter == null,
                onSelected: (_) => setState(() => _respFilter = null)),
            FilterChip(
                label: const Text('Missionaries / WML'), selected: _respFilter == 'WML',
                avatar: const Icon(Icons.volunteer_activism, size: 16),
                onSelected: (_) => setState(() => _respFilter = 'WML')),
            FilterChip(
                label: const Text('EQ / Relief Society'), selected: _respFilter == 'RSEQ',
                avatar: const Icon(Icons.groups_2_outlined, size: 16),
                onSelected: (_) => setState(() => _respFilter = 'RSEQ')),
          ]),
        ),
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
            onToggle: (v) => setState(() => _byDate = v),
            ascending: _ascending, onAscToggle: () => setState(() => _asc = !_ascending)),
        _CompletionCard(rows: rows, onOpen: widget.onOpen),
      ]),
      child: rows.isEmpty
          ? const Padding(padding: EdgeInsets.all(32),
              child: Center(child: Text('No new members in this window.')))
          : (_byDate
              ? _DateList(rows: rows, tier: widget.tier, onOpen: widget.onOpen, chips: true,
                  ascending: _ascending)
              : _UnitGrid(rows: rows, tier: widget.tier, onOpen: widget.onOpen, chips: true,
                  ascending: _ascending)),
    );
  }
}

class _CompletionCard extends StatelessWidget {
  const _CompletionCard({required this.rows, this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>)? onOpen;
  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const SizedBox.shrink();
    return SectionCard(
      title: 'Golden Hour completion',
      child: Wrap(spacing: 18, runSpacing: 12, children: [
        for (final ms in milestones)
          () {
            // Eligible-only: % = (eligible who have it) / (eligible), so ineligible people
            // (wrong age/sex/tenure) never drag the number down. Skip milestones nobody's eligible for.
            final eligible = rows.where(ms.eligible).toList();
            if (eligible.isEmpty) return const SizedBox.shrink();
            final done = eligible.where(ms.complete).toList();
            final missing = eligible.where((m) => !ms.complete(m)).toList();
            return _PctStat(
              label: ms.label,
              pct: done.length / eligible.length,
              caption: '${done.length}/${eligible.length}',
              onTap: () => _showCategory(context, ms.label, missing),
            );
          }(),
      ]),
    );
  }

  void _showCategory(BuildContext context, String label, List<Map<String, dynamic>> missing) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        builder: (_, scroll) => ListView(controller: scroll, padding: const EdgeInsets.all(16), children: [
          Text('Still need: $label', style: Theme.of(context).textTheme.titleLarge),
          Text('${missing.length} eligible ${missing.length == 1 ? 'member' : 'members'}',
              style: Theme.of(context).textTheme.bodySmall),
          const Divider(),
          if (missing.isEmpty) const Padding(padding: EdgeInsets.all(24),
              child: Center(child: Text('Everyone eligible has this. 🎉')))
          else for (final m in missing)
            ListTile(
              dense: true,
              leading: PhotoAvatar(name: '${m['name']}', photoUrl: m['photo_url']?.toString(), size: 36),
              title: Text('${m['name']}'),
              subtitle: Text('${m['unit_name'] ?? ''}'),
              onTap: onOpen == null ? null : () { Navigator.pop(context); onOpen!(m); },
            ),
        ]),
      ),
    );
  }
}

class _PctStat extends StatelessWidget {
  const _PctStat({required this.label, required this.pct, this.caption, this.onTap});
  final String label;
  final double pct;
  final String? caption;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: SizedBox(
        width: 124,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic,
              children: [
            Text('${(pct * 100).round()}%', style: Theme.of(context).textTheme.titleLarge),
            if (caption != null) ...[
              const SizedBox(width: 4),
              Text(caption!, style: Theme.of(context).textTheme.bodySmall),
            ],
          ]),
          Text(label, style: Theme.of(context).textTheme.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          ClipRRect(borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(value: pct, minHeight: 5)),
        ]),
      ),
    );
  }
}

// ---- Needs Action -----------------------------------------------------------
