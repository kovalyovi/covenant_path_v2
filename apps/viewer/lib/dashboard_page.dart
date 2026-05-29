import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'admin_client.dart';
import 'admin_page.dart';
import 'biometric_gate.dart';
import 'broker_client.dart';
import 'disclaimer.dart';
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
  bool _lockAvailable = false;
  bool _lockOn = false;
  EnrollmentStatus? _enrollStatus;

  @override
  void initState() {
    super.initState();
    _future = _load();
    _future.then((rows) {
      if (rows.isEmpty && mounted) _loadEnrollStatus();
    }).catchError((_) {});
    _checkAdmin();
    _loadStakeName();
    _checkLock();
  }

  Future<void> _loadEnrollStatus() async {
    final broker = BrokerClient();
    if (!broker.available) return;
    try {
      final s = await broker.enrollmentStatus();
      if (mounted) setState(() => _enrollStatus = s);
    } catch (_) {}
  }

  Future<void> _checkLock() async {
    final avail = await BiometricLock.available();
    final on = await BiometricLock.enabled();
    if (mounted) setState(() { _lockAvailable = avail; _lockOn = on; });
  }

  Future<void> _toggleLock() async {
    await BiometricLock.setEnabled(!_lockOn);
    if (mounted) {
      setState(() => _lockOn = !_lockOn);
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Biometric app lock ${_lockOn ? 'on' : 'off'}')));
    }
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

  Future<void> _openSyncSettings() async {
    final status = _enrollStatus;
    if (status == null) {
      // Load on demand if not yet fetched
      final broker = BrokerClient();
      if (!broker.available) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Sync settings require Church account login.')));
        return;
      }
      try {
        final s = await broker.enrollmentStatus();
        if (mounted) setState(() => _enrollStatus = s);
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Could not load sync settings: $e')));
        }
        return;
      }
    }
    if (mounted) { _showSyncSettingsSheet(); }
  }

  void _showSyncSettingsSheet() {
    final status = _enrollStatus;
    showModalBottomSheet(
      context: context,
      builder: (ctx) => _SyncSettingsSheet(
          status: status,
          onRevoke: status?.credential.isProvider == true ? _revokeCredential : null),
    );
  }

  Future<void> _revokeCredential() async {
    final stakeId = _enrollStatus?.stakeId;
    if (stakeId == null) return;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Revoke sync access?'),
        content: const Text(
            'Daily sync for your stake will stop. Re-enroll anytime by signing in again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Revoke')),
        ],
      ),
    );
    if (confirm != true || !mounted) return;
    try {
      await BrokerClient().revoke(stakeId);
      if (mounted) {
        Navigator.pop(context); // close sheet
        setState(() {
          _enrollStatus = null; // will reload on next open
        });
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Sync access revoked. Data will not update until re-enrolled.')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not revoke: $e')));
      }
    }
  }

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
              case 'sync':
                _openSyncSettings();
              case 'feedback':
                _sendFeedback();
              case 'about':
                showAboutDisclaimer(context);
              case 'lock':
                _toggleLock();
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
                value: 'sync',
                child: ListTile(
                    leading: Icon(Icons.sync), title: Text('Sync settings'))),
            const PopupMenuItem(
                value: 'feedback',
                child: ListTile(
                    leading: Icon(Icons.feedback_outlined), title: Text('Send feedback'))),
            const PopupMenuItem(
                value: 'about',
                child: ListTile(
                    leading: Icon(Icons.info_outline), title: Text('About & privacy'))),
            if (_lockAvailable)
              PopupMenuItem(
                  value: 'lock',
                  child: ListTile(
                      leading: const Icon(Icons.fingerprint),
                      title: Text('App lock: ${_lockOn ? 'On' : 'Off'}'))),
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
      IconButton(tooltip: 'Sync settings', onPressed: _openSyncSettings, icon: const Icon(Icons.sync)),
      IconButton(tooltip: 'Refresh', onPressed: _refresh, icon: const Icon(Icons.refresh)),
      IconButton(
          tooltip: 'Send feedback',
          onPressed: _sendFeedback,
          icon: const Icon(Icons.feedback_outlined)),
      IconButton(
          tooltip: 'About & privacy',
          onPressed: () => showAboutDisclaimer(context),
          icon: const Icon(Icons.info_outline)),
      if (_lockAvailable)
        IconButton(
            tooltip: 'App lock (biometrics): ${_lockOn ? 'on' : 'off'}',
            onPressed: _toggleLock,
            icon: Icon(_lockOn ? Icons.lock : Icons.lock_open)),
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
      final staleCred = _enrollStatus?.credential.isRevoked == true;
      final body = Column(children: [
        if (_syncing) const _SyncingBanner(),
        if (staleCred) _StaleBanner(onReenroll: () => supabase.auth.signOut()),
        Expanded(
          child: _Body(tab: _tab, tier: tier, future: _future, onRefresh: _refresh,
              onOpen: _open, enrollStatus: _enrollStatus),
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
      required this.onRefresh, required this.onOpen, this.enrollStatus});
  final int tab;
  final ScreenTier tier;
  final Future<List<Map<String, dynamic>>> future;
  final Future<void> Function() onRefresh;
  final void Function(Map<String, dynamic>) onOpen;
  final EnrollmentStatus? enrollStatus;

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
          return _EmptyState(enrollStatus: enrollStatus);
        }
        final view = switch (tab) {
          0 => _OnDateView(rows: rows, tier: tier, onOpen: onOpen),
          1 => _GoldenHourView(rows: rows, tier: tier, onOpen: onOpen),
          2 => _NeedsView(rows: rows, tier: tier, onOpen: onOpen),
          3 => _KpiView(rows: rows, tier: tier, onOpen: onOpen),
          _ => _SpreadsheetView(rows: rows, onOpen: onOpen),
        };
        return RefreshIndicator(onRefresh: onRefresh, child: view);
      },
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({this.enrollStatus});
  final EnrollmentStatus? enrollStatus;

  @override
  Widget build(BuildContext context) {
    final broker = BrokerClient();
    final cred = enrollStatus?.credential;
    final hasNoRole = enrollStatus?.noRole == true;
    final isChurchLoginAvailable = broker.available;

    String title;
    String body;
    Widget? action;

    if (enrollStatus == null) {
      // Still loading status or broker unavailable
      title = 'No members visible';
      body = 'Access is scoped to your LCR calling. Sign in with the email your stake has on file.';
    } else if (hasNoRole && cred?.isNone == true) {
      if (isChurchLoginAvailable) {
        title = 'Set up stake sync';
        body = 'Your stake hasn\'t set up Covenant Path yet. Sign in with your Church account '
            'and check "Keep my stake synced" to start daily data updates.';
        action = FilledButton.icon(
          onPressed: () => supabase.auth.signOut(),
          icon: const Icon(Icons.login),
          label: const Text('Sign in to enable sync'),
        );
      } else {
        title = 'Stake not set up';
        body = 'Ask your stake leader to enable Covenant Path by signing in with their '
            'Church account. Once set up, sign in with your email code for access.';
      }
    } else if (cred?.isRevoked == true) {
      title = 'Sync paused';
      body = 'The daily sync credential for your stake has been revoked. '
          'Re-enroll to resume data updates.';
      if (isChurchLoginAvailable) {
        action = OutlinedButton.icon(
          onPressed: () => supabase.auth.signOut(),
          icon: const Icon(Icons.refresh),
          label: const Text('Re-enroll'),
        );
      }
    } else if (cred?.isActive == true) {
      title = 'Data syncing…';
      body = 'Your stake has a sync credential on file. Data will appear after the next daily run (7 am ET).';
    } else {
      title = 'No members visible';
      body = 'Access is derived from your LCR calling. Sign in with the email your stake has on file.';
    }

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.group_outlined, size: 56,
                color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.4)),
            const SizedBox(height: 16),
            Text(title, style: Theme.of(context).textTheme.titleMedium,
                textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(body, textAlign: TextAlign.center,
                style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
            if (action != null) ...[const SizedBox(height: 20), action],
          ],
        ),
      ),
    );
  }
}

