import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import 'admin_client.dart';
import 'golden_hour.dart';
import 'main.dart';
import 'theme/tokens.dart';
import 'widgets/app_card.dart';
import 'widgets/shimmer.dart';
import 'widgets/status.dart';

Future<void> _open(String? url) async {
  if (url == null || url.isEmpty) return;
  final uri = Uri.tryParse(url);
  if (uri != null) await launchUrl(uri, mode: LaunchMode.externalApplication);
}

/// One place to monitor and operate the whole platform — gated server-side by app_admins.
/// Panels: system health, data freshness, maintenance (kick off a rescrape that also
/// repopulates Google Sheets + Supabase), recent GitHub Actions runs, the commit
/// changelog, and admin management (invite/revoke — escalation-safe, see migration 0008).
class AdminPage extends StatefulWidget {
  const AdminPage({super.key});
  @override
  State<AdminPage> createState() => _AdminPageState();
}

class _AdminPageState extends State<AdminPage> {
  AdminClient get _client =>
      AdminClient(supabase.auth.currentSession?.accessToken ?? '');

  bool _busy = false;
  // Each panel loads independently so the page renders immediately and a slow/failed section
  // (e.g. GitHub Actions) only spins/errors in its own card — never blocks the whole console.
  late Future<Map<String, dynamic>> _summaryF;
  late Future<Map<String, dynamic>> _diagF;
  late Future<Map<String, dynamic>> _actionsF;
  late Future<Map<String, dynamic>> _stakesF;
  late Future<List<Map<String, dynamic>>> _adminsF;
  late Future<List<Map<String, dynamic>>> _loginsF;
  late Future<List<Map<String, dynamic>>> _overridesF;

  @override
  void initState() {
    super.initState();
    _loadAll();
  }

  void _loadAll() {
    final c = _client;
    _summaryF = c.summary();
    _diagF = c.diagnostics();
    _actionsF = c.actions();
    _stakesF = c.enrolledStakes();
    _adminsF = supabase
        .from('app_admins')
        .select('email, invited_by_email')
        .then((r) => (r as List).cast<Map<String, dynamic>>());
    // Login audit (admin-only via RLS, migration 0033): who tried, their callings + access + outcome.
    _loginsF = supabase
        .from('login_audit')
        .select('at, email, name, stake_name, callings, authorized, outcome')
        .order('at', ascending: false)
        .limit(50)
        .then((r) => (r as List).cast<Map<String, dynamic>>());
    // #3c: admin-editable calling→access overrides (admin-only via RLS).
    _overridesF = supabase
        .from('calling_access_overrides')
        .select('id, calling_match, grants_access, note')
        .order('calling_match')
        .then((r) => (r as List).cast<Map<String, dynamic>>());
  }

  Future<void> _refresh() async {
    setState(_loadAll);
    await Future.wait([
      _summaryF.catchError((_) => <String, dynamic>{}),
      _diagF.catchError((_) => <String, dynamic>{}),
      _actionsF.catchError((_) => <String, dynamic>{}),
      _stakesF.catchError((_) => <String, dynamic>{}),
      _adminsF.catchError((_) => <Map<String, dynamic>>[]),
      _loginsF.catchError((_) => <Map<String, dynamic>>[]),
      _overridesF.catchError((_) => <Map<String, dynamic>>[]),
    ]);
  }

  // #3c "map it + add new": grant a calling member-data access without a deploy (applied next sync).
  Future<void> _addOverride() async {
    final matchCtrl = TextEditingController();
    final noteCtrl = TextEditingController();
    bool grants = true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('Add a calling override'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
                controller: matchCtrl,
                decoration: const InputDecoration(
                    labelText: 'Calling contains…', hintText: 'e.g. Ward Mission Leader')),
            const SizedBox(height: 8),
            Row(children: [
              Switch(value: grants, onChanged: (v) => setLocal(() => grants = v)),
              const Expanded(child: Text('Grants member-data access')),
            ]),
            TextField(controller: noteCtrl, decoration: const InputDecoration(labelText: 'Note (optional)')),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final match = matchCtrl.text.trim();
    if (match.isEmpty) return;
    await _guard(() async {
      final note = noteCtrl.text.trim();
      await supabase.rpc('add_calling_override',
          params: {'p_match': match, 'p_grants': grants, 'p_note': note.isEmpty ? null : note});
      _snack('Saved override "$match".');
      await _refresh();
    });
  }

  Future<void> _removeOverride(int id, String match) async {
    await _guard(() async {
      await supabase.rpc('remove_calling_override', params: {'p_id': id});
      _snack('Removed "$match".');
      await _refresh();
    });
  }

