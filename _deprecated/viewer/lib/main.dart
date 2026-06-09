import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'config.dart';
import 'error_reporter.dart';
import 'router.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (supabaseUrl.isEmpty || supabaseAnonKey.isEmpty) {
    installErrorReporting();
    runApp(const _ConfigError());
    return;
  }
  await Supabase.initialize(url: supabaseUrl, anonKey: supabaseAnonKey);

  // Sentry wraps runApp and auto-captures uncaught errors; installErrorReporting() then chains on
  // top so the same errors also reach our broker /log → Axiom. PII is never sent (sendDefaultPii
  // off + our reporter strips member data). No-op path when no DSN is configured.
  Future<void> startApp() async {
    installErrorReporting();
    runApp(const ViewerApp());
  }

  if (sentryDsn.isEmpty) {
    await startApp();
  } else {
    await SentryFlutter.init(
      (o) {
        o.dsn = sentryDsn;
        o.tracesSampleRate = 0.2; // performance traces (20%)
        o.sendDefaultPii = false; // never attach user PII
        o.environment = kReleaseMode ? 'production' : 'debug';
      },
      appRunner: startApp,
    );
  }
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
      builder: (context, mode, _) => MaterialApp.router(
        title: 'Covenant Path',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: mode,
        // Make all text selectable app-wide (text fields manage their own selection and are
        // excluded automatically); taps/buttons still work inside a SelectionArea.
        builder: (context, child) => SelectionArea(child: child ?? const SizedBox.shrink()),
        routerConfig: appRouter,
      ),
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
