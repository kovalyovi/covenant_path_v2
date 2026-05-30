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
  });
  final VoidCallback onFeedback;
  final VoidCallback onContact;
  final VoidCallback onAddPasskey;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  bool _lockAvailable = false;
  bool _lockOn = false;

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
              subtitle: const Text('Sign in without a password next time'),
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
          const Divider(height: 1),
          _header(context, 'About'),
          ListTile(
            leading: const Icon(Icons.info_outline),
            title: const Text('About & privacy'),
            onTap: () => showAboutDisclaimer(context),
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
