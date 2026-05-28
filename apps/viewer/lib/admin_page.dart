import 'package:flutter/material.dart';

import 'admin_client.dart';
import 'main.dart';

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
    final actions = await c.actions();
    final admins = await supabase.from('app_admins').select('email, invited_by_email');
    return _AdminData(summary, actions, (admins as List).cast<Map<String, dynamic>>());
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

  Future<void> _rescrape() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Rescrape now?'),
        content: const Text(
            'This dispatches the daily sync on GitHub: re-scrapes LCR and repopulates '
            'Google Sheets + Supabase. It runs in the cloud and takes a few minutes.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Rescrape')),
        ],
      ),
    );
    if (ok != true) return;
    await _guard(() async {
      await _client.run('daily-sync.yml');
      _snack('Rescrape dispatched. Refresh in a minute to see the run.');
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
      await supabase.rpc('invite_admin', params: {'p_email': email});
      _snack('$email is now an admin.');
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
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  _HealthCard(d: d),
                  _FreshnessCard(d: d),
                  _MaintenanceCard(onRescrape: _busy ? null : _rescrape, d: d),
                  _RunsCard(d: d, onRerun: _busy ? null : _rerun),
                  _ChangelogCard(d: d),
                  _AdminsCard(d: d, onInvite: _busy ? null : _inviteAdmin, onRevoke: _revokeAdmin),
                  const SizedBox(height: 24),
                ],
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
  _AdminData(this.summary, this.actions, this.admins);
  final Map<String, dynamic> summary;
  final Map<String, dynamic> actions;
  final List<Map<String, dynamic>> admins;

  Map<String, dynamic> get sb =>
      (summary['supabase'] as Map?)?.cast<String, dynamic>() ?? const {};
  bool get githubConfigured => summary['github_configured'] == true;
  List<Map<String, dynamic>> get runs =>
      ((actions['runs'] as List?) ?? const []).cast<Map<String, dynamic>>();
  List<Map<String, dynamic>> get commits =>
      ((actions['commits'] as List?) ?? const []).cast<Map<String, dynamic>>();
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
  const _MaintenanceCard({required this.onRescrape, required this.d});
  final VoidCallback? onRescrape;
  final _AdminData d;
  @override
  Widget build(BuildContext context) {
    return _Card(
      title: 'Maintenance',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Re-scrape LCR and repopulate Google Sheets + Supabase. '
            'Runs in the cloud via GitHub Actions.'),
        const SizedBox(height: 10),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: d.githubConfigured ? onRescrape : null,
            icon: const Icon(Icons.cloud_sync),
            label: const Text('Rescrape + repopulate'),
          ),
        ),
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
              leading: const Icon(Icons.commit, size: 18),
              title: Text('${c['message']}'),
              subtitle: Text('${c['sha']} · ${c['author'] ?? ''} · ${_ago(c['date'])}'),
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
