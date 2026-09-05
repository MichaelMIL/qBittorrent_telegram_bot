import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/format.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/screens/plex_screen.dart';
import 'package:qbit_web/screens/torrent_screen.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/add_flow.dart';
import 'package:qbit_web/widgets/common.dart';

/// Everything in qBittorrent, filterable by tag or category, live-refreshing.
class TorrentsScreen extends StatefulWidget {
  const TorrentsScreen({super.key});

  @override
  State<TorrentsScreen> createState() => _TorrentsScreenState();
}

class _TorrentsScreenState extends State<TorrentsScreen> {
  List<Torrent>? _torrents;
  String? _error;
  String? _tag;
  String? _category;
  Timer? _timer;
  String _search = '';

  @override
  void initState() {
    super.initState();
    unawaited(_load());
    _timer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => _load(silent: true),
    );
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent) setState(() => _error = null);
    try {
      final data = await AppScope.read(context).api.get('/api/torrents', {
        'tag': _tag,
        'category': _category,
      });
      if (!mounted) return;
      setState(() {
        _torrents = [
          for (final t in jsonList(data['torrents'])) Torrent.fromJson(t),
        ];
        _error = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      if (!silent || _torrents == null) setState(() => _error = e.message);
    }
  }

  Future<void> _pickFilter() async {
    final api = AppScope.read(context).api;
    final data = await guard(context, () async {
      final r = await Future.wait([
        api.get('/api/tags'),
        api.get('/api/categories'),
      ]);
      return (
        [for (final t in (r[0]['tags'] as List)) '$t'],
        [for (final c in (r[1]['categories'] as List)) '$c'],
      );
    });
    if (data == null || !mounted) return;
    final (tags, cats) = data;
    final choice = await showModalBottomSheet<(String, String?)>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        maxChildSize: 0.95,
        builder: (ctx, controller) => ListView(
          controller: controller,
          children: [
            ListTile(
              leading: const Icon(Icons.all_inclusive),
              title: const Text('📚 All torrents'),
              selected: _tag == null && _category == null,
              onTap: () => Navigator.pop(ctx, ('all', null)),
            ),
            const SectionTitle('🏷 Tags'),
            if (tags.isEmpty)
              const ListTile(
                title: Text("No tags yet. Add one from a torrent's tag menu."),
              ),
            for (final t in tags)
              ListTile(
                leading: const Icon(Icons.label_outline),
                title: Text(t),
                selected: _tag == t,
                onTap: () => Navigator.pop(ctx, ('tag', t)),
              ),
            const SectionTitle('📁 Categories'),
            if (cats.isEmpty)
              const ListTile(
                title: Text('No categories defined in qBittorrent.'),
              ),
            for (final c in cats)
              ListTile(
                leading: const Icon(Icons.folder_outlined),
                title: Text(c),
                selected: _category == c,
                onTap: () => Navigator.pop(ctx, ('cat', c)),
              ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
    if (choice == null) return;
    setState(() {
      _tag = choice.$1 == 'tag' ? choice.$2 : null;
      _category = choice.$1 == 'cat' ? choice.$2 : null;
      _torrents = null;
    });
    unawaited(_load());
  }

  @override
  Widget build(BuildContext context) {
    final all = _torrents;
    final q = _search.toLowerCase();
    final items = all == null
        ? null
        : [
            for (final t in all)
              if (q.isEmpty || t.name.toLowerCase().contains(q)) t,
          ];
    final filterLabel = _tag != null
        ? '🏷 $_tag'
        : _category != null
        ? '📁 $_category'
        : '📚 All torrents';
    final dl = all?.fold<int>(0, (a, t) => a + t.dlspeed) ?? 0;
    final up = all?.fold<int>(0, (a, t) => a + t.upspeed) ?? 0;

    return Scaffold(
      appBar: AppBar(
        title: Text(filterLabel),
        actions: [
          IconButton(
            tooltip: 'Filter by tag / category',
            icon: Icon(
              (_tag ?? _category) == null
                  ? Icons.filter_list
                  : Icons.filter_list_alt,
            ),
            onPressed: _pickFilter,
          ),
          if (AppScope.of(context).can('plex'))
            IconButton(
              tooltip: 'Plex libraries',
              icon: const Icon(Icons.movie_filter_outlined),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const PlexScreen()),
              ),
            ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    decoration: const InputDecoration(
                      isDense: true,
                      prefixIcon: Icon(Icons.search, size: 20),
                      hintText: 'Filter by name',
                      border: OutlineInputBorder(),
                    ),
                    onChanged: (v) => setState(() => _search = v),
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  '⬇️ ${fmtSpeed(dl)}\n⬆️ ${fmtSpeed(up)}',
                  style: Theme.of(context).textTheme.bodySmall,
                  textAlign: TextAlign.right,
                ),
              ],
            ),
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton(
        heroTag: 'library-add',
        tooltip: 'Add magnet / .torrent',
        onPressed: () async {
          await addManually(context);
          unawaited(_load(silent: true));
        },
        child: const Icon(Icons.add),
      ),
      body: _error != null && all == null
          ? EmptyView(icon: Icons.cloud_off, text: _error!, onRetry: _load)
          : items == null
          ? const Center(child: CircularProgressIndicator())
          : items.isEmpty
          ? const EmptyView(icon: Icons.inbox_outlined, text: 'Nothing here.')
          : RefreshIndicator(
              onRefresh: _load,
              child: Constrained(
                child: ListView.builder(
                  padding: const EdgeInsets.only(bottom: 88),
                  itemCount: items.length + 1,
                  itemBuilder: (ctx, i) {
                    if (i == items.length) {
                      return Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text(
                          '${all!.length} torrent(s)'
                          '${_error != null ? ' · ⚠️ $_error' : ''}',
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      );
                    }
                    final t = items[i];
                    return TorrentRow(
                      torrent: t,
                      onTap: () async {
                        await Navigator.of(ctx).push(
                          MaterialPageRoute<void>(
                            builder: (_) => TorrentScreen(hash: t.hash),
                          ),
                        );
                        unawaited(_load(silent: true));
                      },
                    );
                  },
                ),
              ),
            ),
    );
  }
}

class TorrentRow extends StatelessWidget {
  const TorrentRow({required this.torrent, required this.onTap, super.key});
  final Torrent torrent;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final t = torrent;
    final theme = Theme.of(context);
    final active = t.dlspeed > 0 || t.upspeed > 0;
    final line = [
      stateName(t.state),
      fmtSize(t.size),
      if (t.dlspeed > 0) '⬇️ ${fmtSpeed(t.dlspeed)}',
      if (t.upspeed > 0) '⬆️ ${fmtSpeed(t.upspeed)}',
      if (!t.done && t.dlspeed > 0) 'ETA ${fmtEta(t.eta)}',
    ].join(' · ');
    return ListTile(
      leading: Text(stateIcon(t.state), style: const TextStyle(fontSize: 22)),
      title: Text(t.name, maxLines: 2, overflow: TextOverflow.ellipsis),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: t.progress,
              minHeight: 6,
              color: t.done
                  ? Colors.green
                  : t.paused
                  ? theme.colorScheme.outline
                  : null,
              backgroundColor: theme.colorScheme.surfaceContainerHighest,
            ),
          ),
          const SizedBox(height: 4),
          Text(line, style: theme.textTheme.bodySmall),
          if (t.category.isNotEmpty || t.tags.isNotEmpty)
            Text(
              [
                if (t.category.isNotEmpty) '📁 ${t.category}',
                for (final tag in t.tags) '🏷 $tag',
              ].join('  '),
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.primary,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
        ],
      ),
      trailing: Text(
        fmtPercent(t.progress),
        style: theme.textTheme.titleSmall?.copyWith(
          color: active ? theme.colorScheme.primary : null,
        ),
      ),
      isThreeLine: true,
      onTap: onTap,
    );
  }
}
