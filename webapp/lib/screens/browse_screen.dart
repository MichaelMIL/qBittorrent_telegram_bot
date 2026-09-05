import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/main.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/common.dart';
import 'package:qbit_web/widgets/group_grid.dart';

/// The categories of the HeBits "newest uploads" feed, in tab order.
const browseCats = [('series', 'Series'), ('movies', 'Movies')];

/// Everything one category tab remembers, so switching tabs keeps the page,
/// the groups and (via the kept-alive grid) the scroll offset.
class _CatState {
  BrowsePage? data; // null until the first success
  int requested = 1; // page the user is on / asked for — drives the pager
  bool busy = false; // a request is in flight (load, page change or refresh)
  String? error; // ApiException.message, verbatim
  int seq = 0; // monotonic request sequence — stale-response guard
  bool started = false; // first load fired for this category
  String? genre; // active genre tag filter (server-side), null = all
  List<Genre> genres = const []; // last genre list the server sent
}

/// Newest uploads on HeBits, paged, one tab per category.
class BrowseScreen extends StatefulWidget {
  const BrowseScreen({super.key});

  @override
  State<BrowseScreen> createState() => _BrowseScreenState();
}

class _BrowseScreenState extends State<BrowseScreen> {
  String _cat = 'series';
  final Map<String, _CatState> _state = {
    for (final (id, _) in browseCats) id: _CatState(),
  };

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // The shell keeps every screen mounted; only fetch once we are visible.
    if (TickerMode.valuesOf(context).enabled) _ensureLoaded(_cat);
  }

  void _ensureLoaded(String cat) {
    final s = _state[cat]!;
    if (s.started) return;
    s.started = true;
    unawaited(_load(cat));
  }

  Future<void> _load(String cat, {int? page}) async {
    final s = _state[cat]!;
    final target = page ?? s.requested; // refresh/retry reuse the current page
    final token = ++s.seq;
    setState(() {
      s
        ..requested = target
        ..busy = true
        ..error = null;
    });
    try {
      final json = await AppScope.read(context).api.get('/api/browse', {
        'cat': cat,
        'page': '$target',
        'genre': s.genre,
      });
      if (!mounted) return;
      if (token != s.seq) return;
      final parsed = BrowsePage.fromJson(json);
      setState(() {
        s
          ..data = parsed
          ..requested = parsed.page;
        if (parsed.genres.isNotEmpty) s.genres = parsed.genres;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (token != s.seq) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      setState(() => s.error = e.message);
    } finally {
      if (mounted && token == s.seq) setState(() => s.busy = false);
    }
  }

  /// Pick a genre for the current tab (server-side filter); null = all.
  Future<void> _pickGenre() async {
    final s = _state[_cat]!;
    final genres = s.genres;
    final choice = await showModalBottomSheet<String>(
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
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                'Genre',
                style: Theme.of(ctx).textTheme.titleMedium,
              ),
            ),
            ListTile(
              leading: const Icon(Icons.all_inclusive),
              title: const Text('All genres'),
              selected: s.genre == null,
              onTap: () => Navigator.pop(ctx, ''),
            ),
            for (final g in genres)
              ListTile(
                leading: const Icon(Icons.label_outline),
                title: Text(g.label),
                subtitle: Text(g.tag),
                selected: s.genre == g.tag,
                onTap: () => Navigator.pop(ctx, g.tag),
              ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;
    final genre = choice.isEmpty ? null : choice;
    if (genre == s.genre) return;
    s.genre = genre;
    await _load(_cat, page: 1);
  }

  @override
  Widget build(BuildContext context) {
    final cur = _state[_cat]!;
    final data = cur.data;
    final genreLabel = cur.genre == null
        ? null
        : cur.genres
                  .where((g) => g.tag == cur.genre)
                  .map((g) => g.label)
                  .firstOrNull ??
              cur.genre;
    return Scaffold(
      appBar: AppBar(
        title: Text(genreLabel == null ? '🆕 New on HeBits' : '🆕 $genreLabel'),
        actions: [
          IconButton(
            tooltip: 'Filter by genre',
            icon: Icon(
              cur.genre == null ? Icons.filter_list : Icons.filter_list_alt,
              color: cur.genre == null
                  ? null
                  : Theme.of(context).colorScheme.primary,
            ),
            onPressed: cur.genres.isEmpty ? null : _pickGenre,
          ),
          IconButton(
            tooltip: 'Search HeBits',
            icon: const Icon(Icons.search),
            onPressed: () => ShellNav.maybeOf(context)?.goTo('Search'),
          ),
          IconButton(
            tooltip: 'Reload',
            icon: cur.busy
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh),
            onPressed: cur.busy ? null : () => _load(_cat),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(56),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
            child: Row(
              children: [
                Flexible(
                  child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: SegmentedButton<String>(
                      segments: [
                        for (final (id, label) in browseCats)
                          ButtonSegment(
                            value: id,
                            label: Text(label, maxLines: 1, softWrap: false),
                          ),
                      ],
                      selected: {_cat},
                      showSelectedIcon: false,
                      style: const ButtonStyle(
                        visualDensity: VisualDensity.compact,
                        padding: WidgetStatePropertyAll(
                          EdgeInsets.symmetric(horizontal: 10),
                        ),
                      ),
                      onSelectionChanged: (sel) {
                        setState(() => _cat = sel.first);
                        _ensureLoaded(_cat);
                      },
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                if (data != null && data.pages > 1)
                  Pager(
                    page: cur.requested,
                    pages: data.pages,
                    onPage: (p) => _load(_cat, page: p),
                  ),
              ],
            ),
          ),
        ),
      ),
      body: IndexedStack(
        index: browseCats.indexWhere((c) => c.$1 == _cat),
        children: [
          for (final (id, _) in browseCats)
            TickerMode(enabled: id == _cat, child: _body(id)),
        ],
      ),
    );
  }

  Widget _body(String cat) {
    final s = _state[cat]!;
    final data = s.data;
    if (s.error != null) {
      return EmptyView(
        icon: Icons.error_outline,
        text: s.error!,
        onRetry: () => _load(cat),
      );
    }
    if (data == null) return const Center(child: CircularProgressIndicator());
    if (data.groups.isEmpty) {
      return EmptyView(
        icon: Icons.inbox_outlined,
        text: s.genre == null
            ? 'HeBits had nothing new on page ${data.page}.'
            : 'Nothing in this genre on page ${data.page}.',
        onRetry: () => _load(cat),
        retryLabel: 'Reload',
      );
    }
    return RefreshIndicator(
      onRefresh: () => _load(cat),
      child: GroupGrid(
        groups: data.groups,
        onChanged: () => setState(() {}),
        // Short pages must still scroll or pull-to-refresh does nothing.
        physics: const AlwaysScrollableScrollPhysics(),
      ),
    );
  }
}