  Future<void> _revokeStake(String stakeId, String name) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Revoke sync for $name?'),
        content: const Text('Daily sync for this stake will stop until a leader re-enrolls. '
            'You can do this to support a stake whose credential is stale or compromised.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Revoke')),
        ],
      ),
    );
    if (ok != true) return;
    await _guard(() async {
      await _client.revokeStake(stakeId);
      _snack('Revoked sync for $name.');
      await _refresh();
    });
  }

  Future<void> _syncStake(String unit, String name) async {
    if (unit.isEmpty || unit == 'null') {
      _snack('No unit number on file for $name — can\'t scope a sync.');
      return;
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Sync $name now?'),
        content: const Text('Re-scrapes LCR for this one stake and writes to Supabase. Runs in the '
            'cloud (GitHub Actions) and takes a few minutes.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Sync')),
        ],
      ),
    );
    if (ok != true) return;
    await _guard(() async {
      await _client.run('daily-sync.yml', inputs: {'stake': unit, 'targets': 'supabase'});
      _snack('Sync dispatched for $name. Refresh in a minute to see the run.');
      await _refresh();
    });
  }

  void _snack(String msg) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _guard(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } catch (e) {
      _snack('$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _dispatch(String label, String body, Map<String, dynamic> inputs) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('$label?'),
        content: Text('$body It runs in the cloud (GitHub Actions) and takes a few minutes.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(label)),
        ],
      ),
    );
    if (ok != true) return;
    await _guard(() async {
      await _client.run('daily-sync.yml', inputs: inputs);
      _snack('$label dispatched. Refresh in a minute to see the run.');
      await _refresh();
    });
  }

  Future<void> _rerun(int id) =>
      _guard(() async {
        await _client.rerun(id);
        _snack('Re-run requested for #$id.');
        await _refresh();
      });

  Future<void> _inviteAdmin() async {
    final ctrl = TextEditingController();
    final email = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Invite an admin'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(labelText: 'Email', hintText: 'name@example.com'),
          onSubmitted: (v) => Navigator.pop(context, v.trim()),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, ctrl.text.trim()),
              child: const Text('Invite')),
        ],
      ),
    );
    if (email == null || email.isEmpty) return;
    await _guard(() async {
      final res = await _client.invite(email);
      final status = res['status'];
      _snack(status == 'already_admin'
          ? '$email is already an admin.'
          : status == 'pending_owner_approval'
              ? 'Request sent — the owner must approve $email by email.'
              : '$email: $status');
      await _refresh();
    });
  }

  Future<void> _revokeAdmin(String email) => _guard(() async {
        await supabase.rpc('revoke_admin', params: {'p_email': email});
        _snack('Revoked $email.');
        await _refresh();
      });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin · Ops console'),
        actions: [
          IconButton(onPressed: _busy ? null : _refresh, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: Stack(children: [
        RefreshIndicator(
          onRefresh: _refresh,
          child: MaxWidthBody(
            maxWidth: 900,
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                // System + freshness + maintenance + links (from /admin/summary)
                _section<Map<String, dynamic>>(_summaryF, 'System', (s) {
                  final d = _AdminData(s, const {}, const {}, const []);
                  return Column(children: [
                    _HealthCard(d: d),
                    _FreshnessCard(d: d),
                    _MaintenanceCard(onRun: _busy ? null : _dispatch, d: d),
                    _LinksCard(d: d),
                  ]);
                }),
                _section<Map<String, dynamic>>(_diagF, 'Diagnostics', (s) =>
                    _DiagnosticsCard(d: _AdminData(const {}, const {}, s, const []))),
                // Enrolled stakes: cross-stake ops view (who's onboarded, coverage, freshness).
                _section<Map<String, dynamic>>(_stakesF, 'Enrolled stakes', (s) =>
                    _EnrolledStakesCard(
                        stakes: ((s['stakes'] as List?) ?? const []).cast<Map<String, dynamic>>(),
                        onRevoke: _busy ? null : _revokeStake,
                        onSync: _busy ? null : _syncStake)),
                // GitHub Actions: its own card so a token/repo error only affects this section.
                _section<Map<String, dynamic>>(_actionsF, 'GitHub Actions', (a) {
                  final d = _AdminData({'github_configured': a['configured'] == true}, a, const {}, const []);
                  return Column(children: [
                    _RunsCard(d: d, onRerun: _busy ? null : _rerun),
                    _ChangelogCard(d: d),
                  ]);
                }, errorHint: 'Set GITHUB_TOKEN on the broker (Actions: read & write, Contents: '
                    'read) to enable runs + the changelog. The rest of the console still works.'),
                _section<List<Map<String, dynamic>>>(_adminsF, 'Admins', (a) =>
                    _AdminsCard(d: _AdminData(const {}, const {}, const {}, a),
                        onInvite: _busy ? null : _inviteAdmin, onRevoke: _revokeAdmin)),
                // Login audit: debug "leader X can't log in" — who tried, callings, access, outcome.
                _section<List<Map<String, dynamic>>>(_loginsF, 'Recent logins', (rows) =>
                    _LoginAuditCard(rows: rows),
                    errorHint: 'login_audit is admin-only (RLS) — rows appear once the broker '
                        'records logins after its next deploy.'),
                // #3c: admin-editable calling→access overrides.
                _section<List<Map<String, dynamic>>>(_overridesF, 'Calling access overrides', (rows) =>
                    _CallingOverridesCard(
                        rows: rows,
                        onAdd: _busy ? null : _addOverride,
                        onRemove: _busy ? null : _removeOverride),
                    errorHint: 'Admin-only (RLS). Grant a calling access without a deploy — applied next sync.'),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ),
        if (_busy)
          const Positioned.fill(
            child: ColoredBox(
              color: Color(0x33000000),
              child: Center(child: CircularProgressIndicator()),
            ),
          ),
      ]),
    );
  }

  /// A panel that renders immediately as a titled card: spinner while its future loads, a
  /// friendly error (with optional hint) on failure, else the built content.
  Widget _section<T>(Future<T> future, String title, Widget Function(T data) build,
      {String? errorHint}) {
    return FutureBuilder<T>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return AppCard(
              title: '$title…',
              child: const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: CardSkeleton(lines: 3)));
        }
        if (snap.hasError) {
          return AppCard(
            title: title,
            child: Text(
              "Couldn't load: ${snap.error}${errorHint != null ? '\n\n$errorHint' : ''}",
              style: Theme.of(context).textTheme.bodySmall,
            ),
          );
        }
        return build(snap.data as T);
      },
    );
  }
}

