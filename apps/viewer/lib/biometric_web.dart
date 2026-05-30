/// Web biometric app-lock via **WebAuthn platform authenticator** (Touch ID / Windows Hello /
/// Android fingerprint in the browser) — the web equivalent of native local_auth. local_auth is a
/// no-op on web, so this fills that gap. Like the native lock it is a *convenience gate* in front
/// of the already-stored Supabase session (model 1, see the login discussion), NOT a passwordless
/// login: it registers a platform credential on first use, then requires a user-verifying
/// assertion (the OS biometric prompt) to unlock. No password is ever involved.
///
/// Selected via conditional import when dart.library.js_interop IS available (web only).
library;

import 'dart:convert';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';
import 'dart:math';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

const _credKey = 'webauthn_cred_id'; // base64 of the registered credential rawId

bool _hasWebAuthn() {
  try {
    return globalContext.has('PublicKeyCredential') &&
        (web.window.navigator as JSObject).has('credentials');
  } catch (_) {
    return false;
  }
}

/// True only when the browser exposes a user-verifying *platform* authenticator (built-in
/// biometrics), not just any roaming security key.
Future<bool> webBiometricAvailable() async {
  try {
    if (!_hasWebAuthn()) return false;
    final pkc = globalContext.getProperty('PublicKeyCredential'.toJS) as JSObject;
    final promise = pkc.callMethod<JSPromise<JSBoolean>>(
        'isUserVerifyingPlatformAuthenticatorAvailable'.toJS);
    return (await promise.toDart).toDart;
  } catch (_) {
    return false;
  }
}

Uint8List _random(int n) {
  final r = Random.secure();
  return Uint8List.fromList(List<int>.generate(n, (_) => r.nextInt(256)));
}

/// Unlock: register a platform credential on first use, then assert on subsequent opens. Returns
/// true on success; false if the user cancels or it fails (caller keeps the app locked).
Future<bool> webBiometricUnlock() async {
  try {
    if (!_hasWebAuthn()) return true; // can't lock here → don't trap the user out
    final stored = web.window.localStorage.getItem(_credKey);
    return stored == null ? await _register() : await _assert(stored);
  } catch (_) {
    return false;
  }
}

Future<bool> _register() async {
  final rp = JSObject()..setProperty('name'.toJS, 'Covenant Path'.toJS);
  final user = JSObject()
    ..setProperty('id'.toJS, _random(16).toJS)
    ..setProperty('name'.toJS, 'covenant-path'.toJS)
    ..setProperty('displayName'.toJS, 'Covenant Path'.toJS);
  final es256 = JSObject()
    ..setProperty('type'.toJS, 'public-key'.toJS)
    ..setProperty('alg'.toJS, (-7).toJS);
  final rs256 = JSObject()
    ..setProperty('type'.toJS, 'public-key'.toJS)
    ..setProperty('alg'.toJS, (-257).toJS);
  final sel = JSObject()
    ..setProperty('authenticatorAttachment'.toJS, 'platform'.toJS)
    ..setProperty('userVerification'.toJS, 'required'.toJS)
    ..setProperty('residentKey'.toJS, 'discouraged'.toJS);
  final pk = JSObject()
    ..setProperty('challenge'.toJS, _random(32).toJS)
    ..setProperty('rp'.toJS, rp)
    ..setProperty('user'.toJS, user)
    ..setProperty('pubKeyCredParams'.toJS, <JSObject>[es256, rs256].toJS)
    ..setProperty('authenticatorSelection'.toJS, sel)
    ..setProperty('timeout'.toJS, (60000).toJS)
    ..setProperty('attestation'.toJS, 'none'.toJS);
  final options = JSObject()..setProperty('publicKey'.toJS, pk);

  final creds = web.window.navigator.credentials as JSObject;
  final cred = await creds.callMethod<JSPromise<JSAny?>>('create'.toJS, options).toDart;
  if (cred == null) return false;
  final rawId = (cred as JSObject).getProperty('rawId'.toJS) as JSArrayBuffer;
  web.window.localStorage.setItem(_credKey, base64Encode(rawId.toDart.asUint8List()));
  return true;
}

Future<bool> _assert(String credB64) async {
  final allow = JSObject()
    ..setProperty('type'.toJS, 'public-key'.toJS)
    ..setProperty('id'.toJS, Uint8List.fromList(base64Decode(credB64)).toJS)
    ..setProperty('transports'.toJS, <JSString>['internal'.toJS].toJS);
  final pk = JSObject()
    ..setProperty('challenge'.toJS, _random(32).toJS)
    ..setProperty('allowCredentials'.toJS, <JSObject>[allow].toJS)
    ..setProperty('userVerification'.toJS, 'required'.toJS)
    ..setProperty('timeout'.toJS, (60000).toJS);
  final options = JSObject()..setProperty('publicKey'.toJS, pk);

  final creds = web.window.navigator.credentials as JSObject;
  final cred = await creds.callMethod<JSPromise<JSAny?>>('get'.toJS, options).toDart;
  return cred != null;
}

Future<void> webBiometricClear() async {
  web.window.localStorage.removeItem(_credKey);
}
