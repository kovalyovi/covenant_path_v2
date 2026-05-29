import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'admin_client.dart';
import 'admin_page.dart';
import 'golden_hour.dart';
import 'invite_page.dart';
import 'main.dart';
import 'person_detail_page.dart';

/// RLS-scoped dashboard. Four tabs mirroring the reference iOS app (+ our spreadsheet):
///  • Upcoming    — prospective baptisms (people being taught), by planned baptism date.
///  • Golden Hour — Being Taught + New-Member integration milestones (recency-filtered).
///  • KPIs        — stake metrics as line-chart cards.
///  • Table       — every covenant-path field, color-coded like the master sheet.
///
/// Responsive: bottom nav on phones; a side NavigationRail + multi-column cards on
/// tablet/desktop so the browser feels like a real app, not a stretched phone.
class DashboardPage extends StatefulWidget {
  const DashboardPage({super.key});
  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

const _columns =
    'person_uuid, stake_id, unit_id, name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, '
    'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, '
    'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance, details, photo_url, '
    'kind, baptism_goal_date';

const _tabs = [
  (icon: Icons.event, label: 'Upcoming'),
  (icon: Icons.timelapse, label: 'Golden Hour'),
  (icon: Icons.checklist, label: 'Needs'),
  (icon: Icons.insights, label: 'KPIs'),
  (icon: Icons.grid_on, label: 'Table'),
];

class _DashboardPageState extends State<DashboardPage> {
  late Future<List<Map<String, dynamic>>> _future;
  int _tab = 0;
  bool _isAdmin = false;
  String? _stakeName;
  String? _lastSynced;
  bool _syncing = false;

  @override
  void initState() {
    super.initState();
    _future = _load();
    _checkAdmin();
    _loadStakeName();
  }

  Future<void> _checkAdmin() async {
    try {
      if (await supabase.rpc('is_admin') == true && mounted) setState(() => _isAdmin = true);
    } catch (_) {}
  }

  Future<void> _loadStakeName() async {
    try {
      final rows = await supabase.from('stakes').select('name, last_synced_at, sync_state, sync_started_at');
      final list = (rows as List).cast<Map<String, dynamic>>();
      if (list.isEmpty || !mounted) return;
      // freshest stake first, so the chip reflects the most recent scrape the user can see
      list.sort((a, b) => (b['last_synced_at'] ?? '')
          .toString()
          .compareTo((a['last_synced_at'] ?? '').toString()));
      setState(() {
        _stakeName = list.first['name'];
        _lastSynced = list.first['last_synced_at']?.toString();
        // only treat as syncing if it started recently — guards against a crashed run that
        // never got to mark itself 'done' leaving a permanently stuck banner.
        _syncing = list.any((s) {
          if (s['sync_state'] != 'running') return false;
          final started = DateTime.tryParse('${s['sync_started_at'] ?? ''}');
          return started != null && DateTime.now().toUtc().difference(started.toUtc()).inMinutes < 30;
        });
      });
    } catch (_) {}
  }

  Future<List<Map<String, dynamic>>> _load() async {
    final rows = await supabase.from('members').select(_columns).order('unit_name').order('name');
    return (rows as List).cast<Map<String, dynamic>>();
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
  }