class _AdminData {
  _AdminData(this.summary, this.actions, this.diagnostics, this.admins);
  final Map<String, dynamic> summary;
  final Map<String, dynamic> actions;
  final Map<String, dynamic> diagnostics;
  final List<Map<String, dynamic>> admins;

  List<Map<String, dynamic>> get diagRuns =>
      ((diagnostics['runs'] as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic>? get latestSync {
    for (final r in diagRuns) {
      if (r['kind'] == 'sync') return r;
    }
    return null;
  }

  Map<String, dynamic> get sb =>
      (summary['supabase'] as Map?)?.cast<String, dynamic>() ?? const {};
  bool get githubConfigured => summary['github_configured'] == true;
  List<Map<String, dynamic>> get runs =>
      ((actions['runs'] as List?) ?? const []).cast<Map<String, dynamic>>();
  List<Map<String, dynamic>> get commits =>
      ((actions['commits'] as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, String> get links =>
      ((summary['links'] as Map?) ?? const {}).map((k, v) => MapEntry('$k', '$v'));
}

/// Quick links to the platform's external dashboards (admin-only; URLs come from the
/// broker's gated /admin/summary so nothing sensitive is hardcoded in the client).
class _LinksCard extends StatelessWidget {
  const _LinksCard({required this.d});
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    final links = d.links;
    if (links.isEmpty) return const SizedBox.shrink();
    return AppCard(
      title: 'Tools & dashboards',
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        for (final e in links.entries)
          ActionChip(
            avatar: const Icon(Icons.open_in_new, size: 16),
            label: Text(e.key),
            onPressed: () => _open(e.value),
          ),
      ]),
    );
  }
}

// ---- cards -----------------------------------------------------------------

class _HealthCard extends StatelessWidget {
  const _HealthCard({required this.d});
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    final brokerOk = (d.summary['broker'] as Map?)?['ok'] == true;
    final sbOk = d.sb['ok'] == true;
    return AppCard(
      title: 'System health',
      child: Wrap(spacing: 10, runSpacing: 10, children: [
        StatusPill(label: 'Broker', ok: brokerOk),
        StatusPill(label: 'Supabase', ok: sbOk),
        StatusPill(label: 'GitHub Actions', ok: d.githubConfigured,
            offText: 'not linked'),
      ]),
    );
  }
}

class _FreshnessCard extends StatelessWidget {
  const _FreshnessCard({required this.d});
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    final sb = d.sb;
    return AppCard(
      title: 'Data freshness',
      child: Column(children: [
        _kv(context, 'Last member update', _ago(sb['last_member_update'])),
        _kv(context, 'Last stake sync', _ago(sb['last_stake_sync'])),
        const Divider(),
        Wrap(spacing: 18, runSpacing: 8, children: [
          _stat('Members', sb['members']),
          _stat('Units', sb['units']),
          _stat('Stakes', sb['stakes']),
          _stat('Admins', sb['admins']),
        ]),
      ]),
    );
  }

  Widget _stat(String label, dynamic v) => Column(children: [
        Text('${v ?? '—'}',
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
        Text(label),
      ]);
}

