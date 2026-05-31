part of '../dashboard_page.dart';

class _Body extends StatelessWidget {
  const _Body({required this.tab, required this.tier, required this.future,
      required this.onRefresh, required this.onOpen, this.enrollStatus,
      this.missionaries = const {}});
  final int tab;
  final ScreenTier tier;
  final Future<List<Map<String, dynamic>>> future;
  final Future<void> Function() onRefresh;
  final void Function(Map<String, dynamic>) onOpen;
  final EnrollmentStatus? enrollStatus;
  final Map<String, List<Map<String, dynamic>>> missionaries; // unit name → assigned missionaries

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
          0 => _OnDateView(rows: rows, tier: tier, onOpen: onOpen, missionaries: missionaries),
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
      title = 'Setting up your stake…';
      body = 'Your credential is saved and the first sync is running — your stake\'s data will '
          'appear here in a few minutes. Pull down to refresh. (It also refreshes daily at 7 am ET.)';
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
      content: const Text('Sync paused — credential revoked. Re-enroll to resume daily updates.'),
      leading: const Icon(Icons.sync_problem, color: Colors.orange),
      actions: [TextButton(onPressed: onReenroll, child: const Text('Re-enroll'))],
    );
  }
}

class _ReportSheet extends StatelessWidget {
  const _ReportSheet({required this.report, required this.onEmail});
  final Map<String, dynamic> report;
  final Future<void> Function() onEmail;

  @override
  Widget build(BuildContext context) {
    final total = report['total'] ?? 0;
    final onTrack = report['on_track'] ?? 0;
    final outstanding = ((report['outstanding'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final byMilestone = ((report['by_milestone'] as List?) ?? const []).cast<List>();
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.7,
      maxChildSize: 0.95,
      builder: (_, scroll) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
                child: Text(report['stake_name']?.toString() ?? 'Convert report',
                    style: Theme.of(context).textTheme.titleLarge)),
            FilledButton.icon(
                onPressed: () async {
                  await onEmail();
                  if (context.mounted) Navigator.pop(context);
                },
                icon: const Icon(Icons.email_outlined, size: 18),
                label: const Text('Email to me')),
          ]),
          const SizedBox(height: 4),
          Text('$total new members · $onTrack on track · ${outstanding.length} need attention',
              style: Theme.of(context).textTheme.bodyMedium),
          const Divider(height: 20),
          Expanded(
            child: ListView(controller: scroll, children: [
              if (byMilestone.isNotEmpty) ...[
                Text('Most-needed steps', style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 6),
                for (final kv in byMilestone)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                      Flexible(child: Text('${kv[0]}')),
                      Text('${kv[1]}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    ]),
                  ),
                const Divider(height: 20),
              ],
              if (outstanding.isEmpty)
                const Padding(
                    padding: EdgeInsets.symmetric(vertical: 20),
                    child: Center(child: Text('Everyone in scope is on track. 🎉')))
              else ...[
                Text('Outstanding by member', style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 6),
                for (final o in outstanding)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(
                          '${o['name']}'
                          '${o['unit'] != null ? ' · ${o['unit']}' : ''}',
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text(((o['missing'] as List?) ?? const []).join(', '),
                          style: TextStyle(
                              fontSize: 13, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ]),
                  ),
              ],
            ]),
          ),
        ]),
      ),
    );
  }
}

class _SyncSettingsSheet extends StatelessWidget {
  const _SyncSettingsSheet({this.status, this.onRevoke, this.onSyncNow});
  final EnrollmentStatus? status;
  final VoidCallback? onRevoke;
  final VoidCallback? onSyncNow;

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
            if (onSyncNow != null) ...[
              const SizedBox(height: 16),
              FilledButton.icon(
                  onPressed: onSyncNow,
                  icon: const Icon(Icons.sync),
                  label: const Text('Sync my stake now')),
            ],
            if (onRevoke != null) ...[
              const SizedBox(height: 8),
              OutlinedButton.icon(
                  onPressed: () {
                    Navigator.pop(context);
                    onRevoke!();
                  },
                  icon: const Icon(Icons.link_off),
                  label: const Text('Revoke my sync access')),
            ],
            const _GoogleDriveSection(), // M7: connect Drive so the stake owns its own sheet
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

/// M7: per-stake Google Drive. Self-gating — renders only when the broker has OAuth configured and
/// the signed-in user is their stake's sync provider. Connect → the stake's sheet lives in THEIR
/// Drive (which the platform can't do with a 0-storage service account).
class _GoogleDriveSection extends StatefulWidget {
  const _GoogleDriveSection();
  @override
  State<_GoogleDriveSection> createState() => _GoogleDriveSectionState();
}

class _GoogleDriveSectionState extends State<_GoogleDriveSection> {
  Map<String, dynamic>? _status;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await BrokerClient().googleDriveStatus();
      if (mounted) setState(() => _status = s);
    } catch (_) {/* leave hidden on error */}
  }

  void _snack(String m) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
  }

  Future<void> _connect() async {
    setState(() => _busy = true);
    try {
      final r = await BrokerClient().googleDriveStart();
      final url = r['url'] as String?;
      if (url != null && url.isNotEmpty) {
        await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
        _snack('Finish in the Google window, then tap "Refresh".');
      }
    } catch (e) {
      _snack('Could not start: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disconnect() async {
    setState(() => _busy = true);
    try {
      await BrokerClient().googleDriveDisconnect();
      await _load();
    } catch (e) {
      _snack('Could not disconnect: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _status;
    if (s == null || s['configured'] != true || s['eligible'] != true) {
      return const SizedBox.shrink();
    }
    final connected = s['connected'] == true;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Divider(height: 24),
      Row(children: [
        Icon(Icons.add_to_drive, size: 18, color: Theme.of(context).colorScheme.primary),
        const SizedBox(width: 8),
        Text('Google Drive', style: Theme.of(context).textTheme.titleSmall),
      ]),
      const SizedBox(height: 4),
      Text(
        connected
            ? 'Connected as ${s['email'] ?? ''}. Your stake\'s spreadsheet lives in your Drive.'
            : 'Connect your Google account so your stake gets its own spreadsheet that you own '
                '(the app can only touch the file it creates).',
        style: const TextStyle(fontSize: 13),
      ),
      const SizedBox(height: 8),
      Row(children: [
        if (!connected)
          FilledButton.icon(
              onPressed: _busy ? null : _connect,
              icon: const Icon(Icons.add_to_drive, size: 18),
              label: const Text('Connect Google Drive'))
        else
          OutlinedButton.icon(
              onPressed: _busy ? null : _disconnect,
              icon: const Icon(Icons.link_off, size: 18),
              label: const Text('Disconnect')),
        const SizedBox(width: 8),
        TextButton(onPressed: _busy ? null : _load, child: const Text('Refresh')),
      ]),
    ]);
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
