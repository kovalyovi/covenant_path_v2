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

  Future<BrokerResult> _post(String path, Map<String, dynamic> body) async {
    if (!available) throw BrokerException('Church login is not configured (BROKER_URL).');
    final http.Response resp;
    try {
      resp = await http
          .post(Uri.parse('$brokerUrl$path'),
              headers: const {'Content-Type': 'application/json'}, body: jsonEncode(body))
          .timeout(const Duration(seconds: 90));
    } catch (e) {
      throw BrokerException('Could not reach the sign-in service. $e');
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

  Future<BrokerResult> password(String username, String password) =>
      _post('/auth/password', {'username': username, 'password': password});

  Future<void> selectFactor(String loginId, String factorId) =>
      _post('/auth/mfa/select', {'login_id': loginId, 'factor_id': factorId});

  Future<BrokerResult> verifyMfa(String loginId, String code) =>
      _post('/auth/mfa/verify', {'login_id': loginId, 'code': code});
}
