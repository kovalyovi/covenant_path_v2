#if canImport(LocalAuthentication)
import Foundation
import LocalAuthentication

/// Device-biometric app lock — Face ID / Touch ID. Native port of `biometric_gate.dart`'s
/// `BiometricLock` (iOS uses LocalAuthentication). It guards a restored session so a returning leader
/// unlocks with biometrics instead of re-authenticating — it never stores or replays a password.
public enum BiometricService {

    /// Whether this device can do biometrics (hardware present + enrolled).
    public static func available() -> Bool {
        let ctx = LAContext()
        var error: NSError?
        return ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
    }

    /// **Opt-in, OFF by default** (user directive 2026-06-13: don't require Face ID to open the app).
    /// The app launches straight to the dashboard; a leader who wants the extra lock turns it on in
    /// Settings → Security. Persisted. (The at-rest Supabase session is already protected in the
    /// Keychain — this lock is a defense-in-depth UI gate, not the security boundary.)
    public static func enabled() -> Bool {
        AppPrefs.bool(AppPrefs.biometricLock, default: false)
    }

    /// Enable/disable the lock (returns whether the new state took effect — always true on native;
    /// the web-only registration dance from Flutter doesn't apply here).
    @discardableResult
    public static func setEnabled(_ v: Bool) -> Bool {
        AppPrefs.setBool(AppPrefs.biometricLock, v)
        return true
    }

    /// Prompt for biometrics; resolves true on success, false on cancel/error (stay locked, retry).
    public static func authenticate(reason: String = "Unlock Covenant Path") async -> Bool {
        let ctx = LAContext()
        // Allow passcode fallback so a device with biometrics temporarily unavailable isn't bricked.
        return await withCheckedContinuation { cont in
            ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) { ok, _ in
                cont.resume(returning: ok)
            }
        }
    }
}
#endif
