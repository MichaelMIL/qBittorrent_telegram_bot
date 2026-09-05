import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/main.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/add_flow.dart';
import 'package:qbit_web/widgets/common.dart';
import 'package:qbit_web/widgets/group_grid.dart';

const searchFilters = [('a', 'All'), ('1', 'Movies'), ('2', 'Series')];

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _controller = TextEditingController();
  String _cat = 'a';
  SearchPage? _page;
  bool _loading = false;
  String? _error;

  Future<void> _search({String? query, String? cat, int page = 1}) async {
    final q = (query ?? _controller.text).trim();
    if (q.isEmpty) return;
    _controller.text = q;
    setState(() {
      _loading = true;
      _error = null;
      _cat = cat ?? _cat;
    });
    try {
      final data = await AppScope.read(context).api.get('/api/search', {
        'q': q,
        'cat': _cat,
        'page': '$page',
      });
      if (!mounted) return;
      setState(() => _page = SearchPage.fromJson(data));
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final page = _page;
    return Scaffold(
      appBar: AppBar(
        title: TextField(
          controller: _controller,
          textInputAction: TextInputAction.search,
          onSubmitted: (_) => _search(),
          decoration: InputDecoration(
            hintText: 'Search HeBits…',
            border: InputBorder.none,
            suffixIcon: _controller.text.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.clear),
                    onPressed: () => setState(() {
                      _controller.clear();
                      _page = null;
                      _error = null;
                    }),
                  ),
          ),
          onChanged: (_) => setState(() {}),
        ),
        actions: [
          if (AppScope.of(context).can('browse'))
            IconButton(
              tooltip: 'New on HeBits',
              icon: const Icon(Icons.explore_outlined),
              onPressed: () => ShellNav.maybeOf(context)?.goTo('Browse'),
            ),
          IconButton(
            tooltip: 'Search',
            icon: const Icon(Icons.search),
            onPressed: _search,
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
                        for (final (id, label) in searchFilters)
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
                      onSelectionChanged: (s) {
                        final cat = s.first;
                        if (page != null) {
                          unawaited(_search(cat: cat));
                        } else {
                          setState(() => _cat = cat);
                        }
                      },
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                if (page != null && page.pages > 1)
                  Pager(
                    page: page.page,
                    pages: page.pages,
                    onPage: (p) => _search(page: p),
                  ),
              ],
            ),
          ),
        ),
      ),
      floatingActionButton: AppScope.of(context).can('add')
          ? FloatingActionButton.extended(
              heroTag: 'search-add',
              onPressed: () => addManually(context),
              icon: const Icon(Icons.add),
              label: const Text('Magnet / .torrent'),
            )
          : null,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? EmptyView(
              icon: Icons.error_outline,
              text: _error!,
              onRetry: () => _search(page: page?.page ?? 1),
            )
          : page == null
          ? const EmptyView(
              icon: Icons.travel_explore,
              text:
                  'Type a name (try “fauda”) to search HeBits.\n\n'
                  'Markers: 🆓 freeleech · ✔️ snatched · ✅ downloaded · '
                  '⏬ downloading · 📥 added before',
            )
          : page.groups.isEmpty
          ? EmptyView(
              icon: Icons.search_off,
              text: 'No results on HeBits for “${page.query}”.',
            )
          : GroupGrid(
              groups: page.groups,
              onChanged: () => setState(() {}),
            ),
    );
  }
}