  void _open(Map<String, dynamic> m) =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => PersonDetailPage(member: m)));

  Future<void> _sendFeedback() async {
    final titleC = TextEditingController();
    final bodyC = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Send feedback'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: titleC,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Summary')),
          const SizedBox(height: 8),
          TextField(
              controller: bodyC,
              minLines: 3,
              maxLines: 6,
              decoration: const InputDecoration(labelText: 'Details (optional)')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Send')),
        ],
      ),
    );
    if (ok != true || titleC.text.trim().isEmpty) return;
    try {
      final token = supabase.auth.currentSession?.accessToken ?? '';
      final res = await AdminClient(token).feedback(titleC.text.trim(), bodyC.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Thanks! Filed issue #${res['number']}'
                '${res['copilot'] == true ? ' — assigned to Copilot' : ''}')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Couldn\'t send feedback: $e')));
      }
    }
  }

  void _openAdmin() =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AdminPage()));
  void _openInvite() =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const InvitePage()));

  List<Widget> _appBarActions(ScreenTier tier) {
    final chip = _lastSynced != null
        ? _LastUpdated(iso: _lastSynced!, compact: tier == ScreenTier.mobile)
        : null;
    // Phones: stake title + a single "⋯" overflow for options (like the iOS app). Wider
    // screens keep the inline icon row.
    if (tier == ScreenTier.mobile) {
      return [
        if (chip != null) chip,
        IconButton(tooltip: 'Refresh', onPressed: _refresh, icon: const Icon(Icons.refresh)),
        PopupMenuButton<String>(
          tooltip: 'Options',
          icon: const Icon(Icons.more_horiz),
          onSelected: (v) {
            switch (v) {
              case 'admin':
                _openAdmin();
              case 'invite':
                _openInvite();
              case 'feedback':
                _sendFeedback();
              case 'signout':
                supabase.auth.signOut();
            }
          },
          itemBuilder: (_) => [
            if (_isAdmin)
              const PopupMenuItem(
                  value: 'admin',
                  child: ListTile(
                      leading: Icon(Icons.admin_panel_settings),
                      title: Text('Admin · Ops console'))),
            const PopupMenuItem(
                value: 'invite',
                child: ListTile(
                    leading: Icon(Icons.person_add_alt), title: Text('Invite a power user'))),
            const PopupMenuItem(
                value: 'feedback',
                child: ListTile(
                    leading: Icon(Icons.feedback_outlined), title: Text('Send feedback'))),
            const PopupMenuItem(
                value: 'signout',
                child: ListTile(leading: Icon(Icons.logout), title: Text('Sign out'))),
          ],
        ),
      ];
    }
    return [
      if (chip != null) chip,
      if (_isAdmin)
        IconButton(
            tooltip: 'Admin · Ops console',
            onPressed: _openAdmin,
            icon: const Icon(Icons.admin_panel_settings)),
      IconButton(
          tooltip: 'Invite a power user',
          onPressed: _openInvite,
          icon: const Icon(Icons.person_add_alt)),
      IconButton(tooltip: 'Refresh', onPressed: _refresh, icon: const Icon(Icons.refresh)),
      IconButton(
          tooltip: 'Send feedback',
          onPressed: _sendFeedback,
          icon: const Icon(Icons.feedback_outlined)),
      IconButton(
          tooltip: 'Sign out (${supabase.auth.currentUser?.email ?? ''})',
          onPressed: () => supabase.auth.signOut(),
          icon: const Icon(Icons.logout)),
    ];
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final tier = tierFor(c.maxWidth);
      final appBar = AppBar(title: Text(_stakeName ?? 'Covenant Path'), actions: _appBarActions(tier));
      final body = Column(children: [
        if (_syncing) const _SyncingBanner(),
        Expanded(
          child: _Body(tab: _tab, tier: tier, future: _future, onRefresh: _refresh, onOpen: _open),
        ),
      ]);

      if (tier == ScreenTier.mobile) {
        return Scaffold(
          appBar: appBar,
          body: body,
          bottomNavigationBar: NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: [
              for (final t in _tabs) NavigationDestination(icon: Icon(t.icon), label: t.label),
            ],
          ),
        );
      }
      // tablet / desktop: side rail (no full-width bottom bar), app-like.
      return Scaffold(
        appBar: appBar,
        body: Row(children: [
          NavigationRail(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            extended: tier == ScreenTier.desktop,
            labelType: tier == ScreenTier.desktop ? null : NavigationRailLabelType.all,
            destinations: [
              for (final t in _tabs)
                NavigationRailDestination(icon: Icon(t.icon), label: Text(t.label)),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: body),
        ]),
      );
    });
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.tab, required this.tier, required this.future,
      required this.onRefresh, required this.onOpen});
  final int tab;
  final ScreenTier tier;
  final Future<List<Map<String, dynamic>>> future;
  final Future<void> Function() onRefresh;
  final void Function(Map<String, dynamic>) onOpen;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Center(child: Padding(padding: const EdgeInsets.all(24),
              child: Text('Could not load data:\n${snap.error}', textAlign: TextAlign.center)));
        }
        final rows = snap.data ?? [];
        if (rows.isEmpty && tab != 3) {
          return const Center(child: Padding(padding: EdgeInsets.all(24),
              child: Text('No members visible for your account.\n\nAccess is derived from your '
                  'LCR calling — sign in with the email your stake has on file.',
                  textAlign: TextAlign.center)));
        }
        final view = switch (tab) {
          0 => _OnDateView(rows: rows, tier: tier, onOpen: onOpen),
          1 => _GoldenHourView(rows: rows, tier: tier, onOpen: onOpen),
          2 => _NeedsView(rows: rows, tier: tier, onOpen: onOpen),
          3 => _KpiView(rows: rows, tier: tier),
          _ => _SpreadsheetView(rows: rows, onOpen: onOpen),
        };
        return RefreshIndicator(onRefresh: onRefresh, child: view);
      },
    );
  }
}

