import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/format.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/screens/group_screen.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/add_flow.dart';
import 'package:qbit_web/widgets/common.dart';

/// Notification feed: everything the bot would have messaged — new episodes
/// (with one add button per release), auto-adds, completion pings (with a
/// Scan Plex button), stuck/error alerts, Plex scans.
class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key, this.standalone = false});
  final bool standalone; // pushed as its own route (shows a back button)

  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen> {
  List<Event>? _events;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
    _timer = Timer.periodic(
      const Duration(seconds: 20),
      (_) => _load(silent: true),
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    try {
      final data = await AppScope.read(context).api.get('/api/events');
      if (!mounted) return;
      setState(() {
        _events = [for (final e in jsonList(data['events'])) Event.fromJson(e)];
        _error = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      if (!silent || _events == null) setState(() => _error = e.message);
    }
  }

  Future<void> _markAllRead() async {
    final state = AppScope.read(context);
    await guard(context, () => state.api.post('/api/events/read', {}));
    await _load(silent: true);
    unawaited(state.refreshStatus());
  }

  Future<void> _dismiss(Event e) async {
    final state = AppScope.read(context);
    setState(() => _events?.remove(e));
    await guard(context, () => state.api.delete('/api/events/${e.id}'));
    unawaited(state.refreshStatus());
  }

  Future<void> _scanPlex(Event e) async {
    final state = AppScope.read(context);
    final data = await guard(
      context,
      () => state.api.post('/api/plex/scan', {'all': true}),
    );
    if (data != null && mounted) {
      final names = [
        for (final s in jsonList(data['scanning']))
          PlexSection.fromJson(s).label,
      ];
      showSnack(context, '🔍 Plex is scanning ${names.join(', ')}…');
    }
  }

  Future<void> _openSeries(Event e) async {
    final data = await guard(
      context,
      () => AppScope.read(context).api.get('/api/group', {'gid': e.gid}),
    );
    if (data == null || !mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => GroupScreen(group: Group.fromJson(data)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final events = _events;
    final unread = events?.where((e) => !e.read).length ?? 0;
    return Scaffold(
      appBar: AppBar(
        title: const Text('🔔 Activity'),
        actions: [
          if (unread > 0)
            TextButton.icon(
              icon: const Icon(Icons.done_all),
              label: const Text('Mark all read'),
              onPressed: _markAllRead,
            ),
          IconButton(
            tooltip: 'Reload',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: events == null
          ? (_error != null
                ? EmptyView(
                    icon: Icons.error_outline,
                    text: _error!,
                    onRetry: _load,
                  )
                : const Center(child: CircularProgressIndicator()))
          : events.isEmpty
          ? const EmptyView(
              icon: Icons.notifications_none,
              text:
                  'Nothing yet.\nNew-episode alerts for your favorites, completion pings '
                  'and stuck-download warnings show up here (and in Telegram, if the bot runs).',
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: Constrained(
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 32),
                  itemCount: events.length,
                  itemBuilder: (ctx, i) {
                    final e = events[i];
                    return Dismissible(
                      key: ValueKey(e.id),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        alignment: Alignment.centerRight,
                        padding: const EdgeInsets.only(right: 24),
                        child: const Icon(Icons.delete_outline),
                      ),
                      onDismissed: (_) => _dismiss(e),
                      child: EventCard(
                        event: e,
                        onScanPlex: () => _scanPlex(e),
                        onOpenSeries: e.gid.isEmpty
                            ? null
                            : () => _openSeries(e),
                        onDismiss: () => _dismiss(e),
                      ),
                    );
                  },
                ),
              ),
            ),
    );
  }
}

class EventCard extends StatelessWidget {
  const EventCard({
    required this.event,
    required this.onScanPlex,
    required this.onDismiss,
    super.key,
    this.onOpenSeries,
  });
  final Event event;
  final VoidCallback onScanPlex;
  final VoidCallback onDismiss;
  final VoidCallback? onOpenSeries;

  @override
  Widget build(BuildContext context) {
    final e = event;
    final theme = Theme.of(context);
    final (icon, title, body) = switch (e.type) {
      'new_episodes' => (
        '🆕',
        '${e.series} — new episode${e.episodes.length > 1 ? 's' : ''}: ${e.episodes.join(', ')}',
        'Pick a version to add to qBittorrent:',
      ),
      'auto_added' => (
        '⚡',
        '${e.series} — auto-added',
        'with ${e.seriesDefault?.label ?? 'the series default'}',
      ),
      'completed' => (
        '🏁',
        e.name,
        'Download complete — files are in their final location.'
            '${e.category.isNotEmpty ? '\n📁 ${e.category}' : ''}',
      ),
      'error' => (
        '❌',
        e.name,
        'Ran into a problem (state: ${e.state}) — check qBittorrent.',
      ),
      'stalled' => (
        '🐌',
        e.name,
        'Stalled at ${(e.progress * 100).round()}% for over ${e.hours} h — no connectable seeds?',
      ),
      'plex_scan' => (
        '🔍',
        'Plex is scanning ${e.libraries.join(', ')}',
        'Started automatically after a download.',
      ),
      'plex_scan_failed' => ('⚠️', 'Auto Plex scan failed', e.error),
      _ => ('ℹ️', e.type, ''),
    };
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      color: e.read
          ? null
          : theme.colorScheme.primaryContainer.withValues(alpha: 0.35),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(icon, style: const TextStyle(fontSize: 22)),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: theme.textTheme.titleSmall),
                      if (body.isNotEmpty)
                        Text(body, style: theme.textTheme.bodySmall),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Text(fmtDateTime(e.ts), style: theme.textTheme.labelSmall),
                IconButton(
                  tooltip: 'Dismiss',
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: onDismiss,
                ),
              ],
            ),
            if (e.type == 'new_episodes')
              for (final r in e.releases)
                ReleaseRow(
                  release: r,
                  dense: true,
                  onTap: () async {
                    final def = await fetchDefault(context, e.gid);
                    if (!context.mounted) return;
                    await startAdd(
                      context,
                      AddSource.hebits(
                        tid: r.id,
                        title: r.title,
                        gid: e.gid,
                        series: e.series,
                        seriesDefault: def,
                      ),
                    );
                  },
                ),
            if (e.type == 'auto_added')
              for (final r in e.releases)
                Padding(
                  padding: const EdgeInsets.only(left: 34, top: 2),
                  child: Text(
                    '• ${r.episode} · ${r.resolution.isEmpty ? '?' : r.resolution} · ${fmtSize(r.size)} · 🌱${r.seeders}',
                    style: theme.textTheme.bodySmall,
                  ),
                ),
            Wrap(
              spacing: 8,
              children: [
                if (e.type == 'completed' && !e.autoScan)
                  TextButton.icon(
                    icon: const Icon(Icons.movie_filter_outlined, size: 18),
                    label: const Text('Scan Plex now'),
                    onPressed: onScanPlex,
                  ),
                if (onOpenSeries != null &&
                    (e.type == 'new_episodes' || e.type == 'auto_added'))
                  TextButton.icon(
                    icon: const Icon(Icons.open_in_new, size: 18),
                    label: const Text('Open series'),
                    onPressed: onOpenSeries,
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
