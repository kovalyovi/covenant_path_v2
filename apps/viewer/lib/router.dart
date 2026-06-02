import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import 'biometric_gate.dart';
import 'dashboard_page.dart';
import 'login_page.dart';
import 'main.dart';

/// App routing (go_router) — the routing layer + the URL contract the React web app (R1) mirrors
/// with React Router. `SentryNavigatorObserver` records a route transaction + breadcrumb on every
/// navigation, so per-screen performance is tracked. Auth is enforced by `redirect` (re-run on
/// every Supabase auth change via `refreshListenable`), replacing the old AuthGate StreamBuilder.
///
/// Top-level routes: `/login` and `/` (the dashboard shell — its 5 tabs and the person / settings /
/// invite / admin screens are navigated within it on the root navigator). The React rebuild mirrors
/// the full route map (incl. per-tab + /person/:id) — see `.llm/CROSS_SURFACE_UI.md`.
final GoRouter appRouter = GoRouter(
  initialLocation: '/',
  refreshListenable: GoRouterRefreshStream(supabase.auth.onAuthStateChange),
  observers: [SentryNavigatorObserver()],
  redirect: (context, state) {
    final signedIn = supabase.auth.currentSession != null;
    final atLogin = state.matchedLocation == '/login';
    if (!signedIn) return atLogin ? null : '/login';
    if (atLogin) return '/';
    return null;
  },
  routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginPage()),
    GoRoute(path: '/', builder: (_, __) => const BiometricGate(child: DashboardPage())),
  ],
);

/// Bridges the Supabase auth Stream to a Listenable so go_router re-evaluates `redirect` whenever
/// the session changes (sign-in / sign-out / token refresh).
class GoRouterRefreshStream extends ChangeNotifier {
  GoRouterRefreshStream(Stream<dynamic> stream) {
    notifyListeners();
    _sub = stream.asBroadcastStream().listen((_) => notifyListeners());
  }
  late final StreamSubscription<dynamic> _sub;

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }
}
