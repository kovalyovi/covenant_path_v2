import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'golden_hour.dart';
import 'main.dart';

/// Full covenant-path detail for one member, laid out like LCR's "new member" record:
/// sacrament-attendance dots, friends in the church, priesthood / calling / ministering,
/// temple ordinances & experiences, principles taught, and self-reliance classes.
///
/// Driven by `member['details']` (the rich one-work subtree the sync now keeps). When
/// that's null — a row synced before the schema change — it falls back to the flat
/// fields so the page still renders.
class PersonDetailPage extends StatelessWidget {
  const PersonDetailPage({super.key, required this.member});
  final Map<String, dynamic> member;

  Map<String, dynamic>? get _details {
    final d = member['details'];
    return d is Map ? d.cast<String, dynamic>() : null;
  }

  @override
  Widget build(BuildContext context) {
    final name = member['name']?.toString() ?? '—';
    final d = _details;
    final memberSince =
        (d?['memberSince'] ?? member['membership_duration'])?.toString();
    final isInvestigator = member['kind'] == 'investigator';
    final goalDate = (member['baptism_goal_date'] ?? '').toString();
    final baptismDate = (member['baptism_date'] ?? '').toString();
    final baptismLine = isInvestigator
        ? (goalDate.isNotEmpty ? 'Planned baptism $goalDate' : null)
        : ((baptismDate.isNotEmpty && baptismDate != 'needs-profile-api')
            ? 'Baptized $baptismDate'
            : null);

    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: MaxWidthBody(
        maxWidth: 1000,
        child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
        children: [
          // header card (iOS-style): avatar + name + key date
          Card(
            elevation: 0,
            color: Theme.of(context).colorScheme.primaryContainer,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                PhotoAvatar(name: name, photoUrl: member['photo_url']?.toString(), size: 60),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(name,
                        style: Theme.of(context).textTheme.titleLarge?.copyWith(
                            color: Theme.of(context).colorScheme.onPrimaryContainer,
                            fontWeight: FontWeight.bold)),
                    if ((member['unit_name'] ?? '').toString().isNotEmpty)
                      Text(member['unit_name'].toString(),
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: Theme.of(context).colorScheme.onPrimaryContainer)),
                    if (memberSince != null && memberSince.isNotEmpty)
                      Text(memberSince,
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: Theme.of(context).colorScheme.onPrimaryContainer)),
                    if (baptismLine != null)
                      Text(baptismLine,
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context).colorScheme.onPrimaryContainer)),
                  ]),
                ),
              ]),
            ),
          ),
          const SizedBox(height: 8),

          // our covenant-path milestones (data LCR's view lacks: baptism/recommend/etc.)
          _Section(
            title: 'Covenant Path',
            leadingIcon: Icons.timeline,
            child: GoldenHourChips(member: member, size: 30, highlightNext: true),
          ),

          if (d != null)
            _RichBody(member: member, d: d)
          else
            _FlatFallback(member: member),

          _CommentsSection(member: member),
        ],
      ),
      ),
    );
  }
}

/// Two columns on wide screens, stacked on narrow (phones). Mirrors LCR's layout.
class _RichBody extends StatelessWidget {
  const _RichBody({required this.member, required this.d});
  final Map<String, dynamic> member;
  final Map<String, dynamic> d;

  @override
  Widget build(BuildContext context) {
    final left = <Widget>[
      _SacramentSection(d: d),
      _FriendsSection(d: d),
      _ListTextSection(
        title: 'Priesthood Ordination',
        icon: Icons.workspace_premium,
        lines: _strings(d['priesthoodOrdinations']),
        emptyText: 'No priesthood ordination on record.',
      ),
      _ListTextSection(
        title: 'Calling',
        icon: Icons.assignment_ind,
        lines: _strings(d['callings']),
        emptyText: 'Not yet been given a calling.',
        emptyIsAlert: true,
      ),
      _ListTextSection(
        title: 'Ministering Assignment',
        icon: Icons.volunteer_activism,
        lines: _strings(d['ministeringAssignments']),
        emptyText: 'Not yet received a ministering assignment.',
      ),
      _NamesSection(
        title: 'Ministering Brothers & Sisters',
        icon: Icons.diversity_3,
        names: [..._strings(d['ministeringBrothers']), ..._strings(d['ministeringSisters'])],
        emptyText: 'No ministers assigned.',
      ),
    ];
    final right = <Widget>[
      _TempleSection(d: d),
      _PrinciplesSection(d: d),
      _TogglesSection(
        title: 'Self-Reliance Classes Completed',
        icon: Icons.school,
        items: _toggles(d['selfReliance']),
      ),
      _TagsSection(d: d),
    ];

    return LayoutBuilder(builder: (context, c) {
      if (c.maxWidth < 720) {
        return Column(children: [...left, ...right]);
      }
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: Column(children: left)),
        const SizedBox(width: 28),
        Expanded(child: Column(children: right)),
      ]);
    });
  }
}