// ---- Upcoming (prospective baptisms) ----------------------------------------

/// People being taught who have a *planned* (future) baptism date — the missionary
/// "baptismGoalDate". Sorted soonest-first; the date shown is the goal, not an actual baptism.
class _OnDateView extends StatefulWidget {
  const _OnDateView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_OnDateView> createState() => _OnDateViewState();
}

class _OnDateViewState extends State<_OnDateView> {
  bool _byDate = false;

  @override
  Widget build(BuildContext context) {
    final dated = widget.rows
        .where((m) => m['kind'] == 'investigator' && parseMemberDate(m['baptism_goal_date']) != null)
        .toList();
    return _Page(
      tier: widget.tier,
      header: _SectionTitle(title: 'Prospective Baptisms', count: dated.length, byDate: _byDate,
          onToggle: (v) => setState(() => _byDate = v)),
      child: dated.isEmpty
          ? const Padding(padding: EdgeInsets.all(32),
              child: Center(child: Text('No prospective baptisms with a planned date.')))
          : (_byDate
              ? _DateList(rows: dated, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                  dateField: 'baptism_goal_date', datePrefix: 'Planned · ', ascending: true)
              : _UnitGrid(rows: dated, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                  dateField: 'baptism_goal_date', datePrefix: 'Planned · ', ascending: true)),
    );
  }
}