class _StaleBanner extends StatelessWidget {
  const _StaleBanner({required this.onReenroll});
  final VoidCallback onReenroll;

  @override
  Widget build(BuildContext context) {
    return MaterialBanner(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      content: const Text('Sync paused — credential expired. Re-enroll to resume daily updates.'),
      leading: const Icon(Icons.sync_problem, color: Colors.orange),
      actions: [
        TextButton(onPressed: onReenroll, child: const Text('Re-enroll')),
        TextButton(
            onPressed: () =>
                ScaffoldMessenger.of(context).clearMaterialBanners(),
            child: const Text('Dismiss')),
      ],
    );
  }
}

class _SyncSettingsSheet extends StatelessWidget {
  const _SyncSettingsSheet({this.status, this.onRevoke});
  final EnrollmentStatus? status;
  final VoidCallback? onRevoke;

  @override
  Widget build(BuildContext context) {
    final cred = status?.credential;
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Sync settings', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          if (status == null)
            const Text('Loading…')
          else ...[
            _Row(label: 'Stake', value: status!.stakeName ?? '—'),
            _Row(
                label: 'Last synced',
                value: status!.lastSyncedAt != null
                    ? _fmt(status!.lastSyncedAt!)
                    : 'Never'),
            _Row(label: 'Members', value: '${status!.memberCount}'),
            const Divider(height: 24),
            if (cred == null || cred.isNone) ...[
              const ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.warning_amber_outlined, color: Colors.orange),
                  title: Text('No sync credential'),
                  subtitle: Text('Sign in with your Church account and check '
                      '"Keep my stake synced" to enable daily updates.')),
            ] else ...[
              _Row(
                  label: 'Status',
                  value: cred.isRevoked ? 'Revoked' : 'Active',
                  color: cred.isRevoked ? Colors.orange : Colors.green),
              if (cred.principalName != null)
                _Row(label: 'Provided by', value: cred.principalName!),
              if (cred.enrolledAt != null)
                _Row(label: 'Enrolled', value: _fmt(cred.enrolledAt!)),
              _Row(
                  label: 'Coverage',
                  value: cred.complete ? 'Complete' : 'Partial'),
            ],
            const SizedBox(height: 8),
            const Text(
                'Credentials are encrypted and stored server-side. '
                'Your password is never stored.',
                style: TextStyle(fontSize: 12)),
            if (onRevoke != null) ...[
              const SizedBox(height: 16),
              OutlinedButton.icon(
                  onPressed: () {
                    Navigator.pop(context);
                    onRevoke!();
                  },
                  icon: const Icon(Icons.link_off),
                  label: const Text('Revoke my sync access')),
            ],
          ],
        ],
      ),
    );
  }

  String _fmt(String iso) {
    final dt = DateTime.tryParse(iso);
    if (dt == null) return iso;
    return DateFormat('MMM d, y · h:mm a').format(dt.toLocal());
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.label, required this.value, this.color});
  final String label;
  final String value;
  final Color? color;
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          SizedBox(width: 110, child: Text(label,
              style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant))),
          Expanded(child: Text(value,
              style: color != null ? TextStyle(color: color, fontWeight: FontWeight.w500) : null)),
        ]),
      );
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
              ? _UpcomingCalendar(rows: dated, onOpen: widget.onOpen)
              : _UnitGrid(rows: dated, tier: widget.tier, onOpen: widget.onOpen, chips: false,
                  dateField: 'baptism_goal_date', ascending: true)),
    );
  }
}

