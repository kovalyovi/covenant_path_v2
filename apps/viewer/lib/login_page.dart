import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import 'broker_client.dart';
import 'config.dart';
import 'main.dart';
import 'passkey_client.dart';

/// Two ways in, one resulting session:
///  • **Church account** (username + password, MFA-aware) — for leaders. The browser can't
///    talk to the Church's Okta directly (CORS), so it goes through the auth broker
///    (backend/auth_broker), which authenticates server-side and returns a Supabase OTP we
///    verify here. Only shown when [brokerUrl] is configured.
///  • **Email code** — for power-user invitees who have no Church account. Supabase sends a
///    6-digit code to the email LCR has on file; the verified email is what RLS scopes on.
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

enum _Mode { church, email }

class _LoginPageState extends State<LoginPage> {
  final _broker = BrokerClient();
  final _passkey = PasskeyClient();
  late _Mode _mode = _broker.available ? _Mode.church : _Mode.email;
  String? _status; // transient progress note (e.g. "waking up the sign-in service")

  @override
  void initState() {
    super.initState();
    _broker.onStatus = (m) {
      if (mounted) setState(() => _status = m);
    };
    _broker.warmUp(); // N5: start waking the broker now, while the user types — hides cold start
  }

  // Church-account fields
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _mfaCode = TextEditingController();
  String? _loginId;
  List<BrokerFactor> _factors = const [];
  BrokerFactor? _factorSent;

  // Email-code fields
  final _email = TextEditingController();
  final _emailCode = TextEditingController();
  bool _emailCodeSent = false;
  bool _useRelay = false; // route the email-code flow through the broker (for blocked networks)

  bool _busy = false;
  // Signing in NO LONGER captures a leader's session automatically. The credential is stored only
  // when the leader explicitly authorizes daily sync via this checkbox (default off) — then the
  // backend stores it (encrypted), kicks off the first sync, and emails a confirmation. They can
  // revoke anytime in Settings → Sync settings.
  bool _authorizeSync = false;
  String? _error;

