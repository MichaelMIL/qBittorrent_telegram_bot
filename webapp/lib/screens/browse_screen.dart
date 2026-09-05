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

/// How close to the bottom (in pixels) the user must scroll before the next
/// page is requested.
const _loadMoreThreshold = 600.0;

/// Everything one category tab remembers, so switching tabs keeps the feed,
/// the genre filter and (via the kept-alive grid) the scroll offset.
class _CatState {
  final List<Group> groups = []; // pages 1..loaded, appended in order
  int loaded = 0; // pages fetched so far (0 = nothing yet)
  int pages = 1; // total pages the server reported
  bool busy = false; // a request is in flight
  int fetching = 0; // page of the request in flight (0 = none)
  String? error; // ApiException.message, verbatim
  int seq = 0; // monotonic request sequence — stale-response guard
  bool started = false; // first load fired for this category
  String? genre; // active genre tag filter (server-side), null = all
  List<Genre> genres = const []; // last genre list the server sent
  final ScrollController scroll = ScrollController();

  bool get hasMore => loaded < pages;
}

/// Newest uploads on HeBits, one tab per category, filtered by genre, loading
/// the next page automatically as the user nears the bottom.
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

  @override
  void dispose() {
    for (final s in _state.values) {
      s.scroll.dispose();
    }
    super.dispose();
  }

  void _ensureLoaded(String cat) {
    final s = _state[cat]!;
    if (s.started) return;
    s.started = true;
    unawaited(_refresh(cat));
  }

  /// Start over from page 1 (first load, reload, pull-to-refresh, new genre).
  Future<void> _refresh(String cat) => _fetch(cat, page: 1);

  /// Fetch the page after the last loaded one, if there is one.
  Future<void> _loadMore(String cat, {bool retry = false}) async {
    final s = _state[cat]!;
    // after a failed load-more, only the footer's Retry asks again (scrolling
    // would otherwise hammer a dead server)
    if (s.busy || !s.hasMore || (s.error != null && !retry)) return;
    await _fetch(cat, page: s.loaded + 1);
  }

  Future<void> _fetch(String cat, {required int page}) async {
    final s = _state[cat]!;
    final token = ++s.seq;
    setState(() {
      s
        ..busy = true
        ..fetching = page
        ..error = null;
    });
    try {
      final json = await AppScope.read(context).api.get('/api/browse', {
        'cat': cat,
        'page': '$page',
        'genre': s.genre,
      });
      if (!mounted || token != s.seq) return;
      final parsed = BrowsePage.fromJson(json);
      // a fresh feed starts at the top (reload, pull-to-refresh, new genre)
      if (page == 1 && s.scroll.hasClients) s.scroll.jumpTo(0);
      setState(() {
        if (page == 1) s.groups.clear();
        s.groups.addAll(parsed.groups);
        s
          ..loaded = parsed.current
          ..pages = parsed.pageCount;
        if (parsed.genres.isNotEmpty) s.genres = parsed.genres;
      });
      // A short page (few tiles, big screen, narrow genre) never scrolls, so
      // the scroll trigger would never fire: keep loading until it can.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || cat != _cat || !s.scroll.hasClients) return;
        final pos = s.scroll.position;
        if (pos.maxScrollExtent - pos.pixels < _loadMoreThreshold) {
          unawaited(_loadMore(cat));
        }
      });
    } on ApiException catch (e) {
      if (!mounted || token != s.seq) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      setState(() => s.error = e.message);
    } finally {
      if (mounted && token == s.seq) {
        setState(() {
          s
            ..busy = false
            ..fetching = 0;
        });
      }
    }
  }

  bool _onScroll(String cat, ScrollNotification n) {
    if (n.metrics.axis != Axis.vertical) return false;
    final remaining = n.metrics.maxScrollExtent - n.metrics.pixels;
    if (remaining < _loadMoreThreshold) unawaited(_loadMore(cat));
    return false;
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
              child: Text('Genre', style: Theme.of(ctx).textTheme.titleMedium),
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
    if (s.scroll.hasClients) s.scroll.jumpTo(0);
    await _refresh(_cat);
  }

  @override
  Widget build(BuildContext context) {
    final cur = _state[_cat]!;
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
            onPressed: () => _refresh(_cat),
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
                if (cur.loaded > 0)
                  Text(
                    '${cur.groups.length} titles'
                    '${cur.hasMore ? '' : ' · all'}',
                    style: Theme.of(context).textTheme.bodySmall,
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
    if (s.groups.isEmpty) {
      // nothing to show yet: full-screen states
      if (s.error != null) {
        return EmptyView(
          icon: Icons.error_outline,
          text: s.error!,
          onRetry: () => _refresh(cat),
        );
      }
      if (s.busy || s.loaded == 0) {
        return const Center(child: CircularProgressIndicator());
      }
      return EmptyView(
        icon: Icons.inbox_outlined,
        text: s.genre == null
            ? 'HeBits had nothing new here.'
            : 'Nothing in this genre.',
        onRetry: () => _refresh(cat),
        retryLabel: 'Reload',
      );
    }
    final Widget footer;
    if (s.error != null) {
      footer = Column(
        children: [
          Text(
            s.error!,
            textAlign: TextAlign.center,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
          const SizedBox(height: 8),
          FilledButton.tonal(
            onPressed: () => _loadMore(cat, retry: true),
            child: const Text('Retry'),
          ),
        ],
      );
    } else if (s.busy && s.fetching > 1) {
      footer = const Center(
        child: Padding(
          padding: EdgeInsets.all(16),
          child: CircularProgressIndicator(),
        ),
      );
    } else if (s.hasMore) {
      footer = const SizedBox(height: 48); // room for the scroll trigger
    } else {
      footer = Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          "That's everything — ${s.groups.length} titles.",
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: () => _refresh(cat),
      child: NotificationListener<ScrollNotification>(
        onNotification: (n) => _onScroll(cat, n),
        child: GroupGrid(
          groups: s.groups,
          controller: s.scroll,
          onChanged: () => setState(() {}),
          footer: footer,
          // Short pages must still scroll or pull-to-refresh does nothing.
          physics: const AlwaysScrollableScrollPhysics(),
        ),
      ),
    );
  }
}