// ---- sections -------------------------------------------------------------

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child, this.trailing, this.leadingIcon});
  final String title;
  final Widget child;
  final Widget? trailing;
  final IconData? leadingIcon;
  @override
  Widget build(BuildContext context) =>
      SectionCard(title: title, trailing: trailing, leadingIcon: leadingIcon, child: child);
}

/// Sacrament dots. The stored list is newest-first; we show the most recent [_recent]
/// Sundays (rendered oldest→newest so the timeline reads left-to-right) with a "View all"
/// expander.
class _SacramentSection extends StatefulWidget {
  const _SacramentSection({required this.d});
  final Map<String, dynamic> d;
  @override
  State<_SacramentSection> createState() => _SacramentSectionState();
}

class _SacramentSectionState extends State<_SacramentSection> {
  static const _recent = 6;
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final all = (widget.d['sacrament'] as List?)?.cast<Map>() ?? const [];
    if (all.isEmpty) return const SizedBox.shrink();
    final shown = (_expanded ? all.toList() : all.take(_recent).toList()).reversed.toList();
    final missed = _missedCount(widget.d, all);
    final green = Colors.green.shade700;
    return _Section(
      title: 'Attended Sacrament Meeting',
      leadingIcon: Icons.event_available,
      trailing: all.length > _recent
          ? TextButton(
              onPressed: () => setState(() => _expanded = !_expanded),
              child: Text(_expanded ? 'Show recent' : 'View all (${all.length})'))
          : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 14, runSpacing: 10, children: [
          for (final s in shown)
            Column(children: [
              Text(s['label']?.toString() ?? '',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 4),
              Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: (s['attended'] == true) ? green : Colors.transparent,
                  border: Border.all(
                      color: (s['attended'] == true) ? green : Colors.grey.shade400,
                      width: 1.4),
                ),
                child: (s['attended'] == true)
                    ? const Icon(Icons.check, size: 16, color: Colors.white)
                    : null,
              ),
            ]),
        ]),
        if (missed > 0)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text('$missed sacrament meeting${missed == 1 ? '' : 's'} missed',
                style: TextStyle(color: Colors.red.shade700)),
          ),
      ]),
    );
  }

  int _missedCount(Map<String, dynamic> d, List list) {
    final msg = int.tryParse('${d['sacramentMissed'] ?? ''}');
    if (msg != null) return msg;
    return list.where((s) => s['attended'] != true).length;
  }
}

class _FriendsSection extends StatelessWidget {
  const _FriendsSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final friends = (d['friends'] as List?)?.cast<Map>() ?? const [];
    return _Section(
      title: 'Friends in the Church',
      leadingIcon: Icons.people_outline,
      child: friends.isEmpty
          ? _muted(context, 'No friends recorded yet.')
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (friends.any((f) => f['inStake'] == true))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('Inside the Stake',
                        style: Theme.of(context).textTheme.bodySmall),
                  ),
                for (final f in friends)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      InitialsAvatar(name: f['name']?.toString() ?? '?', size: 30),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(f['name']?.toString() ?? '—'),
                              if ((f['unit']?.toString() ?? '').isNotEmpty)
                                Text(f['unit'].toString(),
                                    style: Theme.of(context).textTheme.bodySmall),
                            ]),
                      ),
                    ]),
                  ),
              ],
            ),
    );
  }
}

class _ListTextSection extends StatelessWidget {
  const _ListTextSection({
    required this.title,
    required this.lines,
    required this.emptyText,
    this.emptyIsAlert = false,
    this.icon,
  });
  final String title;
  final List<String> lines;
  final String emptyText;
  final bool emptyIsAlert;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    return _Section(
      title: title,
      leadingIcon: icon,
      child: lines.isEmpty
          ? Text(emptyText,
              style: TextStyle(
                  color: emptyIsAlert ? Colors.red.shade700 : Colors.grey.shade600))
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final l in lines)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(l),
                  ),
              ],
            ),
    );
  }
}

class _NamesSection extends StatelessWidget {
  const _NamesSection(
      {required this.title, required this.names, required this.emptyText, this.icon});
  final String title;
  final List<String> names;
  final String emptyText;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    return _Section(
      title: title,
      leadingIcon: icon,
      child: names.isEmpty
          ? _muted(context, emptyText)
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final n in names)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(children: [
                      InitialsAvatar(name: n, size: 28),
                      const SizedBox(width: 10),
                      Expanded(child: Text(n)),
                    ]),
                  ),
              ],
            ),
    );
  }
}

