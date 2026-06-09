// Non-web stub for the WebAuthn biometric lock. Native uses local_auth instead (see
// biometric_gate.dart), so these are inert. Selected via conditional import when
// dart.library.js_interop is NOT available.

Future<bool> webBiometricAvailable() async => false;

/// Returns true (don't block) on non-web — the native local_auth path handles locking.
Future<bool> webBiometricUnlock() async => true;

Future<void> webBiometricClear() async {}