class _MaintenanceCard extends StatelessWidget {
  const _MaintenanceCard({required this.onRun, required this.d});
  final void Function(String label, String body, Map<String, dynamic> inputs)? onRun;
  final _AdminData d;

  @override
  Widget build(BuildContext context) {
    final on = d.githubConfigured ? onRun : null;
    return AppCard(
      title: 'Maintenance',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Each flow re-scrapes LCR (required for fresh data); the choice controls '
            'where it writes.'),
        const SizedBox(height: 12),
        Wrap(spacing: 10, runSpacing: 10, children: [
          FilledButton.icon(
            onPressed: on == null ? null : () => on('Full sync',
                'Re-scrapes LCR and repopulates both Google Sheets and Supabase.',
                {'targets': 'both'}),
            icon: const Icon(Icons.cloud_sync),
            label: const Text('Full sync'),
          ),
          OutlinedButton.icon(
            onPressed: on == null ? null : () => on('Supabase only',
                'Re-scrapes LCR and repopulates Supabase (the app data) only.',
                {'targets': 'supabase'}),
            icon: const Icon(Icons.storage),
            label: const Text('Supabase only'),
          ),
          OutlinedButton.icon(
            onPressed: on == null ? null : () => on('Google Sheets only',
                'Re-scrapes LCR and repopulates the Google Sheet only.',
                {'targets': 'sheets'}),
            icon: const Icon(Icons.table_chart),
            label: const Text('Sheets only'),
          ),
          OutlinedButton.icon(
            onPressed: on == null ? null : () => on('Refresh photos',
                'Re-scrapes LCR, updates Supabase, and refreshes member avatars in Storage.',
                {'targets': 'supabase', 'photos': 'true'}),
            icon: const Icon(Icons.photo_camera),
            label: const Text('Refresh photos'),
          ),
        ]),
        if (!d.githubConfigured)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('Link GitHub (set GITHUB_TOKEN on the broker) to enable flows.',
                style: Theme.of(context).textTheme.bodySmall),
          ),
      ]),
    );
  }
}

class _DiagnosticsCard extends StatelessWidget {
  const _DiagnosticsCard({required this.d});
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    final run = d.latestSync;
    if (run == null) {
      return const AppCard(title: 'Diagnostics', child: Text('No sync diagnostics yet.'));
    }
    final p = (run['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    final req = (p['requests'] as Map?)?.cast<String, dynamic>() ?? const {};
    final stats = (p['run_stats'] as Map?)?.cast<String, dynamic>() ?? const {};
    final coverage = (p['field_coverage'] as Map?)?.cast<String, dynamic>() ?? const {};
    final endpoints = ((req['endpoints'] as List?) ?? const []).cast<Map>();
    final failed = ((stats['failed_units'] as List?) ?? const []).cast<dynamic>();
    final successPct = (req['success_pct'] as num?)?.toDouble() ?? 100.0;

    return AppCard(
      title: 'Diagnostics',
      trailing: Text(_ago(run['run_at']), style: Theme.of(context).textTheme.bodySmall),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 10, runSpacing: 10, children: [
          StatusPill(label: 'Requests ${successPct.toStringAsFixed(0)}%', ok: successPct >= 99),
          StatusPill(label: 'Units ${(stats['units'] ?? '—')} ok', ok: failed.isEmpty,
              offText: '${failed.length} failed'),
          StatusPill(label: '${req['total_errors'] ?? 0} request errors', ok: (req['total_errors'] ?? 0) == 0),
        ]),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            // #54: one tap → the whole run's diagnostics as text, ready to paste to Claude. PII-safe
            // (counts/endpoints/coverage only — no names/dates/addresses).
            onPressed: () {
              Clipboard.setData(ClipboardData(
                  text: _claudeDump(run, req, stats, coverage, endpoints, failed)));
              ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Diagnostics copied — paste into Claude.')));
            },
            icon: const Icon(Icons.copy_all, size: 16),
            label: const Text('Copy for Claude'),
            style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
          ),
        ),
        if (failed.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('Failed units: ${failed.join(', ')}',
                style: TextStyle(color: Colors.orange.shade800)),
          ),

        if (coverage.isNotEmpty) ...[
          const SizedBox(height: 14),
          Text('Field parity (filled / blocked / pending)',
              style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 6),
          for (final e in coverage.entries) _ParityRow(field: e.key, c: (e.value as Map).cast<String, dynamic>()),
        ],

        if (endpoints.isNotEmpty) ...[
          const SizedBox(height: 14),
          _EndpointPerf(endpoints: endpoints),
        ],
      ]),
    );
  }
}

