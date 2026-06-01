import 'dart:async';
import 'dart:ui' show ImageFilter;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'admin_client.dart';
import 'admin_page.dart';
import 'broker_client.dart';
import 'golden_hour.dart';
import 'invite_page.dart';
import 'main.dart';
import 'passkey_client.dart';
import 'person_detail_page.dart';
import 'settings_page.dart';
import 'widgets/shimmer.dart';

part 'views/dashboard_shell.dart';
part 'views/baptisms_view.dart';
part 'views/golden_hour_view.dart';
part 'views/needs_view.dart';
part 'views/kpis_view.dart';
part 'views/table_view.dart';
part 'views/dashboard_common.dart';

/// RLS-scoped dashboard. Four tabs mirroring the reference iOS app (+ our spreadsheet):
///  • Baptisms    — prospective baptisms (people being taught), by planned baptism date.
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
    'person_uuid, stake_id, unit_id, name, unit_name, baptism_date, birth_date, membership_duration, sex, friends, friends_count, '
    'aaronic_priesthood, melchizedek_priesthood, calling, ministering_brothers_sisters, '
    'ministering_assignment, temple_recommend, patriarchal_blessing, living_ordinance, details, photo_url, '
    'kind, baptism_goal_date';

// Each tab carries its own accent color so the nav reads at a glance (#nav). "Baptisms" = people
// being taught who have a planned baptism date (the old "Upcoming"). Colors are a distinct nav
// palette (not the status green/amber/red or the org teal/blue/rose).
const _tabs = [
  (icon: Icons.event_available, label: 'Baptisms', color: Color(0xFF0277BD)),   // blue
  (icon: Icons.timelapse, label: 'Golden Hour', color: Color(0xFFF9A825)),      // gold/amber
  (icon: Icons.checklist, label: 'Needs', color: Color(0xFFD84315)),            // deep orange
  (icon: Icons.insights, label: 'KPIs', color: Color(0xFF2E7D32)),             // green
  (icon: Icons.grid_on, label: 'Table', color: Color(0xFF5E35B1)),            // deep purple
];

/// App-bar title that doubles as a stake switcher when the viewer can see more than one stake
/// (power users / operators). With a single stake it's just the stake name — one stake at a time;
/// cross-stake browsing for ops/stats lives in the Admin console.
class _StakeTitle extends StatelessWidget {
  const _StakeTitle({required this.stakes, required this.currentId,
      required this.fallback, required this.onSelect});
  final List<Map<String, dynamic>> stakes;
  final String? currentId;
  final String fallback;
  final void Function(String id) onSelect;

  @override
  Widget build(BuildContext context) {
    final title = FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: Text(fallback));
    if (stakes.length < 2) return title;
    return PopupMenuButton<String>(
      tooltip: 'Switch stake',
      onSelected: onSelect,
      itemBuilder: (_) => [
        for (final s in stakes)
          CheckedPopupMenuItem<String>(
            value: s['id'] as String,
            checked: s['id'] == currentId,
            child: Text('${s['name'] ?? '—'}'),
          ),
      ],
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Flexible(child: title),
        const Icon(Icons.arrow_drop_down),
      ]),
    );
  }
}

class _DashboardPageState extends State<DashboardPage> {
  late Future<List<Map<String, dynamic>>> _future;
  int _tab = 0;
  bool _isAdmin = false;
  List<Map<String, dynamic>> _stakes = const [];
  String? _currentStakeId; // the single stake the dashboard is scoped to (switcher-selectable)
  String? _stakeName;
  String? _lastSynced;
  bool _syncing = false;
  DateTime? _syncStartedAt;
  Timer? _syncPoll; // N3: while a sync runs, re-checks sync_state every ~5s so the banner self-clears
  EnrollmentStatus? _enrollStatus;
  Map<String, List<Map<String, dynamic>>> _missionaries = const {}; // unit name → assigned missionaries

