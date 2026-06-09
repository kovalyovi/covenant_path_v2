import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

import 'broker_client.dart';
import 'config.dart';
import 'passkey_web_stub.dart' if (dart.library.js_interop) 'passkey_web.dart' as pw;

/// Passwordless passkey (WebAuthn) login + registration, against the broker's /webauthn/* routes.
/// Login is unauthenticated (it's how you sign in); registration requires the current Supabase
/// session (binds a passkey to the signed-in email). Web-only for now (native uses the stub).
class PasskeyClient {
  bool get available => brokerUrl.isNotEmpty && pw.passkeySupported();

  Future<Map<String, dynamic>> _post(String path, Map<String, dynamic> body,
      {bool authed = false}) async {
    final headers = {'Content-Type': 'application/json'};
    if (authed) {
      final token = Supabase.instance.client.auth.currentSession?.accessToken ?? '';
      if (token.isEmpty) throw BrokerException('Not signed in.');
      headers['Authorization'] = 'Bearer $token';
    }
    final resp = await http
        .post(Uri.parse('$brokerUrl$path'), headers: headers, body: jsonEncode(body))
        .timeout(const Duration(seconds: 30));
    Map<String, dynamic> data = const {};
    if (resp.body.isNotEmpty) {
      try {
        data = jsonDecode(resp.body) as Map<String, dynamic>;
      } catch (_) {
        if (resp.statusCode >= 400) throw BrokerException('Passkey error (${resp.statusCode}).');
      }
    }
    if (resp.statusCode >= 400) {
      throw BrokerException((data['detail'] ?? 'Passkey request failed.').toString());
    }
    return data;
  }

  /// Passwordless login: returns a verifiable Supabase session ({email, otp}) to verifyOtp.
  Future<BrokerResult> login() async {
    final begin = await _post('/webauthn/login/begin', const {});
    final credJson = await pw.passkeyGet(jsonEncode(begin['options']));
    final done = await _post('/webauthn/login/complete', {
      'handle': begin['handle'],
      'credential': jsonDecode(credJson),
    });
    final session = (done['session'] as Map?)?.cast<String, dynamic>() ?? const {};
    return BrokerResult(email: session['email'] as String?, otp: session['otp'] as String?);
  }

  /// Register a passkey for the signed-in user (requires a current session).
  Future<void> register() async {
    final begin = await _post('/webauthn/register/begin', const {}, authed: true);
    final credJson = await pw.passkeyCreate(jsonEncode(begin['options']));
    await _post('/webauthn/register/complete', {
      'handle': begin['handle'],
      'credential': jsonDecode(credJson),
    }, authed: true);
  }
}