/// Cross-stake ops view: every stake's enrollment, coverage, freshness + member count, with an
/// admin revoke for support. "Sync now" reuses the shared daily-sync dispatch (runs all stakes).
class _EnrolledStakesCard extends StatelessWidget {
  const _EnrolledStakesCard({required this.stakes, required this.onRevoke, this.onSync});
  final List<Map<String, dynamic>> stakes;
  final void Function(String stakeId, String name)? onRevoke;
  final void Function(String unitNumber, String name)? onSync;

  @override
  Widget build(BuildContext context) {
    if (stakes.isEmpty) {
      return const AppCard(title: 'Enrolled stakes', child: Text('No stakes yet.'));
    }
    return AppCard(
      title: 'Enrolled stakes (${stakes.length})',
      child: Column(children: [
        for (final s in stakes) _stakeTile(context, s),
      ]),
    );
  }

  Widget _stakeTile(BuildContext context, Map<String, dynamic> s) {
    final cred = (s['credential'] as Map?)?.cast<String, dynamic>();
    final name = '${s['name'] ?? '—'}';
    final stakeId = '${s['stake_id']}';
    final members = s['member_count'] ?? 0;
    final running = s['sync_state'] == 'running';

    final String credLabel;
    final Color credColor;
    if (cred == null) {
      credLabel = 'No credential';
      credColor = AppColors.neutral;
    } else if (cred['state'] == 'revoked') {
      credLabel = 'Revoked';
      credColor = AppColors.warning;
    } else if (cred['complete'] == true) {
      credLabel = 'Active · full coverage';
      credColor = AppColors.success;
    } else {
      credLabel = 'Active · partial';
      credColor = AppColors.info;
    }

    final unitNumber = '${s['unit_number'] ?? ''}';
    final jobs7d = (s['jobs_7d'] as num?)?.toInt() ?? 0;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Row(crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic, children: [
              Flexible(child: Text(name, style: const TextStyle(fontWeight: FontWeight.w600))),
              // Stable LCR stake ID — stakes get renamed, so the ID is how you identify them (#9).
              if (unitNumber.isNotEmpty && unitNumber != 'null') ...[
                const SizedBox(width: 8),
                Text('ID $unitNumber',
                    style: TextStyle(
                        fontFamily: 'monospace', fontSize: 12, color: Colors.grey.shade600)),
              ],
            ]),
          ),
          if (running)
            const Padding(
              padding: EdgeInsets.only(right: 8),
              child: SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
            ),
          // Per-stake sync (#42): scope a fresh scrape to this one stake (active credential only).
          if (!running && cred != null && cred['state'] == 'active' && onSync != null)
            IconButton(
              tooltip: 'Sync this stake now',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.sync, size: 18),
              onPressed: () => onSync!('${s['unit_number'] ?? ''}', name),
            ),
          if (cred != null && cred['state'] == 'active' && onRevoke != null)
            IconButton(
              tooltip: 'Revoke sync (support)',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.link_off, size: 18),
              onPressed: () => onRevoke!(stakeId, name),
            ),
        ]),
        Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          _tag(credLabel, credColor),
          Text('$members members', style: Theme.of(context).textTheme.bodySmall),
          Text('· synced ${_ago(s['last_synced_at'])}', style: Theme.of(context).textTheme.bodySmall),
          // How many sync jobs actually ran for this stake in the last 7 days (#9) — a quick read on
          // whether its schedule is firing. Amber when zero (nothing ran all week).
          Text('· $jobs7d job${jobs7d == 1 ? '' : 's'}/7d',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: jobs7d == 0 ? Colors.orange.shade800 : null)),
          if (cred?['principal_name'] != null)
            Text('· by ${cred!['principal_name']}', style: Theme.of(context).textTheme.bodySmall),
        ]),
        if (cred != null && cred['complete'] != true && (cred['missing'] as List?)?.isNotEmpty == true)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text('Missing: ${(cred['missing'] as List).join(', ')}',
                style: TextStyle(fontSize: 12, color: Colors.orange.shade800)),
          ),
        const Divider(height: 14),
      ]),
    );
  }

  Widget _tag(String text, Color c) => StatusTag(text, color: c);
}

class _ParityRow extends StatelessWidget {
  const _ParityRow({required this.field, required this.c});
  final String field;
  final Map<String, dynamic> c;
  @override
  Widget build(BuildContext context) {
    final filled = (c['filled'] as num?)?.toInt() ?? 0;
    final blocked = (c['blocked'] as num?)?.toInt() ?? 0;
    final pending = (c['pending'] as num?)?.toInt() ?? 0;
    final total = (filled + blocked + pending).clamp(1, 1 << 30);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        SizedBox(width: 150, child: Text(field, overflow: TextOverflow.ellipsis)),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: Row(children: [
              if (filled > 0) Expanded(flex: filled, child: Container(height: 10, color: Colors.green.shade500)),
              if (blocked > 0) Expanded(flex: blocked, child: Container(height: 10, color: Colors.red.shade400)),
              if (pending > 0) Expanded(flex: pending, child: Container(height: 10, color: Colors.grey.shade400)),
            ]),
          ),
        ),
        const SizedBox(width: 8),
        Text('$filled/$total', style: Theme.of(context).textTheme.bodySmall),
      ]),
    );
  }
}

