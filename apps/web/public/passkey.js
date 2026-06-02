// WebAuthn passkey helper for the web app. The browser WebAuthn API needs ArrayBuffers,
// but our broker speaks base64url JSON (py_webauthn). This converts between the two so the
// app just passes the broker's options JSON in and gets a server-ready credential JSON back.
// Exposed as window.cpPasskey.{supported, create, get}. Self-contained — no external library.
// (Mirrors apps/viewer/web/passkey.js so the React + Flutter passkey flows are identical.)
(function () {
  function b64urlToBuf(s) {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const b64 = (s + pad).replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out.buffer;
  }
  function bufToB64url(buf) {
    const bytes = new Uint8Array(buf);
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function supported() {
    return !!(window.PublicKeyCredential && navigator.credentials && navigator.credentials.create);
  }
  async function create(optionsJson) {
    const o = JSON.parse(optionsJson);
    o.challenge = b64urlToBuf(o.challenge);
    o.user.id = b64urlToBuf(o.user.id);
    if (o.excludeCredentials) o.excludeCredentials.forEach((c) => (c.id = b64urlToBuf(c.id)));
    const cred = await navigator.credentials.create({ publicKey: o });
    return JSON.stringify({
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        attestationObject: bufToB64url(cred.response.attestationObject),
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    });
  }
  async function get(optionsJson) {
    const o = JSON.parse(optionsJson);
    o.challenge = b64urlToBuf(o.challenge);
    if (o.allowCredentials) o.allowCredentials.forEach((c) => (c.id = b64urlToBuf(c.id)));
    const cred = await navigator.credentials.get({ publicKey: o });
    return JSON.stringify({
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(cred.response.clientDataJSON),
        authenticatorData: bufToB64url(cred.response.authenticatorData),
        signature: bufToB64url(cred.response.signature),
        userHandle: cred.response.userHandle ? bufToB64url(cred.response.userHandle) : null,
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    });
  }
  window.cpPasskey = { supported: supported, create: create, get: get };
})();