class _TempleSection extends StatelessWidget {
  const _TempleSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final experiences = _toggles(d['templeExperiences']);
    final ordinances = _strings(d['templeOrdinances']);
    if (experiences.isEmpty && ordinances.isEmpty) return const SizedBox.shrink();
    return _Section(
      title: 'Temple Ordinances and Experiences',
      leadingIcon: Icons.account_balance,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final t in experiences) _ToggleRow(label: t.$1, on: t.$2),
        if (ordinances.isNotEmpty) const SizedBox(height: 8),
        for (final o in ordinances)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Text(o),
          ),
      ]),
    );
  }
}

class _PrinciplesSection extends StatelessWidget {
  const _PrinciplesSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final lessons = (d['lessons'] as List?)?.cast<Map>() ?? const [];
    if (lessons.isEmpty) return const SizedBox.shrink();
    final green = Colors.green.shade700;
    return _Section(
      title: 'Principles Taught',
      leadingIcon: Icons.menu_book,
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.person, size: 16, color: green),
        const SizedBox(width: 4),
        Text('= Member Present', style: Theme.of(context).textTheme.bodySmall),
      ]),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final l in lessons)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(l['name']?.toString() ?? '',
                    style: TextStyle(color: green, fontWeight: FontWeight.w500)),
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 6, children: [
                  for (final p in (l['principles'] as List?)?.cast<Map>() ?? const [])
                    _PrincipleDot(
                      taught: _taught(p['taughtLevel']),
                      memberPresent: p['memberPresent'] == true,
                      tooltip: p['name']?.toString() ?? '',
                    ),
                ]),
              ]),
            ),
        ],
      ),
    );
  }

  static bool _taught(dynamic level) {
    if (level == null) return false;
    final s = level.toString();
    return s.isNotEmpty && s != '0' && s != '0.0';
  }
}

class _PrincipleDot extends StatelessWidget {
  const _PrincipleDot({required this.taught, required this.memberPresent, required this.tooltip});
  final bool taught;
  final bool memberPresent;
  final String tooltip;
  @override
  Widget build(BuildContext context) {
    final green = Colors.green.shade700;
    return Tooltip(
      message: '$tooltip — ${taught ? 'taught' : 'not yet'}'
          '${memberPresent ? ' (member present)' : ''}',
      child: Container(
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: taught ? green : Colors.transparent,
          border: Border.all(color: green, width: 1.4),
        ),
        child: memberPresent
            ? Icon(Icons.person, size: 13, color: taught ? Colors.white : green)
            : null,
      ),
    );
  }
}

class _TogglesSection extends StatelessWidget {
  const _TogglesSection({required this.title, required this.items, this.icon});
  final String title;
  final List<(String, bool)> items;
  final IconData? icon;
  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    return _Section(
      title: title,
      leadingIcon: icon,
      child: Column(children: [for (final t in items) _ToggleRow(label: t.$1, on: t.$2)]),
    );
  }
}

class _ToggleRow extends StatelessWidget {
  const _ToggleRow({required this.label, required this.on});
  final String label;
  final bool on;
  @override
  Widget build(BuildContext context) {
    final green = Colors.green.shade700;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 3),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: on
            ? green.withValues(alpha: 0.08)
            : Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(children: [
        Icon(on ? Icons.check_circle : Icons.radio_button_unchecked,
            size: 20, color: on ? green : Colors.grey.shade400),
        const SizedBox(width: 10),
        Expanded(
          child: Text(label,
              style: TextStyle(fontWeight: on ? FontWeight.w500 : FontWeight.normal)),
        ),
      ]),
    );
  }
}

class _TagsSection extends StatelessWidget {
  const _TagsSection({required this.d});
  final Map<String, dynamic> d;
  @override
  Widget build(BuildContext context) {
    final tags = _strings(d['tags']);
    if (tags.isEmpty) return const SizedBox.shrink();
    return _Section(
      title: 'Flags',
      leadingIcon: Icons.flag,
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        for (final t in tags)
          Chip(
            label: Text(t),
            backgroundColor: Colors.amber.shade100,
            visualDensity: VisualDensity.compact,
          ),
      ]),
    );
  }
}

/// Pre-`details` rows: the original flat field list, so the page still works.
class _FlatFallback extends StatelessWidget {
  const _FlatFallback({required this.member});
  final Map<String, dynamic> member;