/// Prospective baptisms as a calendar (this month + next, if any) with today highlighted and
/// baptism days marked, then a compact list. Dates beyond the two months go in a "Later" list.
/// Kept narrow on purpose.
class _UpcomingCalendar extends StatelessWidget {
  const _UpcomingCalendar({required this.rows, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final void Function(Map<String, dynamic>) onOpen;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final items = <({Map<String, dynamic> m, DateTime date})>[];
    for (final m in rows) {
      final d = parseMemberDate(m['baptism_goal_date']);
      if (d != null) items.add((m: m, date: DateTime(d.year, d.month, d.day)));
    }
    items.sort((a, b) => a.date.compareTo(b.date));
    final thisM = DateTime(now.year, now.month);
    final nextM = DateTime(now.year, now.month + 1);
    bool inMonth(DateTime d, DateTime mo) => d.year == mo.year && d.month == mo.month;
    final inCal = items.where((i) => inMonth(i.date, thisM) || inMonth(i.date, nextM)).toList();
    final later = items.where((i) => !inCal.contains(i)).toList();
    final byDay = <DateTime, int>{};
    for (final i in inCal) {
      byDay[i.date] = (byDay[i.date] ?? 0) + 1;
    }
    final showNext = inCal.any((i) => inMonth(i.date, nextM));

    Widget row(({Map<String, dynamic> m, DateTime date}) i) => ListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          leading: PhotoAvatar(
              name: i.m['name']?.toString() ?? '?', photoUrl: i.m['photo_url']?.toString(), size: 38),
          title: Text(i.m['name']?.toString() ?? '—',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text('${i.m['unit_name'] ?? ''} · ${fmtLong(i.date)}',
              style: Theme.of(context).textTheme.bodySmall),
          onTap: () => onOpen(i.m),
        );

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Column(children: [
          _MonthGrid(month: thisM, today: today, byDay: byDay),
          if (showNext) _MonthGrid(month: nextM, today: today, byDay: byDay),
          if (inCal.isNotEmpty)
            SectionCard(
                title: 'This & next month',
                leadingIcon: Icons.event_available,
                child: Column(children: [for (final i in inCal) row(i)])),
          if (later.isNotEmpty)
            SectionCard(
                title: 'Later',
                leadingIcon: Icons.update,
                child: Column(children: [for (final i in later) row(i)])),
        ]),
      ),
    );
  }
}

