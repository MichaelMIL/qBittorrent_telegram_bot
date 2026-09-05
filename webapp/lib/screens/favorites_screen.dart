import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/screens/activity_screen.dart';
import 'package:qbit_web/screens/group_screen.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/add_flow.dart';
import 'package:qbit_web/widgets/common.dart';

/// Starred series: open, toggle ⚡ auto-add, set/edit the default, remove,
/// and check all of them for new episodes right now.
class FavoritesScreen extends StatefulWidget {
  const FavoritesScreen({super.key});

  @override
  State<FavoritesScreen> createState() => _FavoritesScreenState();
}

class _FavoritesScreenState extends State<FavoritesScreen> {
  List<Favorite>? _items;
  String? _error;
  bool _checking = false;
  String? _opening;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final data = await AppScope.read(context).api.get('/api/favorites');
      if (!mounted) return;
      setState(() {
        _items = [
          for (final f in jsonList(data['favorites'])) Favorite.fromJson(f),
        ];
        _error = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      setState(() => _error = e.message);
    }
  }

  Future<void> _open(Favorite f) async {
    setState(() => _opening = f.gid);
    final data = await guard(
      context,
      () => AppScope.read(
        context,
      ).api.get('/api/group', {'gid': f.gid, 'q': f.query}),
    );
    if (!mounted) return;
    setState(() => _opening = null);
    if (data == null) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => GroupScreen(group: Group.fromJson(data)),
      ),
    );
    unawaited(_load());
  }

  Future<void> _toggleAuto(Favorite f) async {
    final api = AppScope.read(context).api;
    if (f.auto) {
      final ok = await guard(
        context,
        () => api.patch('/api/favorites/${f.gid}', {'auto': false}),
      );
      if (ok != null && mounted) {
        showSnack(context, "💤 Auto-add off — you'll just be notified.");
      }
    } else if (f.seriesDefault == null || f.seriesDefault!.category.isEmpty) {
      // no default yet — walk through setting one right here
      if (!await confirm(
        context,
        title: '⚡ ${f.name}',
        body:
            'This series needs a default (tag, category, resolution) before its '
            'episodes can be auto-added. Set one now?',
        yes: 'Set default',
      )) {
        return;
      }
      if (!mounted) return;
      await runDefaultWizard(
        context,
        gid: f.gid,
        name: f.name,
        enableAuto: true,
      );
    } else {
      final ok = await guard(
        context,
        () => api.patch('/api/favorites/${f.gid}', {'auto': true}),
      );
      if (ok != null && mounted) {
        showSnack(context, '⚡ Auto-add on: ${f.seriesDefault!.label}');
      }
    }
    unawaited(_load());
  }

  Future<void> _menu(Favorite f) async {
    final action = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              title: Text(f.name, style: Theme.of(ctx).textTheme.titleMedium),
              subtitle: Text(
                '📌 Default: ${f.seriesDefault?.label ?? 'not set'}\n'
                '⚡ Auto-add: ${f.auto ? 'on — new episodes are grabbed automatically' : 'off — new episodes just notify'}'
                '${f.lastEpLabel != null ? '\n🆕 Newest known episode: ${f.lastEpLabel}' : ''}',
              ),
              isThreeLine: true,
            ),
            const Divider(),
            ListTile(
              leading: Icon(f.auto ? Icons.bolt_outlined : Icons.bolt),
              title: Text(
                f.auto ? '💤 Turn auto-add off' : '⚡ Turn auto-add on',
              ),
              onTap: () => Navigator.pop(ctx, 'auto'),
            ),
            ListTile(
              leading: const Icon(Icons.push_pin_outlined),
              title: Text(
                f.seriesDefault != null ? '✏️ Edit default' : '📌 Set default',
              ),
              onTap: () => Navigator.pop(ctx, 'default'),
            ),
            if (f.seriesDefault != null)
              ListTile(
                leading: const Icon(Icons.delete_sweep_outlined),
                title: const Text('🗑 Forget default'),
                onTap: () => Navigator.pop(ctx, 'forget'),
              ),
            ListTile(
              leading: const Icon(Icons.heart_broken_outlined),
              title: const Text('💔 Remove from favorites'),
              onTap: () => Navigator.pop(ctx, 'remove'),
            ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
    if (action == null || !mounted) return;
    final api = AppScope.read(context).api;
    switch (action) {
      case 'auto':
        await _toggleAuto(f);
      case 'default':
        await runDefaultWizard(
          context,
          gid: f.gid,
          name: f.name,
          current: f.seriesDefault,
        );
      case 'forget':
        final ok = await guard(
          context,
          () => api.delete('/api/defaults/${f.gid}'),
        );
        if (ok != null && mounted) {
          showSnack(context, '🗑 Default forgotten (auto-add off).');
        }
      case 'remove':
        final ok = await guard(
          context,
          () => api.delete('/api/favorites/${f.gid}'),
        );
        if (ok != null && mounted) showSnack(context, 'Removed ${f.name}');
    }
    unawaited(_load());
    if (mounted) unawaited(AppScope.read(context).refreshStatus());
  }

  Future<void> _check() async {
    setState(() => _checking = true);
    final data = await guard(
      context,
      () => AppScope.read(context).api.post('/api/favorites/check'),
    );
    if (!mounted) return;
    setState(() => _checking = false);
    if (data == null) return;
    final notes = data['notifications'] as List;
    unawaited(AppScope.read(context).refreshStatus());
    unawaited(_load());
    if (notes.isEmpty) {
      showSnack(context, '✅ No new episodes for your favorites.');
      return;
    }
    showSnack(
      context,
      '🆕 ${notes.length} new-episode notification(s) — see Activity.',
    );
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => const ActivityScreen(standalone: true),
      ),
    );
    unawaited(_load());
  }

  @override
  Widget build(BuildContext context) {
    final items = _items;
    return Scaffold(
      appBar: AppBar(
        title: const Text('⭐ Favorites'),
        actions: [
          IconButton(
            tooltip: 'Reload',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'fav-check',
        onPressed: _checking ? null : _check,
        icon: _checking
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.new_releases_outlined),
        label: Text(_checking ? 'Checking…' : 'Check episodes'),
      ),
      body: items == null
          ? (_error != null
                ? EmptyView(
                    icon: Icons.error_outline,
                    text: _error!,
                    onRetry: _load,
                  )
                : const Center(child: CircularProgressIndicator()))
          : items.isEmpty
          ? const EmptyView(
              icon: Icons.star_border,
              text:
                  'No favorites yet.\nOpen a series from a search and tap ⭐ Add to favorites.',
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: Constrained(
                child: ListView(
                  padding: const EdgeInsets.only(bottom: 88, top: 4),
                  children: [
                    const Padding(
                      padding: EdgeInsets.fromLTRB(16, 8, 16, 4),
                      child: Text(
                        '⚡ auto-adds new episodes · 💤 just notifies — tap the switch to toggle, '
                        'the ⋮ menu for the default.',
                        style: TextStyle(fontSize: 12),
                      ),
                    ),
                    for (final f in items)
                      ListTile(
                        leading: _opening == f.gid
                            ? const SizedBox(
                                width: 24,
                                height: 24,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : Text(
                                f.auto ? '⚡' : '💤',
                                style: const TextStyle(fontSize: 22),
                              ),
                        title: Text(f.name),
                        subtitle: Text(
                          [
                            if (f.seriesDefault != null)
                              '📌 ${f.seriesDefault!.label}'
                            else
                              '📌 no default',
                            if (f.lastEpLabel != null) '🆕 ${f.lastEpLabel}',
                          ].join(' · '),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Tooltip(
                              message: 'Auto-add',
                              child: Switch(
                                value: f.auto,
                                onChanged: (_) => _toggleAuto(f),
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.more_vert),
                              onPressed: () => _menu(f),
                            ),
                          ],
                        ),
                        onTap: () => _open(f),
                      ),
                  ],
                ),
              ),
            ),
    );
  }
}
