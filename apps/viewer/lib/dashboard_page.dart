import 'dart:async';
import 'dart:ui' show ImageFilter;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
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

part 'views/dashboard_shell.dart';
part 'views/upcoming_view.dart';
part 'views/golden_hour_view.dart';
part 'views/needs_view.dart';
part 'views/kpis_view.dart';
part 'views/table_view.dart';
part 'views/dashboard_common.dart';

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
  DateTime? _syncStartedAt;
  EnrollmentStatus? _enrollStatus;
  Map<String, List<Map<String, dynamic>>> _missionaries = const {}; // unit name → assigned missionaries

  @override
  void initState() {
    super.initState();
    _future = _load();
    _future.then((rows) {
      if (rows.isEmpty && mounted) _loadEnrollStatus();
    }).catchError((_) {});
    _checkAdmin();
    _loadStakeName();
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

  Future<void> _loadStakeName() async {
    try {
      final rows = await supabase.from('stakes')
          .select('name, last_synced_at, sync_state, sync_started_at, missionaries');
      final list = (rows as List).cast<Map<String, dynamic>>();
      if (list.isEmpty || !mounted) return;
      // freshest stake first, so the chip reflects the most recent scrape the user can see
      list.sort((a, b) => (b['last_synced_at'] ?? '')
          .toString()
          .compareTo((a['last_synced_at'] ?? '').toString()));
      setState(() {
        _stakeName = list.first['name'];
        _lastSynced = list.first['last_synced_at']?.toString();
        // unit name → assigned full-time missionaries (#29), merged across visible stakes
        final miss = <String, List<Map<String, dynamic>>>{};
        for (final s in list) {
          final m = s['missionaries'];
          if (m is Map) {
            m.forEach((k, v) {
              if (v is List) {
                miss['$k'] = v.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList();
              }
            });
          }
        }
        _missionaries = miss;
        // only treat as syncing if it started recently — guards against a crashed run that
        // never got to mark itself 'done' leaving a permanently stuck banner.
        DateTime? running;
        for (final s in list) {
          if (s['sync_state'] != 'running') continue;
          final started = DateTime.tryParse('${s['sync_started_at'] ?? ''}');
          // only treat as syncing if it started recently — guards against a crashed run that
          // never got to mark itself 'done' leaving a permanently stuck banner.
          if (started != null && DateTime.now().toUtc().difference(started.toUtc()).inMinutes < 30) {
            running = started;
            break;
          }
        }
        _syncing = running != null;
        _syncStartedAt = running;
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
    final isProvider = status?.credential.isProvider == true;
    showModalBottomSheet(
      context: context,
      builder: (ctx) => _SyncSettingsSheet(
          status: status,
          onRevoke: isProvider ? _revokeCredential : null,
          onSyncNow: isProvider ? _syncNow : null),
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
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(partial
              ? 'Sync started — note: your calling can\'t pull every field, so some data stays blank. Takes a few minutes.'
              : 'Sync started for your stake — this takes a few minutes.')));
      Future.delayed(const Duration(seconds: 8), () {
        if (mounted) _loadStakeName();
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
          title: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text(_stakeName ?? 'Covenant Path')),
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
                  for (final t in _tabs) NavigationDestination(icon: Icon(t.icon), label: t.label),
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