/// A compact month grid; days with a baptism are tinted (with a count dot), today gets a ring.
class _MonthGrid extends StatelessWidget {
  const _MonthGrid({required this.month, required this.today, required this.byDay});
  final DateTime month; // year/month (day ignored)
  final DateTime today;
  final Map<DateTime, int> byDay;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    final daysInMonth = DateTime(month.year, month.month + 1, 0).day;
    final lead = DateTime(month.year, month.month, 1).weekday % 7; // Sun=0 .. Sat=6
    final cells = <Widget?>[for (var i = 0; i < lead; i++) null];
    for (var d = 1; d <= daysInMonth; d++) {
      cells.add(_dayCell(context, DateTime(month.year, month.month, d)));
    }
    while (cells.length % 7 != 0) {
      cells.add(null);
    }
    return SectionCard(
      title: DateFormat('MMMM y').format(month),
      leadingIcon: Icons.calendar_month,
      child: Column(children: [
        Row(children: [
          for (final w in const ['S', 'M', 'T', 'W', 'T', 'F', 'S'])
            Expanded(
                child: Center(
                    child: Text(w,
                        style: TextStyle(fontSize: 11, color: c.onSurfaceVariant)))),
        ]),
        const SizedBox(height: 4),
        for (var r = 0; r < cells.length / 7; r++)
          Row(children: [
            for (var k = 0; k < 7; k++)
              Expanded(child: cells[r * 7 + k] ?? const SizedBox(height: 40)),
          ]),
      ]),
    );
  }

  Widget _dayCell(BuildContext context, DateTime day) {
    final c = Theme.of(context).colorScheme;
    final count = byDay[day] ?? 0;
    final isToday = day == today;
    return Container(
      height: 40,
      margin: const EdgeInsets.all(2),
      decoration: BoxDecoration(
        color: count > 0 ? c.primary.withValues(alpha: 0.14) : null,
        borderRadius: BorderRadius.circular(8),
        border: isToday ? Border.all(color: c.primary, width: 1.6) : null,
      ),
      child: Stack(alignment: Alignment.center, children: [
        Text('${day.day}',
            style: TextStyle(
                fontWeight: count > 0 || isToday ? FontWeight.bold : FontWeight.normal,
                color: count > 0 ? c.primary : null)),
        if (count > 0)
          Positioned(
            bottom: 3,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 5),
              decoration: BoxDecoration(color: c.primary, borderRadius: BorderRadius.circular(8)),
              child: Text('$count',
                  style: TextStyle(color: c.onPrimary, fontSize: 9, fontWeight: FontWeight.bold)),
            ),
          ),
      ]),
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
    return ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      onTap: () => onOpen(m),
      leading: PhotoAvatar(name: name, photoUrl: m['photo_url']?.toString(), size: 44),
      title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (date != null)
          Text(fmtLong(date), style: Theme.of(context).textTheme.bodySmall),
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
  const _KpiView({required this.rows, required this.tier, required this.onOpen});
  final List<Map<String, dynamic>> rows;
  final ScreenTier tier;
  final void Function(Map<String, dynamic>) onOpen;
  @override
  State<_KpiView> createState() => _KpiViewState();
}

