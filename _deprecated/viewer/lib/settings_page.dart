import 'package:flutter/material.dart';

import 'biometric_gate.dart';
import 'disclaimer.dart';
import 'main.dart';
import 'passkey_client.dart';

/// The grouped Settings screen (#navbar): everything that isn't a primary action lives here —
/// appearance, security, support, about, account — so the app bar stays to ≤3 items + a small menu.
/// Feedback/contact/passkey reuse the dashboard's existing flows (passed in as callbacks).
class SettingsPage extends StatefulWidget {
  const SettingsPage({
    super.key,
    required this.onFeedback,
    required this.onContact,
    required this.onAddPasskey,
    this.stakeId,
    this.sheetsEnabled = false,
  });
  final VoidCallback onFeedback;
  final VoidCallback onContact;
  final VoidCallback onAddPasskey;
  final String? stakeId; // current stake (for the #5b Google Sheets toggle); null → hide the toggle
  final bool sheetsEnabled;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool _lockAvailable = false;
  bool _lockOn = false;
  late bool _sheetsEnabled = widget.sheetsEnabled; // #5b Google Sheets toggle
  bool _sheetsBusy = false;

  @override
  void initState() {
    super.initState();
    _checkLock();
  }

  Future<void> _checkLock() async {
    final avail = await BiometricLock.available();
    final on = await BiometricLock.enabled();
    if (mounted) {
      setState(() {
        _lockAvailable = avail;
        _lockOn = on;
      });
    }
  }

  Future<void> _toggleLock(bool target) async {
    final ok = await BiometricLock.setEnabled(target);
    if (!mounted) return;
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not set up biometric unlock — try again.')));
      return;
    }
    setState(() => _lockOn = target);
  }

  /// #5b: a stake leader toggles Google-Sheet generation for the stake (the RPC enforces the role).
  Future<void> _toggleSheets(bool target) async {
    setState(() => _sheetsBusy = true);
    try {
      await supabase.rpc('set_stake_sheets_enabled',
          params: {'p_stake_id': widget.stakeId, 'p_enabled': target});
      if (mounted) setState(() => _sheetsEnabled = target);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Couldn\'t change this — only a stake leader can toggle Google Sheets.')));
      }
    } finally {
      if (mounted) setState(() => _sheetsBusy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final email = supabase.auth.currentUser?.email ?? '';
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          _header(context, 'Appearance'),
          ListenableBuilder(
            listenable: themeController,
            builder: (_, __) => ListTile(
              leading: const Icon(Icons.brightness_6_outlined),
              title: const Text('Theme'),
              subtitle: Text(themeController.label),
              trailing: const Icon(Icons.chevron_right),
              onTap: themeController.cycle,
            ),
          ),
          const Divider(height: 1),
          _header(context, 'Security'),
          if (PasskeyClient().available)
            ListTile(
              leading: const Icon(Icons.key),
              title: const Text('Add a passkey'),
              subtitle: const Text('Recommended — sign in with your face, fingerprint, or PIN '
                  'instead of a password'),
              isThreeLine: true,
              onTap: widget.onAddPasskey,
            ),
          if (_lockAvailable)
            SwitchListTile(
              secondary: const Icon(Icons.fingerprint),
              title: const Text('App lock'),
              subtitle: const Text('Require biometrics to open the app'),
              value: _lockOn,
              onChanged: _toggleLock,
            ),
          if (!PasskeyClient().available && !_lockAvailable)
            const ListTile(
              leading: Icon(Icons.lock_outline),
              title: Text('No extra security options on this device'),
              dense: true,
            ),
          const Divider(height: 1),
          _header(context, 'Support'),
          ListTile(
            leading: const Icon(Icons.support_agent),
            title: const Text('Contact support'),
            subtitle: const Text('Message the app owner'),
            onTap: widget.onContact,
          ),
          ListTile(
            leading: const Icon(Icons.feedback_outlined),
            title: const Text('Send feedback'),
            subtitle: const Text('Report a bug or suggest an improvement'),
            onTap: widget.onFeedback,
          ),
          if (widget.stakeId != null) ...[
            const Divider(height: 1),
            _header(context, 'Google Sheets'),
            SwitchListTile(
              secondary: const Icon(Icons.table_chart_outlined),
              title: const Text('Generate Google Sheets for this stake'),
              subtitle: const Text(
                  'Creates a stake master sheet plus a sheet per ward in the authorized leader’s '
                  'Google Drive, shared read-only with the relevant leaders & missionaries and '
                  'refreshed each sync. Off by default — the same data is always in this app.'),
              isThreeLine: true,
              value: _sheetsEnabled,
              onChanged: _sheetsBusy ? null : _toggleSheets,
            ),
          ],
          const Divider(height: 1),
          _header(context, 'About'),
          ListTile(
            leading: const Icon(Icons.info_outline),
            title: const Text('About & privacy'),
            onTap: () => showAboutDisclaimer(context),
          ),
          ListTile(
            leading: const Icon(Icons.rule),
            title: const Text('Rules & definitions'),
            subtitle: const Text('Eligibility, data access & convert-care'),
            onTap: () => showRulesDialog(context),
          ),
          const Divider(height: 1),
          _header(context, 'Account'),
          ListTile(
            leading: const Icon(Icons.account_circle_outlined),
            title: const Text('Signed in as'),
            subtitle: Text(email.isEmpty ? '—' : email),
          ),
          ListTile(
            leading: Icon(Icons.logout, color: Theme.of(context).colorScheme.error),
            title: Text('Sign out', style: TextStyle(color: Theme.of(context).colorScheme.error)),
            onTap: () {
              Navigator.of(context).pop();
              supabase.auth.signOut();
            },
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _header(BuildContext context, String text) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 18, 16, 6),
        child: Text(text.toUpperCase(),
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.bold,
                letterSpacing: 0.8)),
      );
}