  void _reset() {
    _loginId = null;
    _factors = const [];
    _factorSent = null;
    _mfaCode.clear();
    _emailCodeSent = false;
    _emailCode.clear();
    _error = null;
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
      _status = null;
    });
    try {
      await action();
    } on BrokerException catch (e) {
      setState(() => _error = e.message);
    } on AuthException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Turn a broker-minted OTP into a real Supabase session (AuthGate then routes to the app).
  Future<void> _consume(BrokerResult r) async {
    if (r.email == null || r.otp == null) {
      throw BrokerException('Sign-in service did not return a session.');
    }
    await supabase.auth
        .verifyOTP(email: r.email, token: r.otp!, type: OtpType.email);
    // Tell the browser the credential flow is done so it offers to save the password.
    TextInput.finishAutofillContext();
  }

  /// N2: the Church login succeeded but this calling has NO covenant-path access (the broker says
  /// authorized:false). Don't create a session — show why and stay on the login screen, so a
  /// regular member is never signed into an app they can't use. Only an explicit `false` blocks;
  /// null (not enrolled / broker couldn't determine) is allowed through.
  bool _noAccess(BrokerResult r) {
    if (r.authorized == false) {
      setState(() => _error =
          "This account doesn't have access to Covenant Path. Access is granted by your calling — "
          "if you should have access, ask your stake leadership.");
      return true;
    }
    return false;
  }

  Future<void> _churchSignIn() => _run(() async {
        final r = await _broker.password(_username.text.trim(), _password.text, enroll: _authorizeSync);
        if (r.mfaRequired) {
          setState(() {
            _loginId = r.loginId;
            _factors = r.factors;
          });
          // Auto-send if there's exactly one factor.
          if (r.factors.length == 1) await _selectFactor(r.factors.first);
          return;
        }
        await _finishChurch(r);
      });

  Future<void> _selectFactor(BrokerFactor f) => _run(() async {
        await _broker.selectFactor(_loginId!, f.id);
        setState(() => _factorSent = f);
      });

  Future<void> _verifyMfa() => _run(() async {
        final r = await _broker.verifyMfa(_loginId!, _mfaCode.text.trim(), enroll: _authorizeSync);
        await _finishChurch(r);
      });

  /// After a successful Church login: block a no-access calling (N2); otherwise — if the leader
  /// did NOT authorize sync but their access could improve an existing, insufficient stake
  /// credential — offer to take over (re-auth with consent so the better credential is stored).
  /// Finally, adopt the session.
  Future<void> _finishChurch(BrokerResult r) async {
    if (_noAccess(r)) return;
    if (!_authorizeSync && r.canImprove) {
      final yes = await _offerTakeover(r);
      if (yes == true) {
        setState(() => _authorizeSync = true);
        await _churchSignIn(); // re-auth WITH consent → stores + replaces the weaker credential
        return;
      }
    }
    await _consume(r);
  }

  /// Higher-access transfer offer: the stake's current sync credential can't pull everything and
  /// this leader's access can. Ask whether to authorize their session for the daily sync.
  Future<bool?> _offerTakeover(BrokerResult r) {
    final missing = r.missing.isNotEmpty ? ' (missing: ${r.missing.take(3).join(', ')})' : '';
    return showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Improve your stake\'s sync?'),
        content: Text(
            '${r.stake ?? 'Your stake'} is currently synced by a leader whose access can\'t pull '
            'everything$missing. Your access can fill the gaps. Authorize your Church session to take '
            'over the daily sync? It\'s stored encrypted (never your password) and you can revoke it '
            'anytime in Settings.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Not now')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Authorize sync')),
        ],
      ),
    );
  }

  Future<void> _passkeySignIn() => _run(() async {
        final r = await _passkey.login();
        await _consume(r);
      });

  Future<void> _sendEmailCode() => _run(() async {
        if (_useRelay) {
          await _broker.emailStart(_email.text.trim()); // server-side, bypasses browser→Supabase
        } else {
          await supabase.auth.signInWithOtp(email: _email.text.trim());
        }
        setState(() => _emailCodeSent = true);
      });

  Future<void> _verifyEmailCode() => _run(() async {
        if (_useRelay) {
          // Broker verifies the code and returns tokens; adopt them as the local session.
          final t = await _broker.emailVerify(_email.text.trim(), _emailCode.text.trim());
          await supabase.auth.setSession(t['refresh_token'] as String);
        } else {
          await supabase.auth.verifyOTP(
            email: _email.text.trim(),
            token: _emailCode.text.trim(),
            type: OtpType.email,
          );
        }
      });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: AutofillGroup(
                child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('Covenant Path', style: Theme.of(context).textTheme.headlineSmall),
                  const SizedBox(height: 16),
                  if (_broker.available) ...[
                    SegmentedButton<_Mode>(
                      segments: const [
                        ButtonSegment(value: _Mode.church, label: Text('Church account')),
                        ButtonSegment(value: _Mode.email, label: Text('Email code')),
                      ],
                      selected: {_mode},
                      onSelectionChanged: _busy
                          ? null
                          : (s) => setState(() {
                                _mode = s.first;
                                _reset();
                              }),
                    ),
                    const SizedBox(height: 20),
                  ],
                  if (_mode == _Mode.church) ..._churchFields() else ..._emailFields(),
                  if (_passkey.available) ...[
                    const SizedBox(height: 16),
                    Row(children: [
                      const Expanded(child: Divider()),
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        child: Text('or', style: TextStyle(color: Colors.grey.shade600)),
                      ),
                      const Expanded(child: Divider()),
                    ]),
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: _busy ? null : _passkeySignIn,
                      icon: const Icon(Icons.fingerprint),
                      label: const Text('Sign in with a passkey'),
                    ),
                  ],
                  if (_busy && _status != null) ...[
                    const SizedBox(height: 12),
                    Text(_status!, style: TextStyle(color: Theme.of(context).colorScheme.primary)),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: const TextStyle(color: Colors.red)),
                  ],
                ],
              ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _spinnerOr(String label) => _busy
      ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
      : Text(label);

  List<Widget> _churchFields() {
    // Step 3: enter the MFA code that was sent.
    if (_factorSent != null) {
      return [
        Text('Enter the code sent via ${_factorSent!.label}.'),
        const SizedBox(height: 12),
        TextField(
          controller: _mfaCode,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: 'Verification code', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 16),
        FilledButton(onPressed: _busy ? null : _verifyMfa, child: _spinnerOr('Verify & sign in')),
        TextButton(
          onPressed: _busy ? null : () => setState(() => _factorSent = null),
          child: const Text('Choose a different method'),
        ),
      ];
    }
    // Step 2: pick an MFA factor.
    if (_loginId != null) {
      return [
        const Text('Choose how to receive your verification code:'),
        const SizedBox(height: 8),
        for (final f in _factors)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: OutlinedButton(
              onPressed: _busy ? null : () => _selectFactor(f),
              child: Text(f.label),
            ),
          ),
        TextButton(
          onPressed: _busy ? null : () => setState(_reset),
          child: const Text('Back'),
        ),
      ];
    }
    // Step 1: username + password.
    return [
      const Text('Sign in with your Church account (same as LCR).'),
      const SizedBox(height: 16),
      TextField(
        controller: _username,
        autofillHints: const [AutofillHints.username],
        decoration: const InputDecoration(labelText: 'Church username', border: OutlineInputBorder()),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _password,
        obscureText: true,
        autofillHints: const [AutofillHints.password],
        onSubmitted: (_) => _busy ? null : _churchSignIn(),
        decoration: const InputDecoration(labelText: 'Password', border: OutlineInputBorder()),
      ),
      const SizedBox(height: 6),
      // Explicit, default-OFF authorization — signing in alone never captures the session.
      CheckboxListTile(
        value: _authorizeSync,
        onChanged: _busy ? null : (v) => setState(() => _authorizeSync = v ?? false),
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        dense: true,
        title: const Text('Authorize daily sync for my stake'),
        subtitle: Text(
            'Stores this Church session (encrypted — never your password) so your stake\'s data '
            'refreshes daily. Optional — leave it off to just view. Revoke anytime in Settings.',
            style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
      ),
      const SizedBox(height: 6),
      FilledButton(onPressed: _busy ? null : _churchSignIn, child: _spinnerOr('Sign in')),
    ];
  }

  List<Widget> _emailFields() {
    return [
      const Text('Sign in with the email your stake has on file.'),
      if (_useRelay) ...[
        const SizedBox(height: 8),
        Row(children: [
          Icon(Icons.shield_outlined, size: 15, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 6),
          Expanded(
            child: Text('Backup mode: signing in through our server (for networks that block Supabase).',
                style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.primary)),
          ),
        ]),
      ],
      const SizedBox(height: 16),
      TextField(
        controller: _email,
        enabled: !_emailCodeSent,
        keyboardType: TextInputType.emailAddress,
        autofillHints: const [AutofillHints.email],
        decoration: const InputDecoration(labelText: 'Email', border: OutlineInputBorder()),
      ),
      if (_emailCodeSent) ...[
        const SizedBox(height: 12),
        TextField(
          controller: _emailCode,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: '6-digit code', border: OutlineInputBorder()),
        ),
      ],
      const SizedBox(height: 16),
      FilledButton(
        onPressed: _busy ? null : (_emailCodeSent ? _verifyEmailCode : _sendEmailCode),
        child: _spinnerOr(_emailCodeSent ? 'Verify & sign in' : 'Send code'),
      ),
      if (_emailCodeSent)
        TextButton(
          onPressed: _busy ? null : () => setState(() => _emailCodeSent = false),
          child: const Text('Use a different email'),
        ),
      // Backup sign-in for blocked networks (e.g. some regions can't reach Supabase directly).
      if (_broker.available && !_useRelay)
        TextButton(
          onPressed: _busy
              ? null
              : () => setState(() {
                    _useRelay = true;
                    _emailCodeSent = false;
                    _emailCode.clear();
                    _error = null;
                  }),
          child: const Text("Can't connect? Use backup sign-in"),
        ),
      if (_useRelay)
        TextButton(
          onPressed: _busy
              ? null
              : () => setState(() {
                    _useRelay = false;
                    _emailCodeSent = false;
                    _emailCode.clear();
                    _error = null;
                  }),
          child: const Text('Use normal sign-in'),
        ),
    ];
  }
}