class _KpiViewState extends State<_KpiView> {
  _Period _period = _Period.week;
  String? _unit; // null = whole stake; else drill into one unit
  bool _compare = false; // overlay the previous equal period

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
    final investigators = rows.where((m) => m['kind'] == 'investigator').toList();
    final allUnits = rows.map((m) => '${m['unit_name'] ?? '—'}').toSet();
    final onOpen = widget.onOpen;
    // unique people per period (a member attending several Sundays in a month counts once)
    final friendsAtSac = _metricData(investigators, datesOf: _attendedDates, period: _period);
    final newAtSac = _metricData(baptized, datesOf: _attendedDates, period: _period);
    final newFriends = _metricData(investigators, datesOf: _firstLessonDate, period: _period);
    final lessonsWithMember = _lessonsWithMember(rows);
    final completion = _avgCompletion(baptized);
    // overview drills: list the people behind a number (one entry each, dated for the chrono view)
    List<_Ev> evs(Iterable<Map<String, dynamic>> ms, String dateField) =>
        [for (final m in ms) _Ev(m, parseMemberDate(m[dateField]) ?? DateTime.now(), 0)];

    final cards = <Widget>[
      _MetricChartCard(
        title: 'Investigators at Sacrament',
        icon: Icons.groups,
        color: Colors.orange.shade700,
        series: friendsAtSac.series,
        events: friendsAtSac.events,
        allUnits: allUnits,
        onOpen: onOpen,
        compare: _compareLabels,
        showCompare: _compare,
        suffix: 'people being taught who attended sacrament',
      ),
      _MetricChartCard(
        title: 'New Members at Sacrament',
        icon: Icons.favorite,
        color: const Color(0xFFB5532A),
        series: newAtSac.series,
        events: newAtSac.events,
        allUnits: allUnits,
        onOpen: onOpen,
        compare: _compareLabels,
        showCompare: _compare,
        suffix: 'baptized members who attended sacrament',
      ),
      _MetricChartCard(
        title: 'New Friends Being Taught',
        icon: Icons.local_library,
        color: Colors.teal.shade600,
        series: newFriends.series,
        events: newFriends.events,
        allUnits: allUnits,
        onOpen: onOpen,
        compare: _compareLabels,
        showCompare: _compare,
        suffix: 'people who started lessons in the period',
      ),
      _StatGridCard(items: [
        ('Being taught now', '${investigators.length}', () => _showDrill(context,
            title: 'Being taught now', events: evs(investigators, 'baptism_goal_date'),
            allUnits: allUnits, onOpen: onOpen)),
        ('Lessons w/ member present', '$lessonsWithMember', null),
        ('New members tracked', '${baptized.length}', () => _showDrill(context,
            title: 'New members tracked', events: evs(baptized, 'baptism_date'),
            allUnits: allUnits, onOpen: onOpen)),
        ('Golden Hour', '${(completion * 100).round()}%', null),
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
        const SizedBox(height: 8),
        Center(
          child: FilterChip(
            avatar: Icon(Icons.compare_arrows,
                size: 18, color: _compare ? Theme.of(context).colorScheme.primary : null),
            label: const Text('Compare to previous'),
            selected: _compare,
            onSelected: (v) => setState(() => _compare = v),
          ),
        ),
      ]),
      child: _Columns(cols: _cols(widget.tier).clamp(1, 2), children: cards),
    );
  }
}

