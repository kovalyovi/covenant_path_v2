import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';

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
  /// N2: whether the signed-in calling has covenant-path access (from the broker enroll step).
  /// null = unknown (not enrolled / errored) → don't block; false = no access → block at login.
  final bool? authorized;
  BrokerResult(
      {this.email, this.otp, this.loginId, this.factors = const [], this.name, this.authorized});

  bool get mfaRequired => loginId != null && otp == null;
}

/// Credential info returned from /auth/enrollment-status.
class CredentialInfo {
  final String state; // "none" | "active" | "revoked"
  final bool complete;
  final String? principalName;
  final bool isProvider;
  final String? enrolledAt;
  const CredentialInfo({required this.state, this.complete = false,
      this.principalName, this.isProvider = false, this.enrolledAt});
  factory CredentialInfo.fromJson(Map<String, dynamic> j) => CredentialInfo(
      state: (j['state'] as String?) ?? 'none',
      complete: j['complete'] as bool? ?? false,
      principalName: j['principal_name'] as String?,
      isProvider: j['is_provider'] as bool? ?? false,
      enrolledAt: j['enrolled_at'] as String?);
  bool get isActive => state == 'active';
  bool get isRevoked => state == 'revoked';
  bool get isNone => state == 'none';
}

/// Response from /auth/enrollment-status.
class EnrollmentStatus {
  final String? stakeName;
  final String? stakeId;
  final String? lastSyncedAt;
  final int memberCount;
  final bool hasData;
  final bool noRole; // true if the user has no user_roles row yet
  final CredentialInfo credential;
  const EnrollmentStatus({this.stakeName, this.stakeId, this.lastSyncedAt,
      this.memberCount = 0, this.hasData = false, this.noRole = false,
      required this.credential});
  factory EnrollmentStatus.fromJson(Map<String, dynamic> j) {
    final isNoRole = j['status'] == 'no_role';
    return EnrollmentStatus(
        stakeName: j['stake_name'] as String?,
        stakeId: j['stake_id'] as String?,
        lastSyncedAt: j['last_synced_at'] as String?,
        memberCount: (j['member_count'] as num?)?.toInt() ?? 0,
        hasData: j['has_data'] as bool? ?? false,
        noRole: isNoRole,
        credential: CredentialInfo.fromJson(
            (j['credential'] as Map?)?.cast<String, dynamic>() ?? const {}));
  }
}

class BrokerClient {
  bool get available => brokerUrl.isNotEmpty;

  /// Called when a network attempt fails and we're about to retry — lets the UI show a
  /// "waking up the sign-in service…" message. Set once by the login page.
  void Function(String message)? onStatus;

  /// N5: wake the free-tier broker early — fire a cheap /health ping when the login screen appears,
  /// so it spins up WHILE the user types their credentials, hiding the ~30-60s cold start that
  /// otherwise lands on the first login request. Fire-and-forget; errors ignored.
  void warmUp() {
    if (!available) return;
    http
        .get(Uri.parse('$brokerUrl/health'))
        .timeout(const Duration(seconds: 30))
        .then((_) {}, onError: (_) {});
  }

  // Free hosting (Render) sleeps when idle; the first request after a sleep hits a holding
  // page with no CORS header (browser reports "Failed to fetch"). Retry across ~60s so a
  // cold start resolves itself instead of erroring out. Delays sum to ~63s.
  static const _retryDelays = [Duration(seconds: 3), Duration(seconds: 6),
      Duration(seconds: 9), Duration(seconds: 12), Duration(seconds: 15), Duration(seconds: 18)];

  /// POST with cold-start retry; returns the decoded JSON (throws BrokerException on error).
  Future<Map<String, dynamic>> _postJson(String path, Map<String, dynamic> body) async {
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
    return data;
  }

  Future<BrokerResult> _post(String path, Map<String, dynamic> body) async {
    final data = await _postJson(path, body);
    if (data['status'] == 'mfa_required') {
      return BrokerResult(
        loginId: data['login_id'] as String,
        factors: ((data['factors'] as List?) ?? const [])
            .map((f) => BrokerFactor.fromJson(f as Map<String, dynamic>))
            .toList(),
      );
    }
    final session = (data['session'] as Map?)?.cast<String, dynamic>() ?? const {};
    final enroll = (data['enroll'] as Map?)?.cast<String, dynamic>();
    return BrokerResult(
      email: session['email'] as String?,
      otp: session['otp'] as String?,
      name: data['identity_name'] as String?,
      // N2: only a present, explicit `false` blocks; absent/errored enroll → null (don't block).
      authorized: enroll != null && enroll.containsKey('authorized')
          ? enroll['authorized'] as bool?
          : null,
    );
  }

  Future<BrokerResult> password(String username, String password, {bool enroll = false}) =>
      _post('/auth/password', {'username': username, 'password': password, 'enroll': enroll});

