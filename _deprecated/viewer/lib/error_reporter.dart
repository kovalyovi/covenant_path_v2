import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'config.dart';

/// Best-effort client error telemetry → broker `/log` → Axiom (#53). No-op without a broker URL.
/// Sends only the error type, a truncated message, and a route hint — NEVER member data.
void reportError(Object error, StackTrace? stack, {String? where}) {
  if (brokerUrl.isEmpty) return;
  final msg = error.toString();
  http
      .post(Uri.parse('$brokerUrl/log'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'level': 'error',
            'event': 'client.error',
            'surface': kIsWeb ? 'web' : 'native',
            'message': msg.length > 400 ? msg.substring(0, 400) : msg,
            'context': {
              'type': error.runtimeType.toString(),
              if (where != null) 'where': where,
            },
          }))
      .then((_) {}, onError: (_) {}); // telemetry must never throw
}

/// Install global Flutter + platform error handlers that report to the broker.
void installErrorReporting() {
  final priorOnError = FlutterError.onError;
  FlutterError.onError = (details) {
    priorOnError?.call(details);
    reportError(details.exception, details.stack, where: 'flutter');
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    reportError(error, stack, where: 'platform');
    return true;
  };
}