class _MetricChartCard extends StatelessWidget {
  const _MetricChartCard({required this.title, required this.icon, required this.color,
      required this.series, required this.compare, required this.suffix,
      required this.events, required this.allUnits, required this.onOpen, this.showCompare = false});
  final String title;
  final IconData icon;
  final Color color;
  final _Series series;
  final (String, String) compare; // (prior label, latest label)
  final String suffix;
  final List<_Ev> events;
  final Set<String> allUnits;
  final void Function(Map<String, dynamic>) onOpen;
  final bool showCompare;

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
        SizedBox(
          height: 170,
          child: _Line(
            values: values,
            labels: series.labels,
            color: color,
            prev: showCompare ? series.prev : const [],
            onBucketTap: (i) => _showDrill(context,
                title: title,
                events: events.where((e) => e.bucket == i).toList(),
                allUnits: allUnits,
                onOpen: onOpen,
                bucketLabel: i < series.labels.length ? series.labels[i] : null),
          ),
        ),
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
            child: Text(suffix,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
          ),
          TextButton.icon(
            onPressed: () => _showDrill(context,
                title: title, events: events, allUnits: allUnits, onOpen: onOpen),
            icon: const Icon(Icons.groups, size: 16),
            label: const Text('By unit'),
            style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
          ),
        ]),
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
  const _Line(
      {required this.values, required this.labels, required this.color,
      this.prev = const [], this.onBucketTap});
  final List<double> values;
  final List<String> labels;
  final Color color;
  final List<double> prev; // previous-period overlay (drawn faded/dashed when non-empty)
  final void Function(int bucketIndex)? onBucketTap;

  @override
  Widget build(BuildContext context) {
    if (values.isEmpty) {
      return Center(child: Text('No data yet', style: TextStyle(color: Colors.grey.shade500)));
    }
    final peak = [...values, ...prev].reduce((a, b) => a > b ? a : b);
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
    final prevBar = prev.isEmpty
        ? null
        : LineChartBarData(
            spots: [for (var i = 0; i < prev.length; i++) FlSpot(i.toDouble(), prev[i])],
            isCurved: true,
            curveSmoothness: 0.3,
            color: Colors.grey.shade400,
            barWidth: 2,
            dashArray: const [5, 4],
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(show: false),
          );
    final step = (values.length / 3).ceil().clamp(1, 999);
    return LineChart(LineChartData(
      minY: 0,
      maxY: maxY,
      gridData: const FlGridData(show: false),
      borderData: FlBorderData(show: false),
      lineTouchData: LineTouchData(
        enabled: onBucketTap != null,
        handleBuiltInTouches: false, // don't draw a built-in tooltip (keeps the always-on labels)
        touchCallback: (event, resp) {
          if (onBucketTap != null &&
              event is FlTapUpEvent &&
              (resp?.lineBarSpots?.isNotEmpty ?? false)) {
            onBucketTap!(resp!.lineBarSpots!.first.x.toInt());
          }
        },
        touchTooltipData: LineTouchTooltipData(
          getTooltipColor: (_) => Colors.transparent,
          tooltipPadding: EdgeInsets.zero,
          tooltipMargin: 4,
          getTooltipItems: (touched) => [
            for (final t in touched)
              t.barIndex == 0 && prevBar != null
                  ? null
                  : LineTooltipItem(
                      t.y == t.y.roundToDouble() ? '${t.y.round()}' : t.y.toStringAsFixed(0),
                      TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 11),
                    ),
          ],
        ),
      ),
      showingTooltipIndicators: [
        for (var i = 0; i < spots.length; i++)
          ShowingTooltipIndicators([LineBarSpot(bar, prevBar != null ? 1 : 0, spots[i])]),
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
      lineBarsData: [if (prevBar != null) prevBar, bar],
    ));
  }
}

