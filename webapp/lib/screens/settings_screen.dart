import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/format.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/screens/plex_screen.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/common.dart';

/// Status, tunables (applied immediately, persisted by the backend),
/// category → Plex library map, HeBits cookie, maintenance actions.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  AppSettings? _settings;
  Map<String, List<int>> _choices = {};
  String? _error;
  List<String>? _categories;
  List<PlexSection>? _sections;
  String? _sectionsError;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    final state = AppScope.read(context);
    unawaited(state.refreshStatus());
    try {
      final data = await state.api.get('/api/settings');
      if (!mounted) return;
      setState(() {
        _settings = AppSettings.fromJson(jsonMap(data['settings']));
        _choices = {
          for (final e in jsonMap(data['choices']).entries)
            e.key: [for (final v in e.value as List) v as int],
        };
        _error = null;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(state.connect());
      setState(() => _error = e.message);
    }
  }

  Future<void> _loadPlexMapData() async {
    final api = AppScope.read(context).api;
    try {
      final cats = await api.get('/api/categories');
      if (mounted) {
        setState(
          () => _categories = [
            for (final c in (cats['categories'] as List)) '$c',
          ],
        );
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _sectionsError = e.message);
    }
    try {
      final secs = await api.get('/api/plex/sections');
      if (mounted) {
        setState(() {
          _sections = [
            for (final s in jsonList(secs['sections'])) PlexSection.fromJson(s),
          ];
          _sectionsError = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _sectionsError = e.message);
    }
  }

  Future<void> _set(String key, dynamic value) async {
    final data = await guard(
      context,
      () => AppScope.read(
        context,
      ).api.patch('/api/settings', {'key': key, 'value': value}),
    );
    if (data != null && mounted) {
      setState(
        () => _settings = AppSettings.fromJson(jsonMap(data['settings'])),
      );
      unawaited(AppScope.read(context).refreshStatus());
    }
  }

  Future<void> _run(
    String label,
    Future<String> Function(ApiClient api) fn,
  ) async {
    setState(() => _busy = true);
    showSnack(context, '⏳ $label…');
    final msg = await guard(context, () => fn(AppScope.read(context).api));
    if (!mounted) return;
    setState(() => _busy = false);
    if (msg != null) showSnack(context, msg);
    unawaited(AppScope.read(context).refreshStatus());
  }

  Future<void> _updateCookie() async {
    final cookie = await promptText(
      context,
      title: '🍪 HeBits cookie',
      hint:
          'Paste the whole Cookie request header from DevTools → Network → any hebits.net request',
      multiline: true,
      confirm: 'Validate & save',
    );
    if (cookie == null) return;
    await _run('Validating the cookie', (api) async {
      final r = await api.put('/api/cookie', {'cookie': cookie});
      return '✅ Cookie saved — logged in as “${r['user']}”.';
    });
  }

  Future<void> _clearCache() async {
    await _run('Clearing the server cache', (api) async {
      final r = await api.post('/api/cache/clear');
      final cleared = jsonMap(r['cleared']);
      // the browser keeps its own copy of the posters — drop that too
      PaintingBinding.instance.imageCache
        ..clear()
        ..clearLiveImages();
      return '🗑 Cache cleared — ${cleared['covers']} posters, '
          '${fmtSize(_int(cleared['bytes']))}.';
    });
  }

  static int _int(dynamic v) => v is num ? v.round() : 0;

  static String _cacheSubtitle(Status? status) {
    if (status == null) return '';
    final every = status.cacheClearEveryHours;
    final period = every >= 24 && every % 24 == 0
        ? '${(every / 24).round()} d'
        : '${every.toStringAsFixed(0)} h';
    final parts = <String>[
      if (status.cacheMaxBytes > 0) 'limit ${fmtSize(status.cacheMaxBytes)}',
      if (every > 0)
        'cleared every $period'
      else
        'no automatic clearing (CACHE_CLEAR_HOURS=0)',
      if (status.cacheClearedAt != null)
        'last cleared ${fmtAgo(status.cacheClearedAt!)}',
    ];
    return parts.join(' · ');
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    if (!state.settingsUnlocked) return const _LockedView();
    final status = state.status;
    final s = _settings;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('⚙️ Settings'),
        actions: [
          if (state.settingsLocked)
            IconButton(
              tooltip: 'Lock settings',
              icon: const Icon(Icons.lock_outline),
              onPressed: state.lockSettings,
            ),
          IconButton(
            tooltip: 'Reload',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: s == null
          ? (_error != null
                ? EmptyView(
                    icon: Icons.error_outline,
                    text: _error!,
                    onRetry: _load,
                  )
                : const Center(child: CircularProgressIndicator()))
          : Constrained(
              maxWidth: 760,
              child: ListView(
                padding: const EdgeInsets.only(bottom: 32),
                children: [
                  const SectionTitle('Status'),
                  if (status != null)
                    Card(
                      margin: const EdgeInsets.symmetric(horizontal: 16),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _fact(
                              '🗄 qBittorrent snapshot',
                              status.snapshotTorrents == null
                                  ? 'no snapshot yet'
                                  : '${status.snapshotTorrents} torrents · updated ${fmtAgo(status.snapshotUpdated!)}',
                            ),
                            _fact('⭐ Favorites', '${status.favorites}'),
                            _fact(
                              '🧾 Torrents added on record',
                              '${status.history}',
                            ),
                            _fact(
                              '🔔 Downloads being watched',
                              '${status.watches}',
                            ),
                            _fact(
                              '📌 Series with a default',
                              '${status.defaults}',
                            ),
                            _fact(
                              '🍪 HeBits cookie',
                              status.cookieConfigured
                                  ? 'configured'
                                  : '❗ not set',
                            ),
                            _fact(
                              '🎞 Plex',
                              '${status.plexUrl} · ${status.plexAuth == 'token' ? 'token' : 'LAN no-auth'}',
                            ),
                            _fact('⬇️ qBittorrent', status.qbit),
                            _fact(
                              '✈️ Telegram bot',
                              status.telegram
                                  ? 'configured'
                                  : 'not configured (web only)',
                            ),
                          ],
                        ),
                      ),
                    ),

                  const SectionTitle('🗂 Server cache'),
                  ListTile(
                    leading: const Icon(Icons.image_outlined),
                    title: Text(
                      status == null
                          ? 'Poster cache'
                          : '${status.cacheCovers} posters · '
                                '${fmtSize(status.cacheBytes)} on disk',
                    ),
                    subtitle: Text(_cacheSubtitle(status)),
                    trailing: FilledButton.tonalIcon(
                      icon: const Icon(Icons.delete_sweep_outlined),
                      label: const Text('Clear cache'),
                      onPressed: _busy ? null : _clearCache,
                    ),
                  ),

                  const SectionTitle('🎛 Tunables'),
                  _picker(
                    icon: '🗄',
                    title: 'qBittorrent refresh',
                    subtitle:
                        'Snapshot used for search markers when qBittorrent is unreachable',
                    key: 'qbit_refresh_hours',
                    value: s.qbitRefreshHours,
                    fmt: (v) => '$v h',
                  ),
                  _picker(
                    icon: '⭐',
                    title: 'Episode check',
                    subtitle:
                        'How often favorites are checked for new episodes',
                    key: 'fav_check_hours',
                    value: s.favCheckHours,
                    fmt: (v) => '$v h',
                  ),
                  _picker(
                    icon: '🔔',
                    title: 'Completion check',
                    subtitle: 'Polling frequency for watched downloads',
                    key: 'watch_poll_seconds',
                    value: s.watchPollSeconds,
                    fmt: (v) => '$v s',
                  ),
                  _picker(
                    icon: '🐌',
                    title: 'Stuck-download alert',
                    subtitle:
                        'Warn when a watched download is stalled this long',
                    key: 'stall_alert_hours',
                    value: s.stallAlertHours,
                    fmt: (v) => v == 0 ? 'off' : 'after $v h',
                  ),
                  SwitchListTile(
                    secondary: const Text('🎞', style: TextStyle(fontSize: 22)),
                    title: const Text('Auto-scan Plex after downloads'),
                    subtitle: Text(
                      s.autoPlexScan
                          ? 'On — the mapped library is scanned when a download finishes'
                          : 'Off — completion pings get a “Scan Plex” button instead',
                    ),
                    value: s.autoPlexScan,
                    onChanged: (v) => _set('auto_plex_scan', v),
                  ),
                  ExpansionTile(
                    leading: const Text(
                      '📁→🎞',
                      style: TextStyle(fontSize: 16),
                    ),
                    title: const Text('Category → Plex library map'),
                    subtitle: Text(
                      s.plexMap.isEmpty
                          ? 'Unmapped categories scan all libraries'
                          : '${s.plexMap.length} mapped',
                    ),
                    onExpansionChanged: (open) {
                      if (open && _categories == null) {
                        unawaited(_loadPlexMapData());
                      }
                    },
                    children: [
                      if (_sectionsError != null)
                        Padding(
                          padding: const EdgeInsets.all(16),
                          child: Text(
                            '⚠️ $_sectionsError',
                            style: TextStyle(color: theme.colorScheme.error),
                          ),
                        ),
                      if (_categories == null && _sectionsError == null)
                        const Padding(
                          padding: EdgeInsets.all(16),
                          child: LinearProgressIndicator(),
                        ),
                      if (_categories != null && _categories!.isEmpty)
                        const ListTile(
                          title: Text(
                            'No categories defined in qBittorrent yet.',
                          ),
                        ),
                      if (_categories != null && _sections != null)
                        for (final cat in _categories!)
                          ListTile(
                            leading: const Icon(Icons.folder_outlined),
                            title: Text(cat),
                            trailing: DropdownButton<String>(
                              value:
                                  _sections!.any((x) => x.key == s.plexMap[cat])
                                  ? s.plexMap[cat]
                                  : '',
                              items: [
                                const DropdownMenuItem(
                                  value: '',
                                  child: Text('🌐 all libraries'),
                                ),
                                for (final sec in _sections!)
                                  DropdownMenuItem(
                                    value: sec.key,
                                    child: Text(sec.label),
                                  ),
                              ],
                              onChanged: (v) =>
                                  _set('plex_map', {cat: v == '' ? null : v}),
                            ),
                          ),
                    ],
                  ),

                  const SectionTitle('🧰 Maintenance'),
                  ListTile(
                    leading: const Icon(Icons.sync),
                    title: const Text('Refresh qBittorrent list'),
                    subtitle: const Text('Re-read the torrent snapshot now'),
                    enabled: !_busy,
                    onTap: () => _run('Refreshing the qBittorrent list', (
                      api,
                    ) async {
                      final r = await api.post('/api/refresh');
                      return '✅ Refreshed — ${r['torrents']} torrents, ${r['completed']} completed.';
                    }),
                  ),
                  ListTile(
                    leading: const Icon(Icons.new_releases_outlined),
                    title: const Text('Check favorites for episodes'),
                    enabled: !_busy,
                    onTap: () => _run('Checking favorites', (api) async {
                      final r = await api.post('/api/favorites/check');
                      final n = (r['notifications'] as List).length;
                      return n == 0
                          ? '✅ No new episodes for your favorites.'
                          : '🆕 $n new-episode notification(s) — see Activity.';
                    }),
                  ),
                  ListTile(
                    leading: const Icon(Icons.movie_filter_outlined),
                    title: const Text('Plex libraries'),
                    subtitle: const Text('Scan a library, or all of them'),
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => const PlexScreen(),
                      ),
                    ),
                  ),
                  ListTile(
                    leading: const Icon(Icons.cookie_outlined),
                    title: const Text('Validate HeBits cookie'),
                    enabled: !_busy,
                    onTap: () => _run('Validating the HeBits cookie', (
                      api,
                    ) async {
                      final r = await api.get('/api/cookie');
                      if (r['configured'] != true) {
                        return '❌ No HeBits cookie configured — update it below.';
                      }
                      return r['valid'] == true
                          ? '✅ Cookie valid — logged in as “${r['user']}”.'
                          : '❌ The stored cookie no longer works — log in with a browser and update it.';
                    }),
                  ),
                  ListTile(
                    leading: const Icon(Icons.edit_note),
                    title: const Text('Update HeBits cookie'),
                    subtitle: const Text(
                      'Paste the Cookie header from your logged-in browser',
                    ),
                    enabled: !_busy,
                    onTap: _updateCookie,
                  ),

                  const SectionTitle('🔌 Connection'),
                  ListTile(
                    leading: const Icon(Icons.dns_outlined),
                    title: Text(state.api.baseUrl),
                    subtitle: Text(
                      '${state.authRequired ? 'Password protected' : 'No password set (WEB_PASSWORD)'}'
                      ' · settings lock ${state.settingsLocked ? 'on (SETTINGS_PASSWORD)' : 'off (SETTINGS_PASSWORD empty)'}',
                    ),
                    trailing: TextButton(
                      onPressed: () async {
                        await state.logout();
                      },
                      child: Text(
                        state.authRequired ? 'Log out' : 'Change server',
                      ),
                    ),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _fact(String k, String v) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(flex: 2, child: Text(k)),
        const SizedBox(width: 12),
        Expanded(
          flex: 3,
          child: Text(
            v,
            textAlign: TextAlign.end,
            style: const TextStyle(fontWeight: FontWeight.w500),
          ),
        ),
      ],
    ),
  );

  Widget _picker({
    required String icon,
    required String title,
    required String subtitle,
    required String key,
    required int value,
    required String Function(int) fmt,
  }) {
    final choices = _choices[key] ?? [value];
    return ListTile(
      leading: Text(icon, style: const TextStyle(fontSize: 22)),
      title: Text(title),
      subtitle: Text(subtitle),
      trailing: DropdownButton<int>(
        value: choices.contains(value) ? value : null,
        hint: Text(fmt(value)),
        items: [
          for (final c in choices)
            DropdownMenuItem(value: c, child: Text(fmt(c))),
        ],
        onChanged: (v) => v == null ? null : _set(key, v),
      ),
    );
  }
}

/// Shown instead of the settings while SETTINGS_PASSWORD hasn't been entered
/// in this session.
class _LockedView extends StatefulWidget {
  const _LockedView();

  @override
  State<_LockedView> createState() => _LockedViewState();
}

class _LockedViewState extends State<_LockedView> {
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  Future<void> _unlock() async {
    final state = AppScope.read(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await state.unlockSettings(_password.text);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('⚙️ Settings')),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Icon(Icons.lock_outline, size: 40),
                    const SizedBox(height: 12),
                    Text(
                      'Settings are locked',
                      style: Theme.of(context).textTheme.titleLarge,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Enter the settings password (SETTINGS_PASSWORD in the '
                      "server's .env). It is asked once per session.",
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 20),
                    TextField(
                      controller: _password,
                      obscureText: true,
                      autofocus: true,
                      onSubmitted: (_) => _unlock(),
                      decoration: const InputDecoration(
                        labelText: 'Settings password',
                        prefixIcon: Icon(Icons.key_outlined),
                        border: OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: _busy ? null : _unlock,
                      icon: _busy
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.lock_open),
                      label: const Text('Unlock'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