  static const _fields = <(String, String)>[
    ('Unit', 'unit_name'),
    ('Baptism date', 'baptism_date'),
    ('Birth date', 'birth_date'),
    ('Friends', 'friends'),
    ('Aaronic Priesthood', 'aaronic_priesthood'),
    ('Melchizedek Priesthood', 'melchizedek_priesthood'),
    ('Calling', 'calling'),
    ('Ministering brothers/sisters', 'ministering_brothers_sisters'),
    ('Ministering assignment', 'ministering_assignment'),
    ('Temple recommend', 'temple_recommend'),
    ('Patriarchal blessing', 'patriarchal_blessing'),
    ('Living ordinance', 'living_ordinance'),
  ];

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      const SizedBox(height: 8),
      const Divider(),
      for (final f in _fields)
        ListTile(
          dense: true,
          title: Text(f.$1),
          trailing: Text('${member[f.$2] ?? '—'}',
              style: const TextStyle(fontWeight: FontWeight.w500)),
        ),
    ]);
  }
}

// ---- notes / comments -----------------------------------------------------

/// Leader notes on a member (RLS-scoped to people you can see). Read + add; authors can't
/// see others' across scope boundaries — the DB enforces it.
class _CommentsSection extends StatefulWidget {
  const _CommentsSection({required this.member});
  final Map<String, dynamic> member;
  @override
  State<_CommentsSection> createState() => _CommentsSectionState();
}

class _CommentsSectionState extends State<_CommentsSection> {
  late Future<List<Map<String, dynamic>>> _future;
  final _ctrl = TextEditingController();
  bool _posting = false;

  String? get _uuid => widget.member['person_uuid']?.toString();

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<Map<String, dynamic>>> _load() async {
    final uuid = _uuid;
    if (uuid == null || uuid.isEmpty) return [];
    final rows = await supabase
        .from('member_comments')
        .select('author_email, author_name, body, created_at')
        .eq('member_person_uuid', uuid)
        .order('created_at');
    return (rows as List).cast<Map<String, dynamic>>();
  }

  Future<void> _post() async {
    final body = _ctrl.text.trim();
    final uuid = _uuid;
    if (body.isEmpty || uuid == null) return;
    setState(() => _posting = true);
    try {
      await supabase.from('member_comments').insert({
        'stake_id': widget.member['stake_id'],
        'unit_id': widget.member['unit_id'],
        'member_person_uuid': uuid,
        'author_email': supabase.auth.currentUser?.email ?? '',
        'body': body,
      });
      _ctrl.clear();
      setState(() => _future = _load());
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Could not post note: $e')));
      }
    } finally {
      if (mounted) setState(() => _posting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_uuid == null || _uuid!.isEmpty) return const SizedBox.shrink();
    return SectionCard(
      title: 'Notes',
      leadingIcon: Icons.chat_bubble_outline,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Padding(
                  padding: EdgeInsets.all(8), child: Center(child: CircularProgressIndicator()));
            }
            final list = snap.data ?? [];
            if (list.isEmpty) {
              return Text('No notes yet.', style: TextStyle(color: Colors.grey.shade600));
            }
            return Column(children: [for (final c in list) _tile(context, c)]);
          },
        ),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(
            child: TextField(
              controller: _ctrl,
              minLines: 1,
              maxLines: 4,
              decoration: const InputDecoration(hintText: 'Add a note…', border: OutlineInputBorder()),
            ),
          ),
          const SizedBox(width: 8),
          _posting
              ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
              : IconButton.filled(onPressed: _post, icon: const Icon(Icons.send)),
        ]),
      ]),
    );
  }

  Widget _tile(BuildContext context, Map<String, dynamic> c) {
    final who = (c['author_name'] ?? c['author_email'] ?? '').toString();
    final when = DateTime.tryParse('${c['created_at'] ?? ''}')?.toLocal();
    final ws = when != null ? DateFormat('MMM d, y · h:mm a').format(when) : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(c['body']?.toString() ?? ''),
        const SizedBox(height: 2),
        Text('$who · $ws',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600)),
        const Divider(height: 14),
      ]),
    );
  }
}

// ---- helpers --------------------------------------------------------------

List<String> _strings(dynamic v) =>
    (v as List?)?.map((e) => e.toString()).where((s) => s.isNotEmpty).toList() ?? [];

List<(String, bool)> _toggles(dynamic v) =>
    (v as List?)
        ?.cast<Map>()
        .map((e) => (e['name']?.toString() ?? '', e['done'] == true))
        .where((t) => t.$1.isNotEmpty)
        .toList() ??
    [];

Widget _muted(BuildContext context, String text) =>
    Text(text, style: TextStyle(color: Colors.grey.shade600));