/// Opens the people behind a metric: distribution **by unit** (every unit in scope, including
/// those with 0) expandable to names, or **chronologically** by their date (with unit shown).
void _showDrill(BuildContext context,
    {required String title,
    required List<_Ev> events,
    required Set<String> allUnits,
    required void Function(Map<String, dynamic>) onOpen,
    String? bucketLabel}) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    constraints: const BoxConstraints(maxWidth: 640),
    builder: (_) => _DrillSheet(
        title: title, events: events, allUnits: allUnits, onOpen: onOpen, bucketLabel: bucketLabel),
  );
}

class _DrillSheet extends StatefulWidget {
  const _DrillSheet(
      {required this.title,
      required this.events,
      required this.allUnits,
      required this.onOpen,
      this.bucketLabel});
  final String title;
  final List<_Ev> events;
  final Set<String> allUnits;
  final void Function(Map<String, dynamic>) onOpen;
  final String? bucketLabel;
  @override
  State<_DrillSheet> createState() => _DrillSheetState();
}

class _DrillSheetState extends State<_DrillSheet> {
  bool _byUnit = true;
  String _unit(Map<String, dynamic> m) => (m['unit_name'] ?? '—').toString();
  String _id(Map<String, dynamic> m) => (m['person_uuid'] ?? m['name'] ?? '').toString();

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scroll) => ListView(
        controller: scroll,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          Text(widget.title + (widget.bucketLabel != null ? ' · ${widget.bucketLabel}' : ''),
              style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 10),
          Center(
            child: SegmentedButton<bool>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(value: true, icon: Icon(Icons.groups, size: 18), label: Text('By unit')),
                ButtonSegment(value: false, icon: Icon(Icons.schedule, size: 18), label: Text('By date')),
              ],
              selected: {_byUnit},
              onSelectionChanged: (s) => setState(() => _byUnit = s.first),
            ),
          ),
          const SizedBox(height: 12),
          ...(_byUnit ? _byUnitTiles(context) : _chronoTiles(context)),
        ],
      ),
    );
  }

  List<Widget> _byUnitTiles(BuildContext context) {
    final byUnit = <String, Map<String, Map<String, dynamic>>>{for (final u in widget.allUnits) u: {}};
    for (final e in widget.events) {
      (byUnit[_unit(e.m)] ??= {})[_id(e.m)] = e.m;
    }
    final units = byUnit.keys.toList()..sort();
    return [
      for (final u in units)
        Builder(builder: (context) {
          final members = byUnit[u]!.values.toList()
            ..sort((a, b) => (a['name'] ?? '').toString().compareTo((b['name'] ?? '').toString()));
          final card = Card(
            elevation: 0,
            margin: const EdgeInsets.symmetric(vertical: 4),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
                side: BorderSide(color: Theme.of(context).colorScheme.outlineVariant)),
            child: members.isEmpty
                ? ListTile(
                    dense: true,
                    title: Text(u, style: TextStyle(color: Colors.grey.shade600)),
                    trailing: Text('0', style: TextStyle(color: Colors.grey.shade500)))
                : ExpansionTile(
                    title: Text(u),
                    trailing: _CountBadge(members.length),
                    children: [
                      for (final m in members)
                        ListTile(
                          dense: true,
                          leading: PhotoAvatar(
                              name: m['name']?.toString() ?? '?',
                              photoUrl: m['photo_url']?.toString(),
                              size: 32),
                          title: Text(m['name']?.toString() ?? '—'),
                          onTap: () {
                            Navigator.pop(context);
                            widget.onOpen(m);
                          },
                        ),
                    ],
                  ),
          );
          return card;
        }),
    ];
  }

  List<Widget> _chronoTiles(BuildContext context) {
    final sorted = [...widget.events]..sort((a, b) => b.date.compareTo(a.date));
    if (sorted.isEmpty) {
      return [Padding(padding: const EdgeInsets.all(16), child: Text('No one in this view.', style: TextStyle(color: Colors.grey.shade600)))];
    }
    return [
      for (final e in sorted)
        ListTile(
          dense: true,
          leading: PhotoAvatar(
              name: e.m['name']?.toString() ?? '?', photoUrl: e.m['photo_url']?.toString(), size: 32),
          title: Text(e.m['name']?.toString() ?? '—'),
          subtitle: Text('${_unit(e.m)} · ${fmtLong(e.date)}'),
          onTap: () {
            Navigator.pop(context);
            widget.onOpen(e.m);
          },
        ),
    ];
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
  final List<(String, String, VoidCallback?)> items; // (label, value, onTap?)
  @override
  Widget build(BuildContext context) {
    return SectionCard(
      title: 'Overview',
      child: Wrap(spacing: 24, runSpacing: 16, children: [
        for (final it in items)
          InkWell(
            onTap: it.$3,
            borderRadius: BorderRadius.circular(8),
            child: SizedBox(
                width: 124,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Text(it.$2,
                        style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
                    if (it.$3 != null) ...[
                      const SizedBox(width: 3),
                      Icon(Icons.chevron_right, size: 18, color: Colors.grey.shade500),
                    ],
                  ]),
                  Text(it.$1, style: Theme.of(context).textTheme.bodySmall),
                ])),
          ),
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

/// One matching event for the drill-down: a member counted toward a metric on a date, mapped to
/// the displayed-window bucket index (the x-position on the chart).
class _Ev {
  const _Ev(this.m, this.date, this.bucket);
  final Map<String, dynamic> m;
  final DateTime date;
  final int bucket;
}

/// Series for the chart (unique people per bucket, recent window vs the preceding one) PLUS the
/// underlying events so a tap can show *who* (with their unit), by unit or chronologically.
({_Series series, List<_Ev> events}) _metricData(Iterable<Map<String, dynamic>> rows,
    {required Iterable<DateTime> Function(Map<String, dynamic>) datesOf, required _Period period}) {
  final sets = <int, Set<String>>{};
  final labels = <int, String>{};
  final raw = <(Map<String, dynamic>, DateTime, int)>[]; // (member, date, bucketKey)
  for (final m in rows) {
    final id = (m['person_uuid'] ?? m['name'] ?? identityHashCode(m)).toString();
    for (final dt in datesOf(m)) {
      final (key, label) = _bucketOf(dt, period);
      labels[key] = label;
      (sets[key] ??= <String>{}).add(id);
      raw.add((m, dt, key));
    }
  }
  if (sets.isEmpty) return (series: (labels: [], current: [], prev: []), events: []);
  final keys = sets.keys.toList()..sort();
  final n = _periodWindow[period]!;
  final start = (keys.length - n).clamp(0, keys.length);
  final windowKeys = keys.sublist(start);
  final idxOf = {for (var i = 0; i < windowKeys.length; i++) windowKeys[i]: i};
  final cur = <double>[], prv = <double>[], lab = <String>[];
  for (var i = start; i < keys.length; i++) {
    cur.add(sets[keys[i]]!.length.toDouble());
    lab.add(labels[keys[i]]!);
    final pj = i - n;
    prv.add(pj >= 0 ? sets[keys[pj]]!.length.toDouble() : 0);
  }
  final events = [
    for (final r in raw)
      if (idxOf.containsKey(r.$3)) _Ev(r.$1, r.$2, idxOf[r.$3]!),
  ];
  return (series: (labels: lab, current: cur, prev: keys.length > n ? prv : []), events: events);
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