// ---- Golden Hour ------------------------------------------------------------

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
                    dateField: 'baptism_goal_date', datePrefix: 'Planned · ', ascending: true)
                : _UnitGrid(rows: beingTaught, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                    dateField: 'baptism_goal_date', datePrefix: 'Planned · ', ascending: true)),
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
      this.dateField = 'baptism_date', this.datePrefix = '', this.ascending = false});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final String dateField;
  final String datePrefix;
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
              _MemberRow(m: g.$2[i], onOpen: onOpen, chips: chips,
                  dateField: dateField, datePrefix: datePrefix),
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
      this.dateField = 'baptism_date', this.datePrefix = '', this.ascending = false});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final String dateField;
  final String datePrefix;
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
              dateField: dateField, datePrefix: datePrefix),
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
      this.dateField = 'baptism_date', this.datePrefix = ''});
  final Map<String, dynamic> m;
  final void Function(Map<String, dynamic>) onOpen;
  final bool chips;
  final bool showUnit;
  final String dateField;
  final String datePrefix;

  @override
  Widget build(BuildContext context) {
    final name = m['name']?.toString() ?? '—';
    final date = parseMemberDate(m[dateField]);
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      onTap: () => onOpen(m),
      leading: PhotoAvatar(name: name, photoUrl: m['photo_url']?.toString(), size: 44),
      title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (date != null)
          Text('$datePrefix${fmtLong(date)}', style: Theme.of(context).textTheme.bodySmall),
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

enum _Period { week, month, year }

/// KPIs computed from this stake's own covenant-path data (not LCR membership stats):
///   • New Members at Sacrament — baptized members attending, bucketed by the selected period
///   • Friends at Sacrament     — people being taught attending
///   • New friends being taught / Lessons with member present — current counts
/// Each chart overlays the most recent window against the immediately-preceding window in a
/// contrasting color, so you can see the change. Calendar week / month / year toggle.
class _KpiView extends StatefulWidget {
  const _KpiView({required this.rows, required this.tier});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  @override
  State<_KpiView> createState() => _KpiViewState();
}

class _KpiViewState extends State<_KpiView> {
  _Period _period = _Period.week;
  String? _unit; // null = whole stake; else drill into one unit

  (String, String) get _compareLabels => switch (_period) {
        _Period.week => ('2 weeks ago', 'Last week'),
        _Period.month => ('Last month', 'This month'),
        _Period.year => ('Last year', 'This year'),
      };

  @override
  Widget build(BuildContext context) {
    final units = (widget.rows.map((m) => '${m['unit_name'] ?? ''}').where((u) => u.isNotEmpty).toSet().toList()
      ..sort());
    final rows = _unit == null
        ? widget.rows
        : widget.rows.where((m) => m['unit_name'] == _unit).toList();
    final baptized = rows.where((m) => m['kind'] != 'investigator').toList();
    final investigators = rows.where((m) => m['kind'] == 'investigator');
    // unique people per period (a member attending several Sundays in a month counts once)
    final newAtSac = _uniqueSeries(baptized, datesOf: _attendedDates, period: _period);
    final friendsAtSac = _uniqueSeries(investigators, datesOf: _attendedDates, period: _period);
    final newFriends = _uniqueSeries(investigators, datesOf: _firstLessonDate, period: _period);
    final lessonsWithMember = _lessonsWithMember(rows);
    final completion = _avgCompletion(baptized);

    final cards = <Widget>[
      _MetricChartCard(
        title: 'Investigators at Sacrament',
        icon: Icons.groups,
        color: Colors.orange.shade700,
        series: friendsAtSac,
        compare: _compareLabels,
        suffix: 'unique people being taught who attended sacrament',
      ),
      _MetricChartCard(
        title: 'New Members at Sacrament',
        icon: Icons.favorite,
        color: const Color(0xFFB5532A),
        series: newAtSac,
        compare: _compareLabels,
        suffix: 'unique baptized members who attended sacrament',
      ),
      _MetricChartCard(
        title: 'New Friends Being Taught',
        icon: Icons.local_library,
        color: Colors.teal.shade600,
        series: newFriends,
        compare: _compareLabels,
        suffix: 'people who started lessons in the period',
      ),
      _StatGridCard(items: [
        ('Being taught now', '${investigators.length}'),
        ('Lessons w/ member present', '$lessonsWithMember'),
        ('New members tracked', '${baptized.length}'),
        ('Golden Hour', '${(completion * 100).round()}%'),
      ]),
    ];

    return _Page(
      tier: widget.tier,
      header: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Expanded(
              child: _BigHeader(text: 'KPIs', subtitle: "From this stake's covenant-path data")),
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
        const SizedBox(height: 10),
        Center(
          child: SegmentedButton<_Period>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: _Period.week, label: Text('Week')),
              ButtonSegment(value: _Period.month, label: Text('Month')),
              ButtonSegment(value: _Period.year, label: Text('Year')),
            ],
            selected: {_period},
            onSelectionChanged: (s) => setState(() => _period = s.first),
          ),
        ),
      ]),
      child: _Columns(cols: _cols(widget.tier).clamp(1, 2), children: cards),
    );
  }
}

class _MetricChartCard extends StatelessWidget {
  const _MetricChartCard({required this.title, required this.icon, required this.color,
      required this.series, required this.compare, required this.suffix});
  final String title;
  final IconData icon;
  final Color color;
  final _Series series;
  final (String, String) compare; // (prior label, latest label)
  final String suffix;

