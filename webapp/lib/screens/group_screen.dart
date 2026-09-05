import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/format.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/add_flow.dart';
import 'package:qbit_web/widgets/common.dart';
import 'package:url_launcher/url_launcher.dart';

/// Detail card for one HeBits group: poster, titles, IMDB, favorite toggle,
/// season navigation and one row per release that starts the add flow.
class GroupScreen extends StatefulWidget {
  const GroupScreen({required this.group, super.key});
  final Group group;

  @override
  State<GroupScreen> createState() => _GroupScreenState();
}

class _GroupScreenState extends State<GroupScreen> {
  late Group _group = widget.group;
  int? _season;
  bool _refreshing = false;

  List<int> get _seasons {
    final s = {for (final t in _group.torrents) t.season}.toList()
      ..sort((a, b) => b.compareTo(a));
    return s; // newest first, "Other" (-1) last
  }

  List<Release> get _visible {
    final seasons = _seasons;
    if (seasons.length <= 1) return _group.torrents;
    final season = _season != null && seasons.contains(_season)
        ? _season!
        : seasons.first;
    return [
      for (final t in _group.torrents)
        if (t.season == season) t,
    ];
  }

  Future<void> _refresh() async {
    setState(() => _refreshing = true);
    final data = await guard(
      context,
      () => AppScope.read(
        context,
      ).api.get('/api/group', {'gid': _group.gid, 'q': _group.query}),
    );
    if (!mounted) return;
    setState(() {
      _refreshing = false;
      if (data != null) _group = Group.fromJson(data);
    });
  }

  Future<void> _toggleFavorite() async {
    final api = AppScope.read(context).api;
    if (_group.favorite) {
      final ok = await guard(
        context,
        () => api.delete('/api/favorites/${_group.gid}'),
      );
      if (ok == null || !mounted) return;
      setState(() {
        _group.favorite = false;
        _group.auto = false;
      });
      showSnack(context, 'Removed from favorites');
    } else {
      final ok = await guard(
        context,
        () => api.post('/api/favorites', {
          'gid': _group.gid,
          'name': _group.titleWithYear,
          'query': _group.query,
        }),
      );
      if (ok == null || !mounted) return;
      setState(() => _group.favorite = true);
      showSnack(context, '⭐ Added to favorites');
    }
    unawaited(AppScope.read(context).refreshStatus());
  }

  Future<void> _add(Release t) async {
    if (!AppScope.read(context).can('add')) {
      showSnack(context, 'Adding torrents is not enabled for this login.');
      return;
    }
    final added = await startAdd(
      context,
      AddSource.hebits(
        tid: t.id,
        title: t.title,
        gid: _group.gid.isEmpty ? null : _group.gid,
        series: _group.title,
        seriesDefault: _group.seriesDefault,
      ),
    );
    // pick up the new local status / default
    if (added && mounted) unawaited(_refresh());
  }

  @override
  Widget build(BuildContext context) {
    final g = _group;
    final seasons = _seasons;
    final current = _season != null && seasons.contains(_season)
        ? _season!
        : seasons.first;
    final items = _visible;
    final wide = MediaQuery.sizeOf(context).width >= 720;

    final header = Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: wide ? 180 : 110,
            height: wide ? 270 : 165,
            child: Poster(url: g.cover),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  g.titleWithYear,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                if (g.nameHe.isNotEmpty && g.nameHe != g.title)
                  Text(
                    g.nameHe,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                const SizedBox(height: 6),
                Text(
                  [
                    if (g.cat.isNotEmpty) g.cat,
                    '${g.torrents.length} release${g.torrents.length == 1 ? '' : 's'}',
                  ].join(' · '),
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                if (g.seriesDefault != null) ...[
                  const SizedBox(height: 6),
                  Text(
                    '📌 Default: ${g.seriesDefault!.label}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 4,
                  children: [
                    if (g.imdb.isNotEmpty)
                      OutlinedButton.icon(
                        icon: const Icon(Icons.open_in_new, size: 16),
                        label: const Text('IMDB'),
                        onPressed: () => launchUrl(
                          Uri.parse(g.imdb),
                          mode: LaunchMode.externalApplication,
                        ),
                      ),
                    if (AppScope.of(context).can('favorites'))
                      FilledButton.tonalIcon(
                        icon: Icon(
                          g.favorite ? Icons.star : Icons.star_border,
                        ),
                        label: Text(
                          g.favorite ? 'Favorite' : 'Add to favorites',
                        ),
                        onPressed: _toggleFavorite,
                      ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );

    return Scaffold(
      appBar: AppBar(
        title: Text(g.title),
        actions: [
          IconButton(
            tooltip: 'Reload from HeBits',
            icon: _refreshing
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
            onPressed: _refreshing ? null : _refresh,
          ),
        ],
      ),
      body: Constrained(
        child: ListView(
          padding: const EdgeInsets.only(bottom: 32),
          children: [
            header,
            if (seasons.length > 1)
              SizedBox(
                height: 48,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  children: [
                    for (final s in seasons)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: Text(
                            s >= 0
                                ? 'S${s.toString().padLeft(2, '0')}'
                                : 'Other',
                          ),
                          selected: s == current,
                          onSelected: (_) => setState(() => _season = s),
                        ),
                      ),
                  ],
                ),
              ),
            SectionTitle(
              '${items.length} release${items.length == 1 ? '' : 's'} — tap one to add',
            ),
            for (final t in items) ReleaseRow(release: t, onTap: () => _add(t)),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: Text(
                '🆓 freeleech · ✔️ snatched · ✅ downloaded · ⏬ downloading · 📥 added before',
                style: TextStyle(fontSize: 12),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// One release: status icon, name, tech line, seeders/leechers/snatches.
class ReleaseRow extends StatelessWidget {
  const ReleaseRow({
    required this.release,
    required this.onTap,
    super.key,
    this.dense = false,
  });
  final Release release;
  final VoidCallback onTap;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final t = release;
    final theme = Theme.of(context);
    final local = t.local;
    final tech = [
      if (t.episode.isNotEmpty) t.episode,
      if (t.resolution.isNotEmpty)
        t.resolution
      else
        t.container.isNotEmpty ? t.container : '?',
      if (t.codec.isNotEmpty) t.codec,
      fmtSize(t.size),
    ].join(' · ');
    final stats = [
      '🌱 ${t.seeders}',
      '🩸 ${t.leechers}',
      '⏬ ${t.snatches}',
      if (t.subs.isNotEmpty) '💬 ${t.subs}',
    ].join(' · ');
    return ListTile(
      dense: dense,
      leading: Tooltip(
        message: local?.label ?? 'Add to qBittorrent',
        child: Text(local?.mark ?? '⬇️', style: const TextStyle(fontSize: 20)),
      ),
      title: Text(tech, style: theme.textTheme.titleSmall),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            t.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
          ),
          Text(stats, style: theme.textTheme.bodySmall),
        ],
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (t.free) const Text('🆓'),
          if (t.snatched) const Text('✔️'),
        ],
      ),
      isThreeLine: true,
      onTap: onTap,
    );
  }
}
