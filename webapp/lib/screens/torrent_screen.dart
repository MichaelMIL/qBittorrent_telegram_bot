import 'dart:async';

import 'package:flutter/material.dart';

import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/format.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/add_flow.dart';
import 'package:qbit_web/widgets/common.dart';

/// One torrent: live progress/speeds, pause/resume, tags, category, delete.
class TorrentScreen extends StatefulWidget {
  const TorrentScreen({required this.hash, super.key});
  final String hash;

  @override
  State<TorrentScreen> createState() => _TorrentScreenState();
}

class _TorrentScreenState extends State<TorrentScreen> {
  Torrent? _t;
  String? _error;
  bool _gone = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_gone) return;
    try {
      final data = await AppScope.read(
        context,
      ).api.get('/api/torrents/${widget.hash}');
      if (!mounted) return;
      setState(() {
        _t = Torrent.fromJson(data);
        _error = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      setState(() {
        _error = e.message;
        if (e.status == 404) _gone = true;
      });
    }
  }

  Future<void> _action(String what) async {
    final api = AppScope.read(context).api;
    final ok = await guard(
      context,
      () => api.post('/api/torrents/${widget.hash}/$what'),
    );
    if (ok != null && mounted) {
      showSnack(context, what == 'pause' ? 'Paused' : 'Resumed');
      unawaited(_load());
    }
  }

  Future<void> _toggleTag(String tag, bool on) async {
    final api = AppScope.read(context).api;
    final data = await guard(
      context,
      () => api.post('/api/torrents/${widget.hash}/tags', {
        if (on) 'add': [tag] else 'remove': [tag],
      }),
    );
    if (data != null && mounted) setState(() => _t = Torrent.fromJson(data));
  }

  Future<void> _newTag() async {
    final name = await promptText(context, title: 'New tag', hint: 'Tag name');
    if (name == null) return;
    await _toggleTag(name.replaceAll(',', ' ').trim(), true);
  }

  Future<void> _tagsSheet() async {
    final api = AppScope.read(context).api;
    final tags = await guard(context, () async {
      final r = await api.get('/api/tags');
      return [for (final t in (r['tags'] as List)) '$t'];
    });
    if (tags == null || !mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => DraggableScrollableSheet(
          expand: false,
          initialChildSize: 0.6,
          maxChildSize: 0.95,
          builder: (ctx, controller) => ListView(
            controller: controller,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(20, 0, 20, 8),
                child: Text(
                  '🏷 Tags — tap to toggle',
                  style: TextStyle(fontSize: 18),
                ),
              ),
              for (final tag in tags)
                CheckboxListTile(
                  title: Text(tag),
                  value: _t?.tags.contains(tag) ?? false,
                  onChanged: (v) async {
                    await _toggleTag(tag, v == true);
                    setSheet(() {});
                  },
                ),
              ListTile(
                leading: const Icon(Icons.add),
                title: const Text('New tag…'),
                onTap: () async {
                  Navigator.pop(ctx);
                  await _newTag();
                },
              ),
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _changeCategory() async {
    final c = await pickCategory(
      context,
      current: _t?.category,
      title: '📁 Category',
    );
    if (c == null || !mounted) return;
    final api = AppScope.read(context).api;
    final ok = await guard(
      context,
      () => api.post('/api/torrents/${widget.hash}/category', {
        'category': c.isEmpty ? null : c,
      }),
    );
    if (ok != null) {
      unawaited(_load());
      if (mounted) {
        showSnack(
          context,
          c.isEmpty ? 'Category cleared' : 'Category set to “$c”',
        );
      }
    }
  }

  Future<void> _delete() async {
    final choice = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('⚠️ Delete this torrent?'),
        content: const Text('This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('🗑 Remove torrent only'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(ctx).colorScheme.error,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('💥 Remove + delete files'),
          ),
        ],
      ),
    );
    if (choice == null || !mounted) return;
    final api = AppScope.read(context).api;
    final res = await guard(
      context,
      () => api.delete('/api/torrents/${widget.hash}', {
        'files': choice ? 'true' : 'false',
      }),
    );
    if (res != null && mounted) {
      _timer?.cancel();
      showSnack(
        context,
        '🗑 ${res['name']} removed${choice ? ' and its files were deleted' : ' (files kept)'}.',
      );
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = _t;
    return Scaffold(
      appBar: AppBar(
        title: Text(t?.name ?? 'Torrent'),
        actions: [
          if (t != null)
            IconButton(
              tooltip: 'Delete',
              icon: const Icon(Icons.delete_outline),
              onPressed: _delete,
            ),
        ],
      ),
      body: t == null
          ? (_error != null
                ? EmptyView(
                    icon: Icons.error_outline,
                    text: _error!,
                    onRetry: _gone ? null : _load,
                  )
                : const Center(child: CircularProgressIndicator()))
          : Constrained(
              maxWidth: 720,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Row(
                    children: [
                      Text(
                        stateIcon(t.state),
                        style: const TextStyle(fontSize: 28),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          t.name,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: LinearProgressIndicator(
                      value: t.progress,
                      minHeight: 12,
                      color: t.done ? Colors.green : null,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '${fmtPercent(t.progress)} · ${stateName(t.state)}',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 16),
                  _Facts(
                    rows: [
                      ('Size', fmtSize(t.size)),
                      (
                        'Downloaded / uploaded',
                        '${fmtSize(t.downloaded)} / ${fmtSize(t.uploaded)}',
                      ),
                      (
                        'Speed',
                        '⬇️ ${fmtSpeed(t.dlspeed)}   ⬆️ ${fmtSpeed(t.upspeed)}',
                      ),
                      ('Ratio', t.ratio.toStringAsFixed(2)),
                      ('ETA', t.done ? '—' : fmtEta(t.eta)),
                      (
                        'Peers',
                        '🌱 ${t.numSeeds} seeds · 🩸 ${t.numLeechs} leechers',
                      ),
                      (
                        'Added',
                        fmtDateTime(
                          DateTime.fromMillisecondsSinceEpoch(t.addedOn * 1000),
                        ),
                      ),
                      if (t.completionOn > 0)
                        (
                          'Completed',
                          fmtDateTime(
                            DateTime.fromMillisecondsSinceEpoch(
                              t.completionOn * 1000,
                            ),
                          ),
                        ),
                      if (t.savePath.isNotEmpty) ('Path', t.savePath),
                      ('State', t.state),
                    ],
                  ),
                  const SizedBox(height: 16),
                  ListTile(
                    leading: const Icon(Icons.label_outline),
                    title: const Text('Tags'),
                    subtitle: Text(t.tags.isEmpty ? '—' : t.tags.join(', ')),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: _tagsSheet,
                  ),
                  ListTile(
                    leading: const Icon(Icons.folder_outlined),
                    title: const Text('Category'),
                    subtitle: Text(t.category.isEmpty ? '—' : t.category),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: _changeCategory,
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 12,
                    runSpacing: 8,
                    children: [
                      FilledButton.icon(
                        icon: Icon(t.paused ? Icons.play_arrow : Icons.pause),
                        label: Text(t.paused ? 'Resume' : 'Pause'),
                        onPressed: () => _action(t.paused ? 'resume' : 'pause'),
                      ),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.delete_outline),
                        label: const Text('Delete'),
                        onPressed: _delete,
                      ),
                    ],
                  ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 16),
                      child: Text(
                        '⚠️ $_error',
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                ],
              ),
            ),
    );
  }
}

class _Facts extends StatelessWidget {
  const _Facts({required this.rows});
  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Column(
          children: [
            for (final (k, v) in rows)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 150,
                      child: Text(
                        k,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                    Expanded(child: SelectableText(v)),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