  @override
  Widget build(BuildContext context) {
    final values = series.current;
    final last = values.isNotEmpty ? values.last : null;
    final prior = values.length >= 2 ? values[values.length - 2] : null;
    final delta = (last != null && prior != null) ? (last - prior) : null;
    return SectionCard(
      title: title,
      leadingIcon: icon,
      iconColor: color,
      trailing: delta == null ? null : _DeltaBadge(delta: delta),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (last != null && prior != null) ...[
          IntrinsicHeight(
            child: Row(children: [
              Expanded(child: _bigStat(context, compare.$1, prior)),
              Container(
                  width: 1,
                  color: Theme.of(context).colorScheme.outlineVariant,
                  margin: const EdgeInsets.symmetric(horizontal: 14)),
              Expanded(child: _bigStat(context, compare.$2, last)),
            ]),
          ),
          const SizedBox(height: 16),
        ],
        SizedBox(height: 170, child: _Line(values: values, labels: series.labels, color: color)),
        const SizedBox(height: 6),
        Text(suffix,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
      ]),
    );
  }

  Widget _bigStat(BuildContext context, String label, double v) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          const SizedBox(height: 2),
          Text(v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(1),
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
        ],
      );
}

/// iOS-style trend line: smooth curve, gradient fill, open dots, and a value label above
/// every point (always-on tooltips). Sparse gray x-axis labels.
class _Line extends StatelessWidget {
  const _Line({required this.values, required this.labels, required this.color});
  final List<double> values;
  final List<String> labels;
  final Color color;

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) {
      return Center(child: Text('No data yet', style: TextStyle(color: Colors.grey.shade500)));
    }
    final peak = values.reduce((a, b) => a > b ? a : b);
    final maxY = peak * 1.35 + 1; // headroom so the value labels above points aren't clipped
    final spots = [for (var i = 0; i < values.length; i++) FlSpot(i.toDouble(), values[i])];
    final bar = LineChartBarData(
      spots: spots,
      isCurved: true,
      curveSmoothness: 0.3,
      preventCurveOverShooting: true,
      color: color,
      barWidth: 3,
      dotData: FlDotData(
        show: true,
        getDotPainter: (spot, pct, b, i) => FlDotCirclePainter(
            radius: 3.5, color: Colors.white, strokeWidth: 2, strokeColor: color),
      ),
      belowBarData: BarAreaData(
        show: true,
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [color.withValues(alpha: 0.28), color.withValues(alpha: 0.02)],
        ),
      ),
    );
    final step = (values.length / 3).ceil().clamp(1, 999);
    return LineChart(LineChartData(
      minY: 0,
      maxY: maxY,
      gridData: const FlGridData(show: false),
      borderData: FlBorderData(show: false),
      lineTouchData: LineTouchData(
        enabled: false,
        touchTooltipData: LineTouchTooltipData(
          getTooltipColor: (_) => Colors.transparent,
          tooltipPadding: EdgeInsets.zero,
          tooltipMargin: 4,
          getTooltipItems: (touched) => [
            for (final t in touched)
              LineTooltipItem(
                t.y == t.y.roundToDouble() ? '${t.y.round()}' : t.y.toStringAsFixed(0),
                TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11),
              ),
          ],
        ),
      ),
      showingTooltipIndicators: [
        for (var i = 0; i < spots.length; i++) ShowingTooltipIndicators([LineBarSpot(bar, 0, spots[i])]),
      ],
      titlesData: FlTitlesData(
        leftTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: 1,
            reservedSize: 22,
            getTitlesWidget: (x, meta) {
              final i = x.toInt();
              if (i < 0 || i >= labels.length) return const SizedBox.shrink();
              if (i % step != 0 && i != labels.length - 1) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(labels[i], style: TextStyle(fontSize: 10, color: Colors.grey.shade500)),
              );
            },
          ),
        ),
      ),
      lineBarsData: [bar],
    ));
  }
}

