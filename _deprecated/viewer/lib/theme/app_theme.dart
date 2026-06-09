import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One theme, two brightnesses. Centralizes the Material-3 ThemeData (was a one-liner in main.dart)
/// so light + dark share one seed and the app gets dark mode "for free." Part of #67.
abstract final class AppTheme {
  static const Color _seed = Colors.indigo;

  static ThemeData _base(Brightness brightness) {
    final scheme = ColorScheme.fromSeed(seedColor: _seed, brightness: brightness);
    return ThemeData(
      colorScheme: scheme,
      useMaterial3: true,
      cardTheme: CardThemeData(
        margin: const EdgeInsets.symmetric(vertical: 6),
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: scheme.outlineVariant),
        ),
      ),
    );
  }

  static ThemeData get light => _base(Brightness.light);
  static ThemeData get dark => _base(Brightness.dark);
}

/// Persisted light/dark/system preference. A ValueNotifier so MaterialApp rebuilds on toggle.
class ThemeController extends ValueNotifier<ThemeMode> {
  ThemeController() : super(ThemeMode.system) {
    _load();
  }
  static const _prefKey = 'theme_mode';

  Future<void> _load() async {
    final p = await SharedPreferences.getInstance();
    final v = p.getString(_prefKey);
    value = switch (v) {
      'light' => ThemeMode.light,
      'dark' => ThemeMode.dark,
      _ => ThemeMode.system,
    };
  }

  Future<void> set(ThemeMode mode) async {
    value = mode;
    final p = await SharedPreferences.getInstance();
    await p.setString(_prefKey, mode.name);
  }

  /// Cycle system → light → dark → system, for a single menu toggle.
  Future<void> cycle() async {
    await set(switch (value) {
      ThemeMode.system => ThemeMode.light,
      ThemeMode.light => ThemeMode.dark,
      ThemeMode.dark => ThemeMode.system,
    });
  }

  String get label => switch (value) {
        ThemeMode.system => 'System',
        ThemeMode.light => 'Light',
        ThemeMode.dark => 'Dark',
      };
}
