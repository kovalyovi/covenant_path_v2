import Foundation
import Observation

/// Small UserDefaults-backed preference store (port of the various SharedPreferences keys the
/// Flutter app uses: theme, biometric lock, remembered stake, the one-time passkey upsell flag).
public enum AppPrefs {
    private static let store = UserDefaults.standard

    // keys (match the Flutter pref keys where shared semantics matter)
    static let themeMode = "theme_mode"
    static let biometricLock = "biometric_lock_enabled"
    static let currentStake = "current_stake_id"
    static let passkeySuggested = "passkey_suggested"

    public static func string(_ key: String) -> String? { store.string(forKey: key) }
    public static func setString(_ key: String, _ value: String) { store.set(value, forKey: key) }
    public static func bool(_ key: String, default def: Bool = false) -> Bool {
        store.object(forKey: key) == nil ? def : store.bool(forKey: key)
    }
    public static func setBool(_ key: String, _ value: Bool) { store.set(value, forKey: key) }
}

/// The persisted appearance mode (system/light/dark), with a cycle for the single menu toggle.
/// Mirrors `theme/app_theme.dart` `ThemeController`. The view maps this to SwiftUI's `ColorScheme?`.
public enum AppThemeMode: String, CaseIterable, Sendable {
    case system, light, dark
    public var label: String {
        switch self {
        case .system: return "System"
        case .light: return "Light"
        case .dark: return "Dark"
        }
    }
}

@MainActor
@Observable
public final class ThemeController {
    public private(set) var mode: AppThemeMode

    public init() {
        let raw = AppPrefs.string(AppPrefs.themeMode)
        mode = AppThemeMode(rawValue: raw ?? "") ?? .system
    }

    public func set(_ m: AppThemeMode) {
        mode = m
        AppPrefs.setString(AppPrefs.themeMode, m.rawValue)
    }

    /// Cycle system → light → dark → system (port of `ThemeController.cycle`).
    public func cycle() {
        switch mode {
        case .system: set(.light)
        case .light: set(.dark)
        case .dark: set(.system)
        }
    }
}