  @override
  void initState() {
    super.initState();
    _future = _bootstrap();
    _checkAdmin();
    // Industry-standard passkey upsell: once, after the user reaches the app, suggest enrolling a
    // passkey for password-free sign-in next time — but only where passkeys actually work.
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeSuggestPasskey());
  }

  @override
  void dispose() {
    _syncPoll?.cancel();
    super.dispose();
  }

  /// One-time, dismissible nudge to add a passkey (only when the platform supports it). We remember
  /// that we've asked so we never nag; "Add" reuses the same enrollment flow as Settings.
  Future<void> _maybeSuggestPasskey() async {
    if (!PasskeyClient().available) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      if (prefs.getBool('passkey_suggested') == true) return;
      await prefs.setBool('passkey_suggested', true);
    } catch (_) {
      return; // if we can't remember the prompt, don't risk nagging — skip it
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      duration: const Duration(seconds: 8),
      content: const Text('Tip: add a passkey to sign in without a password next time.'),
      action: SnackBarAction(label: 'Add passkey', onPressed: _addPasskey),
    ));
  }

  /// Resolve which single stake to show BEFORE the first member query, so the dashboard is scoped
  /// to one stake from the start. A leader sees only their own stake; multi-stake power users get a
  /// switcher in the app bar; cross-stake browsing for ops/stats lives in the Admin console.
  Future<List<Map<String, dynamic>>> _bootstrap() async {
    await _loadStakes();
    final rows = await _load();
    if (rows.isEmpty && mounted) _loadEnrollStatus();
    return rows;
  }

  Future<void> _loadEnrollStatus() async {
    final broker = BrokerClient();
    if (!broker.available) return;
    try {
      final s = await broker.enrollmentStatus();
      if (mounted) setState(() => _enrollStatus = s);
    } catch (_) {}
  }

  Future<void> _checkAdmin() async {
    try {
      if (await supabase.rpc('is_admin') == true && mounted) setState(() => _isAdmin = true);
    } catch (_) {}
  }

  Future<void> _loadStakes() async {
    try {
      final rows = await supabase.from('stakes')
          .select('id, name, last_synced_at, sync_state, sync_started_at, missionaries');
      final list = (rows as List).cast<Map<String, dynamic>>();
      if (list.isEmpty) return;
      // freshest stake first, so an unset default lands on the most recent scrape
      list.sort((a, b) => (b['last_synced_at'] ?? '')
          .toString()
          .compareTo((a['last_synced_at'] ?? '').toString()));
      String? current = _currentStakeId;
      if (current == null) {
        try {
          current = (await SharedPreferences.getInstance()).getString('current_stake_id');
        } catch (_) {}
      }
      // keep the remembered choice only if still visible; otherwise default to the freshest stake
      if (current == null || !list.any((s) => s['id'] == current)) {
        current = list.first['id'] as String?;
      }
      if (!mounted) return;
      setState(() {
        _stakes = list;
        _currentStakeId = current;
      });
      _applyCurrentStake();
    } catch (_) {}
  }

  /// Recompute the single-stake view state (title, freshness chip, missionaries, syncing banner)
  /// from the selected stake only — never merge across stakes.
  void _applyCurrentStake() {
    if (_stakes.isEmpty) return;
    final s = _stakes.firstWhere((e) => e['id'] == _currentStakeId, orElse: () => _stakes.first);
    final miss = <String, List<Map<String, dynamic>>>{};
    final m = s['missionaries'];
    if (m is Map) {
      m.forEach((k, v) {
        if (v is List) {
          miss['$k'] = v.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList();
        }
      });
    }
    DateTime? running;
    if (s['sync_state'] == 'running') {
      final started = DateTime.tryParse('${s['sync_started_at'] ?? ''}');
      // only treat as syncing if it started recently — guards a crashed run that never marked 'done'
      if (started != null && DateTime.now().toUtc().difference(started.toUtc()).inMinutes < 30) {
        running = started;
      }
    }
    setState(() {
      _stakeName = s['name'] as String?;
      _lastSynced = s['last_synced_at']?.toString();
      _missionaries = miss;
      _syncing = running != null;
      _syncStartedAt = running;
    });
    _manageSyncPoll();
  }

  /// While a sync is running, re-check the stake's sync_state every ~5s (N3) so the "syncing…"
  /// banner clears itself and fresh data appears without a manual refresh.
  void _manageSyncPoll() {
    if (_syncing) {
      _syncPoll ??= Timer.periodic(const Duration(seconds: 5), (_) => _pollSyncState());
    } else {
      _syncPoll?.cancel();
      _syncPoll = null;
    }
  }

  Future<void> _pollSyncState() async {
    final id = _currentStakeId;
    if (id == null) return;
    try {
      final rows = await supabase.from('stakes')
          .select('id, name, last_synced_at, sync_state, sync_started_at, missionaries')
          .eq('id', id);
      final list = (rows as List).cast<Map<String, dynamic>>();
      if (list.isEmpty || !mounted) return;
      final idx = _stakes.indexWhere((e) => e['id'] == id);
      if (idx >= 0) _stakes[idx] = list.first;
      final wasSyncing = _syncing;
      _applyCurrentStake(); // recomputes _syncing + (re)manages this timer
      if (wasSyncing && !_syncing) _refresh(); // sync finished → pull the fresh members
    } catch (_) {}
  }

  Future<void> _switchStake(String id) async {
    if (id == _currentStakeId) return;
    setState(() => _currentStakeId = id);
    _applyCurrentStake();
    try {
      await (await SharedPreferences.getInstance()).setString('current_stake_id', id);
    } catch (_) {}
    setState(() => _future = _load());
    await _future;
  }

  Future<List<Map<String, dynamic>>> _load() async {
    // Scope to the selected stake — never return the RLS union of every stake the viewer has a role
    // in (that merged two stakes into one "141 members" list). RLS is still the gate underneath.
    final base = supabase.from('members').select(_columns);
    final filtered = _currentStakeId != null ? base.eq('stake_id', _currentStakeId!) : base;
    final rows = await filtered.order('unit_name').order('name');
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

  Future<void> _contactSupport() async {
    final subjectC = TextEditingController();
    final bodyC = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Contact support'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Send a message to the app owner. They\'ll reply to your sign-in email.',
              style: TextStyle(fontSize: 13)),
          const SizedBox(height: 8),
          TextField(
              controller: subjectC,
              decoration: const InputDecoration(labelText: 'Subject (optional)')),
          const SizedBox(height: 8),
          TextField(
              controller: bodyC,
              autofocus: true,
              minLines: 3,
              maxLines: 6,
              decoration: const InputDecoration(labelText: 'How can we help?')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Send')),
        ],
      ),
    );
    if (ok != true || bodyC.text.trim().isEmpty) return;
    try {
      await BrokerClient().contact(subjectC.text.trim(), bodyC.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Message sent — thank you!')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Couldn\'t send: $e')));
      }
    }
  }

  Future<void> _generateReport() async {
    final broker = BrokerClient();
    if (!broker.available) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Reports need Church-account login configured.')));
      return;
    }
    showDialog(
        context: context,
        barrierDismissible: false,
        builder: (_) => const Center(child: CircularProgressIndicator()));
    Map<String, dynamic>? rep;
    try {
      rep = await broker.report();
    } catch (e) {
      if (mounted) {
        Navigator.pop(context); // spinner
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Couldn\'t build report: $e')));
      }
      return;
    }
    if (!mounted) return;
    Navigator.pop(context); // spinner
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => _ReportSheet(report: rep!, onEmail: _emailReport),
    );
  }

  Future<void> _emailReport() async {
    try {
      final res = await BrokerClient().emailReport();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Report emailed to ${res['to'] ?? 'you'}.')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Couldn\'t email report: $e')));
      }
    }
  }

  Future<void> _addPasskey() async {
    final pk = PasskeyClient();
    if (!pk.available) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Passkeys are available in the web app.')));
      return;
    }
    try {
      await pk.register();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Passkey added — next time, sign in with a passkey (no password).')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Could not add passkey: $e')));
      }
    }
  }

  void _openAdmin() =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AdminPage()));
  void _openInvite() =>
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const InvitePage()));
  void _openSettings() => Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => SettingsPage(
          onFeedback: _sendFeedback, onContact: _contactSupport, onAddPasskey: _addPasskey)));

  void _openSyncSettings() {
    final broker = BrokerClient();
    if (!broker.available) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Sync settings require Church account login.')));
      return;
    }
    // Open the sheet INSTANTLY with a content-shaped skeleton; resolve status in the background so
    // it never jumps from blank to content (#shimmer). Cache the result so a re-open is immediate.
    final future = _enrollStatus != null
        ? Future<EnrollmentStatus?>.value(_enrollStatus)
        : broker.enrollmentStatus().then((s) {
            if (mounted) setState(() => _enrollStatus = s);
            return s;
          });
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => _SyncSettingsSheet(
          statusFuture: future, onRevoke: _revokeCredential, onSyncNow: _syncNow),
    );
  }

  Future<void> _syncNow() async {
    Navigator.of(context).maybePop(); // close the sheet/dialog that triggered it
    try {
      final res = await BrokerClient().syncNow();
      if (!mounted) return;
      final partial = res['coverage_complete'] == false;
      // Optimistically show the in-progress state right away (#freshness "see the sync in progress")
      // so the banner + freshness chip update immediately; reconcile with the real stakes.sync_state
      // a few seconds later once the job has marked itself running.
      setState(() {
        _syncing = true;
        _syncStartedAt = DateTime.now().toUtc();
      });
      _manageSyncPoll();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(partial
              ? 'Sync started — note: your calling can\'t pull every field, so some data stays blank. Takes a few minutes.'
              : 'Sync started for your stake — this takes a few minutes.')));
      Future.delayed(const Duration(seconds: 8), () {
        if (mounted) _loadStakes();
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Couldn\'t start sync: $e')));
      }
    }
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

  /// Decluttered app bar (#navbar): at most 3 items on every screen size — the freshness chip, a
  /// Refresh button, and one "⋯" menu. The menu holds ≤5 primary actions; everything else
  /// (appearance, security, support, about, account) lives on the Settings screen.
  List<Widget> _appBarActions(ScreenTier tier) {
    return [
      if (_lastSynced != null)
        _LastUpdated(
            iso: _lastSynced!,
            compact: tier == ScreenTier.mobile,
            syncing: _syncing,
            onSyncNow: BrokerClient().available ? _syncNow : null),
      IconButton(tooltip: 'Refresh', onPressed: _refresh, icon: const Icon(Icons.refresh)),
      PopupMenuButton<String>(
        tooltip: 'Menu',
        icon: const Icon(Icons.menu),
        onSelected: (v) {
          switch (v) {
            case 'sync':
              _openSyncSettings();
            case 'report':
              _generateReport();
            case 'invite':
              _openInvite();
            case 'admin':
              _openAdmin();
            case 'settings':
              _openSettings();
          }
        },
        itemBuilder: (_) => [
          const PopupMenuItem(
              value: 'sync',
              child: ListTile(leading: Icon(Icons.sync), title: Text('Sync settings'))),
          const PopupMenuItem(
              value: 'report',
              child: ListTile(
                  leading: Icon(Icons.summarize_outlined), title: Text('Generate report'))),
          const PopupMenuItem(
              value: 'invite',
              child: ListTile(
                  leading: Icon(Icons.person_add_alt), title: Text('Invite a power user'))),
          if (_isAdmin)
            const PopupMenuItem(
                value: 'admin',
                child: ListTile(
                    leading: Icon(Icons.admin_panel_settings),
                    title: Text('Admin · Ops console'))),
          const PopupMenuItem(
              value: 'settings',
              child: ListTile(leading: Icon(Icons.settings_outlined), title: Text('Settings'))),
        ],
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final tier = tierFor(c.maxWidth);
      // FittedBox scales the title down to fit instead of truncating — full stake name visible (#48).
      final appBar = AppBar(
          title: _StakeTitle(
              stakes: _stakes,
              currentId: _currentStakeId,
              fallback: _stakeName ?? 'Covenant Path',
              onSelect: _switchStake),
          actions: _appBarActions(tier));
      final staleCred = _enrollStatus?.credential.isRevoked == true;
      final body = Column(children: [
        if (_syncing) _SyncingBanner(startedAt: _syncStartedAt),
        if (staleCred) _StaleBanner(onReenroll: () => supabase.auth.signOut()),
        Expanded(
          child: _Body(tab: _tab, tier: tier, future: _future, onRefresh: _refresh,
              onOpen: _open, enrollStatus: _enrollStatus, missionaries: _missionaries),
        ),
      ]);

      if (tier == ScreenTier.mobile) {
        // Frosted "glass" bottom nav (#41): the body extends behind it and a BackdropFilter blurs
        // the content scrolling underneath. _Page / the table add bottom clearance so nothing hides.
        final c = Theme.of(context).colorScheme;
        return Scaffold(
          appBar: appBar,
          extendBody: true,
          body: body,
          bottomNavigationBar: ClipRect(
            child: BackdropFilter(
              filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
              child: NavigationBar(
                backgroundColor: c.surface.withValues(alpha: 0.72),
                elevation: 0,
                selectedIndex: _tab,
                onDestinationSelected: (i) => setState(() => _tab = i),
                destinations: [
                  for (final t in _tabs)
                    NavigationDestination(
                        icon: Icon(t.icon, color: t.color.withValues(alpha: 0.6)),
                        selectedIcon: Icon(t.icon, color: t.color),
                        label: t.label),
                ],
              ),
            ),
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
            extended: true, // #navbar: text next to icons on tablet + desktop
            minExtendedWidth: 168,
            destinations: [
              for (final t in _tabs)
                NavigationRailDestination(
                    icon: Icon(t.icon, color: t.color.withValues(alpha: 0.6)),
                    selectedIcon: Icon(t.icon, color: t.color),
                    label: Text(t.label)),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(child: body),
        ]),
      );
    });
  }
}
