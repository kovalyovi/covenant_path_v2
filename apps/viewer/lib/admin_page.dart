import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'admin_client.dart';
import 'golden_hour.dart';
import 'main.dart';

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

  late Future<_AdminData> _future;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<_AdminData> _load() async {
    final c = _client;
    final summary = await c.summary();
    // GitHub Actions is optional — a token/scope/repo issue must not stop the console from
    // opening (this was the "ops console won't open / 404" bug). Load it best-effort.
    Map<String, dynamic> actions = const {};
    String? actionsError;
    try {
      actions = await c.actions();
    } catch (e) {
      actionsError = '$e';
    }
    final diagnostics = await c.diagnostics();
    final admins = await supabase.from('app_admins').select('email, invited_by_email');
    return _AdminData(summary, actions, diagnostics,
        (admins as List).cast<Map<String, dynamic>>(), actionsError);
  }

  Future<void> _refresh() async {
    setState(() => _future = _load());
    await _future;
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
        FutureBuilder<_AdminData>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text('Could not load the console:\n${snap.error}',
                      textAlign: TextAlign.center),
                ),
              );
            }
            final d = snap.data!;
            return RefreshIndicator(
              onRefresh: _refresh,
              child: MaxWidthBody(
                maxWidth: 900,
                child: ListView(
                  padding: const EdgeInsets.all(12),
                  children: [
                    _HealthCard(d: d),
                    _FreshnessCard(d: d),
                    _MaintenanceCard(onRun: _busy ? null : _dispatch, d: d),
                    _DiagnosticsCard(d: d),
                    if (d.actionsError != null)
                      _Card(
                        title: 'GitHub Actions',
                        child: Text(
                          'Unavailable: ${d.actionsError}\n\nThe rest of the console works. To '
                          'enable runs + changelog, set GITHUB_TOKEN on the broker (fine-grained '
                          'PAT with Actions: read & write, Contents: read) scoped to the repo.',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      )
                    else ...[
                      _RunsCard(d: d, onRerun: _busy ? null : _rerun),
                      _ChangelogCard(d: d),
                    ],
                    _LinksCard(d: d),
                    _AdminsCard(d: d, onInvite: _busy ? null : _inviteAdmin, onRevoke: _revokeAdmin),
                    const SizedBox(height: 24),
                  ],
                ),
              ),
            );
          },
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
}

class _AdminData {
  _AdminData(this.summary, this.actions, this.diagnostics, this.admins, [this.actionsError]);
  final Map<String, dynamic> summary;
  final Map<String, dynamic> actions;
  final Map<String, dynamic> diagnostics;
  final List<Map<String, dynamic>> admins;
  final String? actionsError;

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
    return _Card(
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

class _Card extends StatelessWidget {
  const _Card({required this.title, required this.child, this.trailing});
  final String title;
  final Widget child;
  final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
                child: Text(title,
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold))),
            if (trailing != null) trailing!,
          ]),
          const SizedBox(height: 10),
          child,
        ]),
      ),
    );
  }
}

class _HealthCard extends StatelessWidget {
  const _HealthCard({required this.d});
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    final brokerOk = (d.summary['broker'] as Map?)?['ok'] == true;
    final sbOk = d.sb['ok'] == true;
    return _Card(
      title: 'System health',
      child: Wrap(spacing: 10, runSpacing: 10, children: [
        _Pill(label: 'Broker', ok: brokerOk),
        _Pill(label: 'Supabase', ok: sbOk),
        _Pill(label: 'GitHub Actions', ok: d.githubConfigured,
            offText: 'not linked'),
      ]),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label, required this.ok, this.offText = 'down'});
  final String label;
  final bool ok;
  final String offText;
  @override
  Widget build(BuildContext context) {
    final c = ok ? Colors.green.shade600 : Colors.orange.shade700;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
          color: c.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: c)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(ok ? Icons.check_circle : Icons.error_outline, size: 16, color: c),
        const SizedBox(width: 6),
        Text('$label · ${ok ? 'ok' : offText}', style: TextStyle(color: c)),
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
    return _Card(
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
    return _Card(
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
      return const _Card(title: 'Diagnostics', child: Text('No sync diagnostics yet.'));
    }
    final p = (run['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    final req = (p['requests'] as Map?)?.cast<String, dynamic>() ?? const {};
    final stats = (p['run_stats'] as Map?)?.cast<String, dynamic>() ?? const {};
    final coverage = (p['field_coverage'] as Map?)?.cast<String, dynamic>() ?? const {};
    final endpoints = ((req['endpoints'] as List?) ?? const []).cast<Map>();
    final failed = ((stats['failed_units'] as List?) ?? const []).cast<dynamic>();
    final successPct = (req['success_pct'] as num?)?.toDouble() ?? 100.0;

    return _Card(
      title: 'Diagnostics',
      trailing: Text(_ago(run['run_at']), style: Theme.of(context).textTheme.bodySmall),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 10, runSpacing: 10, children: [
          _Pill(label: 'Requests ${successPct.toStringAsFixed(0)}%', ok: successPct >= 99),
          _Pill(label: 'Units ${(stats['units'] ?? '—')} ok', ok: failed.isEmpty,
              offText: '${failed.length} failed'),
          _Pill(label: '${req['total_errors'] ?? 0} request errors', ok: (req['total_errors'] ?? 0) == 0),
        ]),
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
          Text('Endpoint performance', style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 6),
          for (final ep in endpoints)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(children: [
                Expanded(child: Text('${ep['endpoint']}',
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                    overflow: TextOverflow.ellipsis)),
                Text('${ep['calls']} calls · ${ep['avg_ms']}ms avg'
                    '${(ep['errors'] ?? 0) != 0 ? ' · ${ep['errors']} err' : ''}',
                    style: TextStyle(
                        fontSize: 12,
                        color: (ep['errors'] ?? 0) != 0 ? Colors.red.shade700 : null)),
              ]),
            ),
        ],
      ]),
    );
  }
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
    return _Card(
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
                    subtitle: Text('${r['event']} · ${_ago(r['created_at'])}'),
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
    return _Card(
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
    return _Card(
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

// ---- helpers ---------------------------------------------------------------

Widget _kv(BuildContext context, String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Expanded(child: Text(k)),
        Text(v, style: const TextStyle(fontWeight: FontWeight.w500)),
      ]),
    );

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
