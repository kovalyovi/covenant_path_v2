import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'biometric_gate.dart';
import 'config.dart';
import 'dashboard_page.dart';
import 'error_reporter.dart';
import 'login_page.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  installErrorReporting(); // uncaught errors → broker /log → Axiom (best-effort, no-op offline)
  if (supabaseUrl.isEmpty || supabaseAnonKey.isEmpty) {
    runApp(const _ConfigError());
    return;
  }
  await Supabase.initialize(url: supabaseUrl, anonKey: supabaseAnonKey);
  runApp(const ViewerApp());
}

/// Shorthand used across the app.
SupabaseClient get supabase => Supabase.instance.client;

/// App-wide light/dark preference (persisted). The dashboard menu toggles it.
final themeController = ThemeController();

class ViewerApp extends StatelessWidget {
  const ViewerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: themeController,
      builder: (context, mode, _) => MaterialApp(
        title: 'Covenant Path',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: mode,
        // Make all text selectable app-wide (text fields manage their own selection and are
        // excluded automatically); taps/buttons still work inside a SelectionArea.
        builder: (context, child) => SelectionArea(child: child ?? const SizedBox.shrink()),
        home: const AuthGate(),
      ),
    );
  }
}

/// Shows the login page until there's a session, then the dashboard. RLS scopes
/// everything the dashboard reads to the signed-in user's calling.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<AuthState>(
      stream: supabase.auth.onAuthStateChange,
      builder: (context, _) {
        final session = supabase.auth.currentSession;
        return session == null
            ? const LoginPage()
            : const BiometricGate(child: DashboardPage());
      },
    );
  }
}

class _ConfigError extends StatelessWidget {
  const _ConfigError();
  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'Missing SUPABASE_URL / SUPABASE_ANON_KEY.\n\n'
              'Run with:\n'
              'flutter run --dart-define=SUPABASE_URL=... '
              '--dart-define=SUPABASE_ANON_KEY=...',
              textAlign: TextAlign.center,
            ),
          ),
        ),
      ),
    );
  }
}
