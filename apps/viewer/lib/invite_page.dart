import 'package:flutter/material.dart';

import 'main.dart';

/// Power users: give someone your exact access. They sign in with the invited email
/// (a one-time code — no Church account needed) and see what you see, and can invite
/// others. Backed by the invite_power_user / revoke_power_user RPCs (escalation-safe:
/// you can only clone roles you hold).
class InvitePage extends StatefulWidget {
  const InvitePage({super.key});
  @override
  State<InvitePage> createState() => _InvitePageState();
}

class _InvitePageState extends State<InvitePage> {
  final _email = TextEditingController();
  bool _busy = false;
  String? _msg;
  bool _ok = false;
  late Future<List<Map<String, dynamic>>> _invites;
  List<Map<String, dynamic>> _units = [];
  String? _unitId; // null => grant everything the inviter can see

  @override
  void initState() {
    super.initState();
    _invites = _load();
    _loadUnits();
  }

  Future<void> _loadUnits() async {
    try {
      final rows = await supabase.from('units').select('id, name').order('name');
      if (mounted) setState(() => _units = (rows as List).cast<Map<String, dynamic>>());
    } catch (_) {/* RLS may allow none; the "everything" option still works */}
  }

  Future<List<Map<String, dynamic>>> _load() async {
    final rows = await supabase
        .from('invitations')
        .select('invited_email, role, unit_id, status, invited_by_email, created_at')
        .order('created_at', ascending: false);
    return (rows as List).cast<Map<String, dynamic>>();
  }

  Future<void> _invite() async {
    final email = _email.text.trim();
    if (email.isEmpty) return;
    setState(() { _busy = true; _msg = null; });
    try {
      final params = {'p_email': email, if (_unitId != null) 'p_unit': _unitId};
      final n = await supabase.rpc('invite_power_user', params: params);
      _msg = 'Invited $email ($n scope${n == 1 ? '' : 's'}). They can sign in with that email.';
      _ok = true;
      _email.clear();
      _invites = _load();
    } catch (e) {
      _msg = 'Could not invite: $e';
      _ok = false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _revoke(String email) async {
    try {
      await supabase.rpc('revoke_power_user', params: {'p_email': email});
    } finally {
      if (mounted) setState(() => _invites = _load());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Power users')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Give someone your exact access. They sign in with the invited '
                'email (a one-time code is sent — no Church account needed), see what you '
                'see, and can invite others.'),
            const SizedBox(height: 12),
            if (_units.length > 1)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: DropdownButtonFormField<String?>(
                  initialValue: _unitId,
                  decoration: const InputDecoration(labelText: 'Access to', border: OutlineInputBorder()),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('Everything I can see')),
                    for (final u in _units)
                      DropdownMenuItem(value: u['id'].toString(), child: Text('${u['name']} only')),
                  ],
                  onChanged: (v) => setState(() => _unitId = v),
                ),
              ),
            Row(children: [
              Expanded(child: TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(labelText: 'Email to invite', border: OutlineInputBorder()),
              )),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: _busy ? null : _invite,
                child: _busy
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('Invite'),
              ),
            ]),
            if (_msg != null) Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(_msg!, style: TextStyle(color: _ok ? Colors.green.shade700 : Colors.red)),
            ),
          ]),
        ),
        const Divider(height: 1),
        Expanded(child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _invites,
          builder: (context, snap) {
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final rows = snap.data!;
            if (rows.isEmpty) {
              return const Center(child: Text('No power users invited yet.'));
            }
            // collapse multiple scope rows per email
            final byEmail = <String, Map<String, dynamic>>{};
            for (final r in rows) {
              byEmail.putIfAbsent(r['invited_email'].toString(), () => r);
            }
            return ListView(children: [
              for (final r in byEmail.values)
                ListTile(
                  leading: Icon(r['status'] == 'revoked' ? Icons.person_off : Icons.person),
                  title: Text(r['invited_email'].toString()),
                  subtitle: Text('${r['role']} • ${r['status']}'
                      '${r['invited_by_email'] != null ? ' • by ${r['invited_by_email']}' : ''}'),
                  trailing: r['status'] == 'revoked'
                      ? null
                      : TextButton(
                          onPressed: () => _revoke(r['invited_email'].toString()),
                          child: const Text('Revoke'),
                        ),
                ),
            ]);
          },
        )),
      ]),
    );
  }
}
