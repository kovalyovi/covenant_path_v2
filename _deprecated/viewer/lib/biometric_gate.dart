import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'biometric_web_stub.dart' if (dart.library.js_interop) 'biometric_web.dart' as webbio;

/// Device-biometric app lock — Face ID / Touch ID / fingerprint / Windows Hello. Native uses
/// local_auth; **web uses WebAuthn platform authenticators** (biometric_web.dart) so the browser
/// also gets a biometric gate. Either way it guards a restored session so a returning leader
/// unlocks with biometrics instead of re-authenticating — it never stores or replays a password.
class BiometricLock {
  static const _prefKey = 'biometric_lock_enabled';
  static final _auth = LocalAuthentication();

  /// Whether this device/browser can do biometrics (native hardware, or a web platform authenticator).
  static Future<bool> available() async {
    if (kIsWeb) return webbio.webBiometricAvailable();
    try {
      return (await _auth.isDeviceSupported()) && (await _auth.canCheckBiometrics);
    } catch (_) {
      return false;
    }
  }

  /// On by default on native; opt-in on web (registering a platform credential prompts the user,
  /// so we only do it when they explicitly turn the lock on).
  static Future<bool> enabled() async {
    final p = await SharedPreferences.getInstance();
    return p.getBool(_prefKey) ?? !kIsWeb;
  }

  /// Enable/disable the lock. On web, enabling registers the platform credential now (returns false
  /// if the user cancels); disabling drops it. Returns whether the new state took effect.
  static Future<bool> setEnabled(bool v) async {
    if (kIsWeb && v && !await webbio.webBiometricUnlock()) return false; // registration cancelled
    final p = await SharedPreferences.getInstance();
    await p.setBool(_prefKey, v);
    if (kIsWeb && !v) await webbio.webBiometricClear();
    return true;
  }

  static Future<bool> authenticate() async {
    if (kIsWeb) return webbio.webBiometricUnlock();
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
