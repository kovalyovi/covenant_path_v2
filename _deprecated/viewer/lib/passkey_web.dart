// Web passkey interop — thin bridge to window.cpPasskey (web/passkey.js), which does the
// base64url↔ArrayBuffer conversion + the WebAuthn ceremony. Dart passes the broker's options JSON
// in and gets a server-ready credential JSON back. Selected via conditional import on web.
@JS()
library;

import 'dart:js_interop';

@JS('cpPasskey.supported')
external bool _supported();

@JS('cpPasskey.create')
external JSPromise<JSString> _create(JSString optionsJson);

@JS('cpPasskey.get')
external JSPromise<JSString> _get(JSString optionsJson);

bool passkeySupported() {
  try {
    return _supported();
  } catch (_) {
    return false; // passkey.js not loaded / WebAuthn unavailable
  }
}

Future<String> passkeyCreate(String optionsJson) async =>
    (await _create(optionsJson.toJS).toDart).toDart;

Future<String> passkeyGet(String optionsJson) async =>
    (await _get(optionsJson.toJS).toDart).toDart;
