import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';

/// Thin client for the Church-login auth broker (backend/auth_broker). The browser can't
/// call the Church's Okta directly (CORS); the broker does it server-side and hands back a
/// Supabase session OTP the app verifies. Empty [brokerUrl] => Church login is unavailable.
class BrokerException implements Exception {
  final String message;
  BrokerException(this.message);
  @override
  String toString() => message;
}

/// One MFA factor offered by Okta (e.g. "Text message to •••1234").
class BrokerFactor {
  final String id;
  final String label;
  final String method;
  BrokerFactor(this.id, this.label, this.method);
  factory BrokerFactor.fromJson(Map<String, dynamic> j) =>
      BrokerFactor(j['id'] as String, (j['label'] ?? j['method'] ?? 'Code') as String,
          (j['method'] ?? '') as String);
}

/// Result of a step: either a verifiable Supabase session, or an MFA challenge to continue.
class BrokerResult {
  final String? email; // present when a session was minted
  final String? otp; // Supabase OTP to verifyOtp(email, otp)
  final String? loginId; // present when MFA is required
  final List<BrokerFactor> factors;
  final String? name;
  BrokerResult({this.email, this.otp, this.loginId, this.factors = const [], this.name});

  bool get mfaRequired => loginId != null && otp == null;
}

class BrokerClient {
  bool get available => brokerUrl.isNotEmpty;

  /// Called when a network attempt fails and we're about to retry — lets the UI show a
  /// "waking up the sign-in service…" message. Set once by the login page.
  void Function(String message)? onStatus;

  // Free hosting (Render) sleeps when idle; the first request after a sleep hits a holding
  // page with no CORS header (browser reports "Failed to fetch"). Retry across ~60s so a
  // cold start resolves itself instead of erroring out. Delays sum to ~63s.
  static const _retryDelays = [Duration(seconds: 3), Duration(seconds: 6),
      Duration(seconds: 9), Duration(seconds: 12), Duration(seconds: 15), Duration(seconds: 18)];

  Future<BrokerResult> _post(String path, Map<String, dynamic> body) async {
    if (!available) throw BrokerException('Church login is not configured (BROKER_URL).');
    http.Response? resp;
    Object? lastErr;
    for (var attempt = 0; attempt <= _retryDelays.length; attempt++) {
      try {
        resp = await http
            .post(Uri.parse('$brokerUrl$path'),
                headers: const {'Content-Type': 'application/json'}, body: jsonEncode(body))
            .timeout(const Duration(seconds: 30));
        break; // got an HTTP response (success or error) — stop retrying
      } catch (e) {
        // Network failure (cold start / transient). Wait and retry within budget.
        lastErr = e;
        if (attempt < _retryDelays.length) {
          onStatus?.call('Waking up the sign-in service… this can take up to a minute on first use.');
          await Future.delayed(_retryDelays[attempt]);
        }
      }
    }
    if (resp == null) {
      throw BrokerException(
          'Could not reach the sign-in service after several tries. It may be starting up — '
          'please try again in a minute. ($lastErr)');
    }
    Map<String, dynamic> data;
    try {
      data = jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {
      throw BrokerException('Sign-in service error (${resp.statusCode}).');
    }
    if (resp.statusCode >= 400) {
      throw BrokerException((data['detail'] ?? 'Sign-in failed (${resp.statusCode}).').toString());
    }
    if (data['status'] == 'mfa_required') {
      return BrokerResult(
        loginId: data['login_id'] as String,
        factors: ((data['factors'] as List?) ?? const [])
            .map((f) => BrokerFactor.fromJson(f as Map<String, dynamic>))
            .toList(),
      );
    }
    final session = (data['session'] as Map?)?.cast<String, dynamic>() ?? const {};
    return BrokerResult(
      email: session['email'] as String?,
      otp: session['otp'] as String?,
      name: data['identity_name'] as String?,
    );
  }

  Future<BrokerResult> password(String username, String password, {bool enroll = false}) =>
      _post('/auth/password', {'username': username, 'password': password, 'enroll': enroll});

  Future<void> selectFactor(String loginId, String factorId) =>
      _post('/auth/mfa/select', {'login_id': loginId, 'factor_id': factorId});

  Future<BrokerResult> verifyMfa(String loginId, String code, {bool enroll = false}) =>
      _post('/auth/mfa/verify', {'login_id': loginId, 'code': code, 'enroll': enroll});
}
