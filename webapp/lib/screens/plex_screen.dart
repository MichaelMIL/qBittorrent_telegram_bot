import 'dart:async';

import 'package:flutter/material.dart';

import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/common.dart';

/// Plex libraries with one-tap scans; polls while any library is refreshing.
class PlexScreen extends StatefulWidget {
  const PlexScreen({super.key});

  @override
  State<PlexScreen> createState() => _PlexScreenState();
}

class _PlexScreenState extends State<PlexScreen> {
  List<PlexSection>? _sections;
  String? _error;
  Timer? _timer;
  final Map<String, DateTime> _started = {};

  @override
  void initState() {
    super.initState();
    unawaited(_load());
    _timer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (_sections?.any((s) => s.refreshing) ?? false) {
        unawaited(_load(silent: true));
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    try {
      final data = await AppScope.read(context).api.get('/api/plex/sections');
      if (!mounted) return;
      final sections = [
        for (final s in jsonList(data['sections'])) PlexSection.fromJson(s),
      ];
      // announce finished scans we started from here
      for (final s in sections) {
        final started = _started[s.key];
        if (started != null && !s.refreshing) {
          _started.remove(s.key);
          final secs = DateTime.now().difference(started).inSeconds;
          showSnack(context, '✅ Plex finished scanning ${s.label} (${secs}s).');
        }
      }
      setState(() {
        _sections = sections;
        _error = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      if (!silent || _sections == null) setState(() => _error = e.message);
    }
  }

  Future<void> _scan({List<String> keys = const [], bool all = false}) async {
    final data = await guard(
      context,
      () => AppScope.read(
        context,
      ).api.post('/api/plex/scan', {'keys': keys, 'all': all}),
    );
    if (data == null || !mounted) return;
    final targets = [
      for (final s in jsonList(data['scanning'])) PlexSection.fromJson(s),
    ];
    for (final s in targets) {
      _started[s.key] = DateTime.now();
    }
    showSnack(
      context,
      '🔍 Plex is scanning ${targets.map((s) => s.label).join(', ')}…',
    );
    unawaited(
      Future<void>.delayed(const Duration(seconds: 2), () {
        if (mounted) unawaited(_load(silent: true));
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sections = _sections;
    return Scaffold(
      appBar: AppBar(
        title: const Text('🎞 Plex libraries'),
        actions: [
          IconButton(
            tooltip: 'Reload',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      floatingActionButton: sections == null || sections.isEmpty
          ? null
          : FloatingActionButton.extended(
              heroTag: 'plex-all',
              onPressed: () => _scan(all: true),
              icon: const Icon(Icons.refresh),
              label: const Text('Scan all'),
            ),
      body: sections == null
          ? (_error != null
                ? EmptyView(
                    icon: Icons.error_outline,
                    text: _error!,
                    onRetry: _load,
                  )
                : const Center(child: CircularProgressIndicator()))
          : sections.isEmpty
          ? const EmptyView(
              icon: Icons.video_library_outlined,
              text: 'No libraries found.',
            )
          : Constrained(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 88, top: 4),
                children: [
                  const Padding(
                    padding: EdgeInsets.fromLTRB(16, 8, 16, 4),
                    child: Text(
                      'Tap a library to scan it for new files.',
                      style: TextStyle(fontSize: 12),
                    ),
                  ),
                  for (final s in sections)
                    ListTile(
                      leading: Text(
                        s.icon,
                        style: const TextStyle(fontSize: 22),
                      ),
                      title: Text(s.title),
                      subtitle: Text(s.refreshing ? '⏳ scanning…' : s.type),
                      trailing: s.refreshing
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.search),
                      onTap: () => _scan(keys: [s.key]),
                    ),
                ],
              ),
            ),
    );
  }
}