class _RunsCard extends StatelessWidget {
  const _RunsCard({required this.d, required this.onRerun});
  final _AdminData d;
  final void Function(int id)? onRerun;
  @override
  Widget build(BuildContext context) {
    if (!d.githubConfigured) return const SizedBox.shrink();
    final runs = d.runs;
    return AppCard(
      title: 'Recent Actions runs',
      child: runs.isEmpty
          ? const Text('No runs found.')
          : Column(
              children: [
                for (final r in runs)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    onTap: r['html_url'] != null ? () => _open('${r['html_url']}') : null,
                    leading: _RunStatus(status: '${r['status']}', conclusion: '${r['conclusion']}'),
                    title: Text('${r['name']} #${r['run_number']}'),
                    subtitle: Text([
                      '${r['event']}',
                      _ago(r['created_at']),
                      if (_dur(r['duration_seconds']).isNotEmpty)
                        ('${r['status']}' == 'completed'
                            ? 'took ${_dur(r['duration_seconds'])}'
                            : 'running ${_dur(r['duration_seconds'])}'),
                    ].join(' · ')),
                    trailing: ('${r['status']}' != 'in_progress' && '${r['status']}' != 'queued')
                        ? IconButton(
                            tooltip: 'Re-run',
                            icon: const Icon(Icons.replay),
                            onPressed: onRerun == null ? null : () => onRerun!(r['id'] as int),
                          )
                        : const SizedBox(
                            width: 20, height: 20,
                            child: Padding(padding: EdgeInsets.all(2),
                                child: CircularProgressIndicator(strokeWidth: 2))),
                  ),
              ],
            ),
    );
  }
}

class _RunStatus extends StatelessWidget {
  const _RunStatus({required this.status, required this.conclusion});
  final String status;
  final String conclusion;
  @override
  Widget build(BuildContext context) {
    if (status != 'completed') {
      return Icon(Icons.hourglass_top, color: Colors.blue.shade600);
    }
    final ok = conclusion == 'success';
    return Icon(ok ? Icons.check_circle : Icons.cancel,
        color: ok ? Colors.green.shade600 : Colors.red.shade600);
  }
}

class _ChangelogCard extends StatelessWidget {
  const _ChangelogCard({required this.d});
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    if (!d.githubConfigured) return const SizedBox.shrink();
    final commits = d.commits;
    if (commits.isEmpty) return const SizedBox.shrink();
    return AppCard(
      title: 'Changelog',
      child: Column(
        children: [
          for (final c in commits)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              onTap: c['html_url'] != null ? () => _open('${c['html_url']}') : null,
              leading: const Icon(Icons.commit, size: 18),
              title: Text('${c['message']}'),
              subtitle: Text('${c['sha']} · ${c['author'] ?? ''} · ${_ago(c['date'])}'),
              trailing: c['html_url'] != null ? const Icon(Icons.open_in_new, size: 14) : null,
            ),
        ],
      ),
    );
  }
}

class _AdminsCard extends StatelessWidget {
  const _AdminsCard({required this.d, required this.onInvite, required this.onRevoke});
  final _AdminData d;
  final VoidCallback? onInvite;
  final void Function(String email) onRevoke;
  @override
  Widget build(BuildContext context) {
    final me = supabase.auth.currentUser?.email?.toLowerCase();
    return AppCard(
      title: 'Admins',
      trailing: TextButton.icon(
        onPressed: onInvite,
        icon: const Icon(Icons.person_add_alt),
        label: const Text('Invite'),
      ),
      child: Column(
        children: [
          for (final a in d.admins)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.shield_outlined),
              title: Text('${a['email']}'),
              subtitle: (a['invited_by_email'] != null)
                  ? Text('invited by ${a['invited_by_email']}')
                  : null,
              trailing: ('${a['email']}'.toLowerCase() == me)
                  ? const Chip(label: Text('you'), visualDensity: VisualDensity.compact)
                  : IconButton(
                      tooltip: 'Revoke',
                      icon: const Icon(Icons.remove_circle_outline),
                      onPressed: () => onRevoke('${a['email']}'),
                    ),
            ),
        ],
      ),
    );
  }
}

// ---- endpoint troubleshoot (#13–15) ----------------------------------------