class _DeltaBadge extends StatelessWidget {
  const _DeltaBadge({required this.delta});
  final double delta;
  @override
  Widget build(BuildContext context) {
    final up = delta >= 0;
    final c = up ? Colors.green.shade700 : Colors.red.shade700;
    final v = delta == delta.roundToDouble() ? delta.abs().round().toString() : delta.abs().toStringAsFixed(1);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(20)),
      child: Text('${up ? '+' : '−'}$v', style: TextStyle(color: c, fontWeight: FontWeight.w600, fontSize: 12)),
    );
  }
}

class _StatGridCard extends StatelessWidget {
  const _StatGridCard({required this.items});
  final List<(String, String)> items;
  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Overview',
      child: Wrap(spacing: 24, runSpacing: 16, children: [
        for (final it in items)
          SizedBox(width: 120, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(it.$2, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
            Text(it.$1, style: Theme.of(context).textTheme.bodySmall),
          ])),
      ]),
    );
  }
}

// ---- Table (color-coded like the master sheet) ------------------------------

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

  static const _yes = {'Yes', 'Active'};

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
              headingRowColor: WidgetStatePropertyAll(scheme.colorScheme.primary),
              headingTextStyle:
                  TextStyle(color: scheme.colorScheme.onPrimary, fontWeight: FontWeight.bold),
              headingRowHeight: 44,
              dataRowMinHeight: 40,
              dataRowMaxHeight: 48,
              columnSpacing: 18,
              columns: [for (final c in _SpreadsheetView._cols) DataColumn(label: Text(c.$1))],
              rows: [
                for (final m in rows)
                  DataRow(
                    onSelectChanged: (_) => widget.onOpen(m),
                    cells: [for (final c in _SpreadsheetView._cols) _cell('${m[c.$2] ?? ''}', c.$3)],
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

/// Page scaffold for a tab: a sticky-ish header + scrollable body, capped + centered on wide.
class _Page extends StatelessWidget {
  const _Page({required this.tier, required this.header, required this.child});
  final ScreenTier tier;
  final Widget header;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final maxW = tier == ScreenTier.mobile ? double.infinity : 1280.0;
    return Center(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxW),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(14, 16, 14, 32),
          children: [header, const SizedBox(height: 8), child],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.count, required this.byDate, required this.onToggle});
  final String title;
  final int count;
  final bool byDate;
  final ValueChanged<bool> onToggle;
  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Text(title, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
      const SizedBox(width: 8),
      _CountBadge(count),
      const Spacer(),
      SegmentedButton<bool>(
        showSelectedIcon: false,
        style: const ButtonStyle(visualDensity: VisualDensity.compact),
        segments: const [
          ButtonSegment(value: false, icon: Icon(Icons.groups, size: 18), label: Text('Unit')),
          ButtonSegment(value: true, icon: Icon(Icons.event, size: 18), label: Text('Date')),
        ],
        selected: {byDate},
        onSelectionChanged: (s) => onToggle(s.first),
      ),
    ]);
  }
}

class _BigHeader extends StatelessWidget {
  const _BigHeader({required this.text, required this.subtitle});
  final String text;
  final String subtitle;
  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(text, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
      Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
    ]);
  }
}

/// Shown across the top while a scrape is running for the user's stake (coarse status from
/// stakes.sync_state). Covers the new-stake "first sync" case too — the row exists the moment
/// the run starts, so a freshly-onboarded stake sees this instead of an empty screen.
class _SyncingBanner extends StatelessWidget {
  const _SyncingBanner();
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Material(
      color: c.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          SizedBox(
            width: 16, height: 16,
            child: CircularProgressIndicator(strokeWidth: 2, color: c.onSecondaryContainer),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text('Syncing your stake from LCR — fresh data in a few minutes.',
                style: TextStyle(color: c.onSecondaryContainer)),
          ),
        ]),
      ),
    );
  }
}

/// AppBar chip showing data freshness. Shows "Updated 2h ago" (icon-only when [compact]);
/// hover tooltip and tap both reveal the exact local date/time + timezone of the last scrape.
class _LastUpdated extends StatelessWidget {
  const _LastUpdated({required this.iso, this.compact = false});
  final String iso;
  final bool compact;