  Future<void> selectFactor(String loginId, String factorId) =>
      _post('/auth/mfa/select', {'login_id': loginId, 'factor_id': factorId});

  Future<BrokerResult> verifyMfa(String loginId, String code, {bool enroll = false}) =>
      _post('/auth/mfa/verify', {'login_id': loginId, 'code': code, 'enroll': enroll});

  /// Email-OTP relay (for networks that can't reach Supabase directly): the broker asks Supabase
  /// to email a one-time code. The user enters it; emailVerify returns session tokens to adopt.
  Future<void> emailStart(String email) async {
    await _postJson('/auth/email/start', {'email': email});
  }

  /// Verify the emailed code via the broker → {access_token, refresh_token} for setSession.
  Future<Map<String, dynamic>> emailVerify(String email, String code) =>
      _postJson('/auth/email/verify', {'email': email, 'code': code});

  Future<EnrollmentStatus> enrollmentStatus() async {
    if (!available) throw BrokerException('Broker not configured.');
    final token = Supabase.instance.client.auth.currentSession?.accessToken ?? '';
    if (token.isEmpty) throw BrokerException('Not signed in.');
    final resp = await http
        .get(Uri.parse('$brokerUrl/auth/enrollment-status'),
            headers: {'Authorization': 'Bearer $token'})
        .timeout(const Duration(seconds: 20));
    Map<String, dynamic> data;
    try {
      data = jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {
      throw BrokerException('Enrollment status error (${resp.statusCode}).');
    }
    if (resp.statusCode >= 400) {
      throw BrokerException((data['detail'] ?? 'Enrollment status failed.').toString());
    }
    return EnrollmentStatus.fromJson(data);
  }

  Future<void> revoke(String stakeId) async {
    await _authed('POST', '/auth/revoke', body: {'stake_id': stakeId});
  }

  /// Provider triggers a sync for their own stake. Returns {coverage_complete, last_synced_at}.
  Future<Map<String, dynamic>> syncNow() => _authed('POST', '/auth/sync-now');

  /// In-app daily-sync schedule (#schedule): read {eligible, hour_et, paused}; write hour + pause.
  Future<Map<String, dynamic>> getSchedule() => _authed('GET', '/auth/schedule');
  Future<Map<String, dynamic>> setSchedule(int hourEt, bool paused) =>
      _authed('POST', '/auth/schedule', body: {'hour_et': hourEt, 'paused': paused});

  /// M7 per-stake Google Drive: status, start the OAuth (returns {url} to open), disconnect.
  Future<Map<String, dynamic>> googleDriveStatus() => _authed('GET', '/auth/google/status');
  Future<Map<String, dynamic>> googleDriveStart() => _authed('POST', '/auth/google/start');
  Future<Map<String, dynamic>> googleDriveDisconnect() => _authed('POST', '/auth/google/disconnect');

  /// Support form (#74): email the owner a message from the signed-in user.
  Future<void> contact(String subject, String message) async {
    await _authed('POST', '/contact', body: {'subject': subject, 'message': message});
  }

  /// Ad-hoc leader report (#73): structured convert-integration status for the caller's scope.
  Future<Map<String, dynamic>> report() async {
    return await _authed('GET', '/report');
  }

  /// Email the caller's scope report (default: to themselves; or a chosen recipient).
  Future<Map<String, dynamic>> emailReport({String? toEmail}) async {
    return await _authed('POST', '/report/email',
        body: {if (toEmail != null && toEmail.isNotEmpty) 'to_email': toEmail});
  }

  /// Shared authed request carrying the signed-in user's Supabase token. Returns the decoded
  /// JSON body (empty map if none). Throws BrokerException on transport/HTTP error.
  Future<Map<String, dynamic>> _authed(String method, String path,
      {Map<String, dynamic>? body}) async {
    if (!available) throw BrokerException('Broker not configured.');
    final token = Supabase.instance.client.auth.currentSession?.accessToken ?? '';
    if (token.isEmpty) throw BrokerException('Not signed in.');
    final uri = Uri.parse('$brokerUrl$path');
    final headers = {'Authorization': 'Bearer $token', 'Content-Type': 'application/json'};
    final resp = await (method == 'GET'
            ? http.get(uri, headers: headers)
            : http.post(uri, headers: headers, body: jsonEncode(body ?? const {})))
        .timeout(const Duration(seconds: 30));
    Map<String, dynamic> data = const {};
    if (resp.body.isNotEmpty) {
      try {
        data = jsonDecode(resp.body) as Map<String, dynamic>;
      } catch (_) {
        if (resp.statusCode >= 400) throw BrokerException('Request failed (${resp.statusCode}).');
      }
    }
    if (resp.statusCode >= 400) {
      throw BrokerException((data['detail'] ?? 'Request failed (${resp.statusCode}).').toString());
    }
    return data;
  }
}