/// Collapse an endpoint to its route pattern so calls aggregate — defensive on the CLIENT so even
/// OLD diagnostics rows (captured before the metrics-normalizer fix) group cleanly: a path segment
/// that is `{id}`, an `{id}`-prefixed hex tail, a long hex id, or all-digits becomes `{id}`.
String _normEndpoint(String ep) => ep
    .split('/')
    .map((s) => (s == '{id}' ||
            RegExp(r'^\d+$').hasMatch(s) ||
            RegExp(r'^(\{id\})?[0-9a-fA-F]{8,}$').hasMatch(s))
        ? '{id}'
        : s)
    .join('/');

/// Group raw per-endpoint metrics by route pattern (summing calls/errors, weighting avg latency by
/// calls), sorted FAILING-first then by call volume — the readable view behind #15.
List<Map<String, dynamic>> _groupEndpoints(List endpoints) {
  final by = <String, Map<String, num>>{};
  for (final raw in endpoints) {
    final ep = (raw as Map);
    final key = _normEndpoint('${ep['endpoint'] ?? ''}');
    final calls = (ep['calls'] as num?) ?? 0;
    final avg = (ep['avg_ms'] as num?) ?? 0;
    final g = by.putIfAbsent(key, () => {'calls': 0, 'errors': 0, 'ms': 0, 'max': 0});
    g['calls'] = g['calls']! + calls;
    g['errors'] = g['errors']! + ((ep['errors'] as num?) ?? 0);
    g['ms'] = g['ms']! + avg * calls;
    final mx = (ep['max_ms'] as num?) ?? avg;
    if (mx > g['max']!) g['max'] = mx;
  }
  final out = [
    for (final e in by.entries)
      {
        'endpoint': e.key,
        'calls': e.value['calls'],
        'errors': e.value['errors'],
        'avg_ms': e.value['calls']! > 0 ? (e.value['ms']! / e.value['calls']!).round() : 0,
        'max_ms': e.value['max'],
      }
  ];
  out.sort((a, b) {
    final ec = (b['errors'] as num).compareTo(a['errors'] as num);
    return ec != 0 ? ec : (b['calls'] as num).compareTo(a['calls'] as num);
  });
  return out;
}

/// Endpoint-performance list: grouped by route, failing endpoints first, with a "Failing only / All"
/// toggle so a noisy run collapses to just what's broken (#13–15). Failing rows render in red.
class _EndpointPerf extends StatefulWidget {
  const _EndpointPerf({required this.endpoints});
  final List endpoints;
  @override
  State<_EndpointPerf> createState() => _EndpointPerfState();
}

class _EndpointPerfState extends State<_EndpointPerf> {
  bool _failingOnly = true;

  @override
  Widget build(BuildContext context) {
    final grouped = _groupEndpoints(widget.endpoints);
    final failing = grouped.where((e) => (e['errors'] as num) > 0).toList();
    final hasFailing = failing.isNotEmpty;
    final show = (_failingOnly && hasFailing) ? failing : grouped;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(
            child: Text('Endpoint performance', style: Theme.of(context).textTheme.labelLarge)),
        if (hasFailing)
          TextButton(
            onPressed: () => setState(() => _failingOnly = !_failingOnly),
            style: TextButton.styleFrom(visualDensity: VisualDensity.compact),
            child: Text(_failingOnly ? 'Show all ${grouped.length}' : 'Failing only (${failing.length})'),
          ),
      ]),
      const SizedBox(height: 2),
      for (final ep in show)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(children: [
            Expanded(
                child: Text('${ep['endpoint']}',
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                    overflow: TextOverflow.ellipsis)),
            Text(
                '${ep['calls']} calls · ${ep['avg_ms']}ms avg'
                '${(ep['errors'] as num) != 0 ? ' · ${ep['errors']} err' : ''}',
                style: TextStyle(
                    fontSize: 12,
                    color: (ep['errors'] as num) != 0 ? Colors.red.shade700 : null)),
          ]),
        ),
    ]);
  }
}

// ---- helpers ---------------------------------------------------------------

