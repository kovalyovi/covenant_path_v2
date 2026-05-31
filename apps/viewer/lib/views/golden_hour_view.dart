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
  OrgBucket? _orgFilter; // null = all orgs; else only converts that org currently owns

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

  /// Human-readable window the data covers, so a selected Week/Month/Year isn't ambiguous (#range).
  /// Null for "All" (no bounded window).
  String? _windowRangeLabel() {
    if (_window == _Window.all) return null;
    final now = DateTime.now();
    final days = switch (_window) {
      _Window.week => 7,
      _Window.month => 31,
      _Window.year => 366,
      _Window.all => 0,
    };
    final from = now.subtract(Duration(days: days));
    return 'Baptized ${DateFormat('MMM d').format(from)} – ${DateFormat('MMM d, y').format(now)}';
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
        .where((m) => _orgFilter == null || responsibleOrg(m) == _orgFilter)
        .toList();
    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        sectionToggle,
        const SizedBox(height: 8),
        _OrgFilterBar(selected: _orgFilter, onSelect: (b) => setState(() => _orgFilter = b)),
        if (_orgFilter != null) ...[
          const SizedBox(height: 6),
          _SubtleNote(orgResponsibilityNote(_orgFilter!)),
        ],
        const SizedBox(height: 10),
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
        if (_windowRangeLabel() != null) ...[
          const SizedBox(height: 6),
          Center(child: _RangePill(_windowRangeLabel()!)),
        ],
        const SizedBox(height: 10),
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

/// The org-ownership filter bar: All + one colored chip per org (WML / EQ / RS). Selected → filled
/// with that org's color; unselected → colored icon + faint colored border. Colors come from
/// orgInfo so they stay consistent with the per-member responsibility chips. (#15)
class _OrgFilterBar extends StatelessWidget {
  const _OrgFilterBar({required this.selected, required this.onSelect});
  final OrgBucket? selected;
  final void Function(OrgBucket?) onSelect;
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Wrap(spacing: 6, runSpacing: 6, alignment: WrapAlignment.center, children: [
        FilterChip(
          label: const Text('All'),
          selected: selected == null,
          showCheckmark: false,
          onSelected: (_) => onSelect(null),
        ),
        for (final b in OrgBucket.values)
          () {
            final i = orgInfo(b);
            final sel = selected == b;
            return FilterChip(
              label: Text(i.label),
              avatar: Icon(i.icon, size: 16, color: sel ? Colors.white : i.color),
              selected: sel,
              showCheckmark: false,
              selectedColor: i.color,
              labelStyle: TextStyle(
                  color: sel ? Colors.white : null, fontWeight: FontWeight.w500),
              side: BorderSide(color: i.color.withValues(alpha: sel ? 1 : 0.45)),
              onSelected: (_) => onSelect(b),
            );
          }(),
      ]),
    );
  }
}

/// A centered, muted one-liner (used for the org-responsibility explanation under the filter).
class _SubtleNote extends StatelessWidget {
  const _SubtleNote(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Text(text,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ),
      );
}

/// A small pill showing the date range the current period covers, so the data window is explicit.
class _RangePill extends StatelessWidget {
  const _RangePill(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
          color: c.surfaceContainerHighest, borderRadius: BorderRadius.circular(20)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.date_range, size: 14, color: c.onSurfaceVariant),
        const SizedBox(width: 6),
        Text(text,
            style: TextStyle(
                fontSize: 12, color: c.onSurfaceVariant, fontWeight: FontWeight.w500)),
      ]),
    );
  }
}

// ---- Needs Action -----------------------------------------------------------