  String get _exact {
    final dt = DateTime.tryParse(iso)?.toLocal();
    if (dt == null) return iso;
    return '${DateFormat('MMM d, y · h:mm a').format(dt)} ${dt.timeZoneName}';
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Tooltip(
        message: 'Data last updated:\n$_exact',
        child: InkWell(
          borderRadius: BorderRadius.circular(20),
          onTap: () => showDialog<void>(
            context: context,
            builder: (_) => AlertDialog(
              title: const Text('Data freshness'),
              content: Text('Last scraped from LCR:\n\n$_exact'),
              actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
            ),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.history, size: 18),
              if (!compact) ...[
                const SizedBox(width: 4),
                Text('Updated ${_ago(iso)}', style: const TextStyle(fontSize: 12)),
              ],
            ]),
          ),
        ),
      ),
    );
  }
}

class _CountBadge extends StatelessWidget {
  const _CountBadge(this.n);
  final int n;
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 2),
      decoration: BoxDecoration(color: c.secondaryContainer, borderRadius: BorderRadius.circular(20)),
      child: Text('$n', style: TextStyle(color: c.onSecondaryContainer, fontWeight: FontWeight.bold, fontSize: 12)),
    );
  }
}

/// Lays children into [cols] balanced columns (variable-height friendly).
class _Columns extends StatelessWidget {
  const _Columns({required this.cols, required this.children});
  final int cols;
  final List<Widget> children;
  @override
  Widget build(BuildContext context) {
    if (cols <= 1 || children.length <= 1) {
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children);
    }
    final buckets = List.generate(cols, (_) => <Widget>[]);
    for (var i = 0; i < children.length; i++) {
      buckets[i % cols].add(children[i]);
    }
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var i = 0; i < cols; i++) ...[
        if (i > 0) const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: buckets[i])),
      ],
    ]);
  }
}

// ---- responsive + date + math helpers ---------------------------------------

int _cols(ScreenTier t) => switch (t) {
      ScreenTier.mobile => 1,
      ScreenTier.tablet => 2,
      ScreenTier.desktop => 3,
    };

final _longFmt = DateFormat('EEEE, MMMM d, y');
String fmtLong(DateTime? d) => d == null ? '' : _longFmt.format(d);

List<(String, List<Map<String, dynamic>>)> _groupByUnit(List<Map<String, dynamic>> rows,
    {String dateField = 'baptism_date', bool ascending = false}) {
  final by = <String, List<Map<String, dynamic>>>{};
  for (final m in rows) {
    (by[(m['unit_name'] ?? '—').toString()] ??= []).add(m);
  }
  for (final list in by.values) {
    list.sort((a, b) {
      final da = parseMemberDate(a[dateField]), db = parseMemberDate(b[dateField]);
      if (da == null) return 1;
      if (db == null) return -1;
      return ascending ? da.compareTo(db) : db.compareTo(da);
    });
  }
  final keys = by.keys.toList()..sort();
  return [for (final k in keys) (k, by[k]!)];
}

const _months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