/// Recent Church-login evaluations (admin-only). Shows who tried, the stake + callings they
/// presented, and the outcome — the tool for debugging "this leader can't log in".
class _LoginAuditCard extends StatelessWidget {
  const _LoginAuditCard({required this.rows});
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return const AppCard(
          title: 'Recent logins', child: Text('No login attempts recorded yet.'));
    }
    return AppCard(
      title: 'Recent logins',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [for (final r in rows) _row(context, r)],
      ),
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> r) {
    final outcome = (r['outcome'] ?? r['authorized'] ?? '').toString();
    final color = outcome == 'blocked'
        ? Colors.red
        : (outcome == 'undetermined' ? Colors.orange : Colors.green);
    final callings = ((r['callings'] as List?) ?? const []).join(', ');
    final at = (r['at'] ?? '').toString();
    final when = at.length >= 16 ? at.substring(0, 16).replaceAll('T', ' ') : at;
    final small = Theme.of(context).textTheme.bodySmall;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(
              child: Text(r['email']?.toString() ?? '(unknown email)',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            StatusTag(outcome.isEmpty ? '—' : outcome, color: color),
          ]),
          if ((r['stake_name'] ?? '').toString().isNotEmpty)
            Text(r['stake_name'].toString(), style: small),
          if (callings.isNotEmpty) Text('Callings: $callings', style: small),
          Text(when, style: small?.copyWith(color: Colors.grey)),
          const Divider(height: 14),
        ],
      ),
    );
  }
}

/// #3c: admin-editable calling→access overrides — grant a calling member-data access without a
/// deploy. The list + an Add button; provisioning unions these in on the next sync.
class _CallingOverridesCard extends StatelessWidget {
  const _CallingOverridesCard({required this.rows, this.onAdd, this.onRemove});
  final List<Map<String, dynamic>> rows;
  final VoidCallback? onAdd;
  final void Function(int id, String match)? onRemove;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      title: 'Calling access overrides',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
                onPressed: onAdd, icon: const Icon(Icons.add), label: const Text('Add')),
          ),
          if (rows.isEmpty)
            const Text('None. Add one to grant a calling member-data access without a code change.')
          else
            for (final o in rows) _row(context, o),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> o) {
    final grants = o['grants_access'] != false;
    final note = (o['note'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Icon(grants ? Icons.vpn_key : Icons.link_off,
            size: 20, color: grants ? Colors.green : Colors.grey),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(o['calling_match']?.toString() ?? ''),
            Text('${grants ? 'grants access' : 'denies access'}${note.isNotEmpty ? ' · $note' : ''}',
                style: Theme.of(context).textTheme.bodySmall),
          ]),
        ),
        IconButton(
          icon: const Icon(Icons.delete_outline, size: 20),
          onPressed: onRemove == null
              ? null
              : () => onRemove!((o['id'] as num).toInt(), o['calling_match']?.toString() ?? ''),
        ),
      ]),
    );
  }
}

Widget _kv(BuildContext context, String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Expanded(child: Text(k)),
        Text(v, style: const TextStyle(fontWeight: FontWeight.w500)),
      ]),
    );

/// PII-safe text dump of a sync run's diagnostics for the "Copy for Claude" button (#54):
/// success rate, failed units, per-field parity, and per-endpoint latency/error counts.
String _claudeDump(Map<String, dynamic> run, Map req, Map stats, Map coverage, List endpoints,
    List failed) {
  final b = StringBuffer()
    ..writeln('Covenant Path — sync diagnostics (PII-safe)')
    ..writeln('run_at: ${run['run_at']}   kind: ${run['kind']}')
    ..writeln('requests: ${req['success_pct'] ?? '?'}% success, ${req['total_errors'] ?? 0} errors')
    ..writeln('units ok: ${stats['units'] ?? '?'}'
        '${failed.isEmpty ? '' : '   failed: ${failed.join(', ')}'}');
  if (coverage.isNotEmpty) {
    b.writeln('field_coverage (filled/blocked/pending):');
    coverage.forEach((k, v) {
      final c = (v as Map);
      b.writeln('  $k: ${c['filled'] ?? 0}/${c['blocked'] ?? 0}/${c['pending'] ?? 0}');
    });
  }
  if (endpoints.isNotEmpty) {
    b.writeln('endpoints (grouped by route, failing first):');
    for (final ep in _groupEndpoints(endpoints)) {
      b.writeln('  ${ep['endpoint']}: ${ep['calls']} calls, ${ep['avg_ms']}ms avg, '
          '${ep['errors'] ?? 0} err');
    }
  }
  return b.toString();
}

String _ago(dynamic iso) {
  if (iso == null) return 'never';
  final t = DateTime.tryParse(iso.toString());
  if (t == null) return iso.toString();
  final diff = DateTime.now().toUtc().difference(t.toUtc());
  if (diff.inMinutes < 1) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}

/// Human duration for a job's execution time (seconds → "45s", "2m 13s", "1h 4m").
String _dur(dynamic seconds) {
  final s = (seconds is num) ? seconds.toInt() : int.tryParse('${seconds ?? ''}');
  if (s == null || s < 0) return '';
  if (s < 60) return '${s}s';
  final m = s ~/ 60, rs = s % 60;
  if (m < 60) return rs == 0 ? '${m}m' : '${m}m ${rs}s';
  final h = m ~/ 60, rm = m % 60;
  return rm == 0 ? '${h}h' : '${h}h ${rm}m';
}
