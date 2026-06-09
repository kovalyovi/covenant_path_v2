// Non-web stub for passkey WebAuthn interop. Native passkey login is deferred (web-first), so
// these report unsupported. Selected via conditional import when dart.library.js_interop is absent.

bool passkeySupported() => false;

Future<String> passkeyCreate(String optionsJson) async =>
    throw UnsupportedError('Passkeys are available on the web app.');

Future<String> passkeyGet(String optionsJson) async =>
    throw UnsupportedError('Passkeys are available on the web app.');