DateTime? parseMemberDate(dynamic v) {
  if (v == null) return null;
  final s = v.toString().trim();
  if (s.isEmpty || s == 'N/A' || s == 'needs-profile-api') return null;
  final iso = DateTime.tryParse(s);
  if (iso != null) return iso;
  final m = RegExp(r'^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})$').firstMatch(s);
  if (m != null) {
    final mo = _months.indexWhere((x) => x.toLowerCase() == m.group(2)!.toLowerCase().substring(0, 3));
    if (mo >= 0) return DateTime(int.parse(m.group(3)!), mo + 1, int.parse(m.group(1)!));
  }
  final m2 = RegExp(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$').firstMatch(s);
  if (m2 != null) {
    var y = int.parse(m2.group(3)!);
    if (y < 100) y += 2000;
    return DateTime(y, int.parse(m2.group(1)!), int.parse(m2.group(2)!));
  }
  return null;
}

/// A chart series: the most recent window of buckets ([current] + [labels]) overlaid against
/// the immediately-preceding equal-length window ([prev], position-aligned; empty if none).
typedef _Series = ({List<String> labels, List<double> current, List<double> prev});

const _periodWindow = {_Period.week: 12, _Period.month: 12, _Period.year: 5};

(int, String) _bucketOf(DateTime dt, _Period p) {
  switch (p) {
    case _Period.week:
      final monday = dt.subtract(Duration(days: dt.weekday - 1)); // ISO week start
      return (monday.year * 10000 + monday.month * 100 + monday.day, DateFormat('M/d').format(monday));
    case _Period.month:
      return (dt.year * 100 + dt.month, DateFormat('MMM').format(dt));
    case _Period.year:
      return (dt.year, '${dt.year}');
  }
}

/// Unique-people series: for each member, [datesOf] yields the dates it counts toward; each
/// bucket counts DISTINCT people (not total events, so a person attending many Sundays in a
/// month counts once). Sliced into the recent window vs the preceding window.
_Series _uniqueSeries(Iterable<Map<String, dynamic>> rows,
    {required Iterable<DateTime> Function(Map<String, dynamic>) datesOf, required _Period period}) {
  final sets = <int, Set<String>>{};
  final labels = <int, String>{};
  for (final m in rows) {
    final id = (m['person_uuid'] ?? m['name'] ?? identityHashCode(m)).toString();
    for (final dt in datesOf(m)) {
      final (key, label) = _bucketOf(dt, period);
      labels[key] = label;
      (sets[key] ??= <String>{}).add(id);
    }
  }
  if (sets.isEmpty) return (labels: [], current: [], prev: []);
  final keys = sets.keys.toList()..sort();
  final n = _periodWindow[period]!;
  final start = (keys.length - n).clamp(0, keys.length);
  final cur = <double>[], prv = <double>[], lab = <String>[];
  for (var i = start; i < keys.length; i++) {
    cur.add(sets[keys[i]]!.length.toDouble());
    lab.add(labels[keys[i]]!);
    final pj = i - n; // same slot, one window earlier
    prv.add(pj >= 0 ? sets[keys[pj]]!.length.toDouble() : 0);
  }
  return (labels: lab, current: cur, prev: keys.length > n ? prv : []);
}

/// Sundays this person was marked present at sacrament.
Iterable<DateTime> _attendedDates(Map<String, dynamic> m) sync* {
  final d = m['details'];
  final sac = (d is Map ? d['sacrament'] : null) as List?;
  if (sac == null) return;
  for (final s in sac) {
    if (s is! Map || s['attended'] != true) continue;
    final dt = parseMemberDate(s['date']);
    if (dt != null) yield dt;
  }
}

/// The single date this person started being taught (missionary "first lesson").
Iterable<DateTime> _firstLessonDate(Map<String, dynamic> m) sync* {
  final fl = parseMemberDate((m['details'] as Map?)?['firstLesson']);
  if (fl != null) yield fl;
}

/// Count of lessons taught (across all people) where a member was present for ≥1 principle.
int _lessonsWithMember(List<Map<String, dynamic>> rows) {
  var c = 0;
  for (final m in rows) {
    final d = m['details'];
    final lessons = (d is Map ? d['lessons'] : null) as List?;
    if (lessons == null) continue;
    for (final l in lessons) {
      if (l is! Map) continue;
      final ps = (l['principles'] as List?) ?? const [];
      if (ps.any((p) => p is Map && p['memberPresent'] == true)) c++;
    }
  }
  return c;
}

double _avgCompletion(List<Map<String, dynamic>> rows) {
  if (rows.isEmpty) return 0;
  var sum = 0.0;
  for (final m in rows) {
    final applicable = milestonesFor(m);
    if (applicable.isEmpty) continue;
    sum += applicable.where((x) => x.complete(m)).length / applicable.length;
  }
  return sum / rows.length;
}

String _ago(dynamic iso) {
  final t = DateTime.tryParse('${iso ?? ''}');
  if (t == null) return '$iso';
  final diff = DateTime.now().toUtc().difference(t.toUtc());
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}
