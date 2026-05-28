import 'dart:convert';

import 'package:http/http.dart' as http;

import 'config.dart';

/// Calls the broker's admin/ops endpoints. Every request carries the signed-in user's
/// Supabase access token as a Bearer; the broker verifies it belongs to an app_admin
/// (RLS-independent — the broker checks app_admins with the service-role key).
class AdminException implements Exception {
  final String message;
  AdminException(this.message);
  @override
  String toString() => message;
}

class AdminClient {
  AdminClient(this.accessToken);
  final String accessToken;

  bool get available => brokerUrl.isNotEmpty;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $accessToken',
      };

  Future<Map<String, dynamic>> _get(String path) async {
    _ensure();
    final r = await http
        .get(Uri.parse('$brokerUrl$path'), headers: _headers)
        .timeout(const Duration(seconds: 40));
    return _decode(r);
  }

  Future<Map<String, dynamic>> _post(String path, [Map<String, dynamic>? body]) async {
    _ensure();
    final r = await http
        .post(Uri.parse('$brokerUrl$path'),
            headers: _headers, body: jsonEncode(body ?? const {}))
        .timeout(const Duration(seconds: 40));
    return _decode(r);
  }

  void _ensure() {
    if (!available) throw AdminException('Ops console needs BROKER_URL configured.');
  }

  Map<String, dynamic> _decode(http.Response r) {
    Map<String, dynamic> data;
    try {
      data = jsonDecode(r.body) as Map<String, dynamic>;
    } catch (_) {
      throw AdminException('Broker error (${r.statusCode}).');
    }
    if (r.statusCode == 403) throw AdminException('Not authorized (admins only).');
    if (r.statusCode >= 400) {
      throw AdminException((data['detail'] ?? 'Request failed (${r.statusCode}).').toString());
    }
    return data;
  }

  Future<Map<String, dynamic>> summary() => _get('/admin/summary');
  Future<Map<String, dynamic>> actions() => _get('/admin/actions');
  Future<Map<String, dynamic>> diagnostics() => _get('/admin/diagnostics');
  Future<Map<String, dynamic>> run(String workflow, {Map<String, dynamic>? inputs}) =>
      _post('/admin/actions/run', {'workflow': workflow, if (inputs != null) 'inputs': inputs});
  Future<Map<String, dynamic>> rerun(int runId) => _post('/admin/actions/$runId/rerun');
  Future<Map<String, dynamic>> invite(String email) => _post('/admin/invite', {'email': email});
}
