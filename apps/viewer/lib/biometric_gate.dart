import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Device-biometric app lock — Face ID / Touch ID / fingerprint / Windows Hello via local_auth.
/// Native only; on web it's a no-op (passkeys/WebAuthn would be the web path). Gates a restored
/// session so a returning leader unlocks with biometrics instead of re-authenticating.
class BiometricLock {
  static const _prefKey = 'biometric_lock_enabled';
  static final _auth = LocalAuthentication();

  /// Whether this device can do biometrics at all (false on web / unsupported hardware).
  static Future<bool> available() async {
    if (kIsWeb) return false;
    try {
      return (await _auth.isDeviceSupported()) && (await _auth.canCheckBiometrics);
    } catch (_) {
      return false;
    }
  }

  static Future<bool> enabled() async {
    if (kIsWeb) return false;
    final p = await SharedPreferences.getInstance();
    return p.getBool(_prefKey) ?? true; // on by default wherever supported
  }

  static Future<void> setEnabled(bool v) async {
    final p = await SharedPreferences.getInstance();
    await p.setBool(_prefKey, v);
  }

  static Future<bool> authenticate() async {
    try {
      return await _auth.authenticate(
        localizedReason: 'Unlock Covenant Path',
        persistAcrossBackgrounding: true,
      );
    } catch (_) {
      return false; // hardware error / cancelled — stay locked, let the user retry
    }
  }
}

/// Shows [child] once unlocked. On web, or when the lock is off/unavailable, shows it immediately
/// (fail-open on *availability* so a device without biometrics is never locked out).
class BiometricGate extends StatefulWidget {
  const BiometricGate({super.key, required this.child});
  final Widget child;
  @override
  State<BiometricGate> createState() => _BiometricGateState();
}

class _BiometricGateState extends State<BiometricGate> {
  bool _unlocked = false;
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _maybeLock();
  }

  Future<void> _maybeLock() async {
    final shouldLock = await BiometricLock.enabled() && await BiometricLock.available();
    if (!mounted) return;
    if (!shouldLock) {
      setState(() {
        _unlocked = true;
        _checking = false;
      });
      return;
    }
    setState(() => _checking = false);
    _unlock();
  }

  Future<void> _unlock() async {
    final ok = await BiometricLock.authenticate();
    if (mounted && ok) setState(() => _unlocked = true);
  }

  @override
  Widget build(BuildContext context) {
    if (_unlocked) return widget.child;
    return Scaffold(
      body: Center(
        child: _checking
            ? const CircularProgressIndicator()
            : Column(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.lock_outline, size: 48, color: Theme.of(context).colorScheme.primary),
                const SizedBox(height: 16),
                const Text('Covenant Path is locked'),
                const SizedBox(height: 16),
                FilledButton.icon(
                    onPressed: _unlock,
                    icon: const Icon(Icons.fingerprint),
                    label: const Text('Unlock')),
              ]),
      ),
    );
  }
}
