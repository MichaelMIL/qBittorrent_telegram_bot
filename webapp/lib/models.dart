// Plain data classes mirroring the API's JSON.

import 'package:qbit_web/api/client.dart';

/// Typed view of a nested JSON object (empty when absent or not an object).
Json jsonMap(dynamic v) => v is Map ? Json.from(v) : <String, dynamic>{};

/// Typed view of a JSON array of objects (non-objects are dropped).
List<Json> jsonList(dynamic v) => [
  if (v is List)
    for (final e in v)
      if (e is Map) Json.from(e),
];

/// A JSON array rendered as strings.
List<String> stringList(dynamic v) => [
  if (v is List)
    for (final e in v) _str(e),
];

int _int(dynamic v) =>
    v is int ? v : (v is num ? v.round() : int.tryParse('$v') ?? 0);
double _double(dynamic v) =>
    v is num ? v.toDouble() : double.tryParse('$v') ?? 0;
String _str(dynamic v) => v == null ? '' : '$v';

/// Where a HeBits release stands in qBittorrent (see decorate_local_status).
class LocalStatus {
  LocalStatus(this.status, this.progress);
  final String status; // done | dl | gone | hist
  final double progress;

  static LocalStatus? from(dynamic j) =>
      j is Map ? LocalStatus(_str(j['status']), _double(j['progress'])) : null;

  String get mark => switch (status) {
    'done' => '✅',
    'dl' => '⏬${(progress * 100).round()}%',
    _ => '📥',
  };

  String get label => switch (status) {
    'done' => 'Downloaded',
    'dl' => 'Downloading ${(progress * 100).round()}%',
    'gone' => 'Added before, gone from qBittorrent',
    _ => 'Added before',
  };
}

class Release {
  Release.fromJson(Json j)
    : id = _int(j['id']),
      title = _str(j['title']),
      resolution = _str(j['resolution']),
      codec = _str(j['codec']),
      container = _str(j['container']),
      subs = _str(j['subs']),
      size = _int(j['size']),
      seeders = _int(j['seeders']),
      leechers = _int(j['leechers']),
      snatches = _int(j['snatches']),
      free = j['free'] == true,
      snatched = j['snatched'] == true,
      episode = _str(j['episode']),
      season = j['season'] is int ? j['season'] as int : -1,
      local = LocalStatus.from(j['local']);

  final int id;
  final String title;
  final String resolution;
  final String codec;
  final String container;
  final String subs;
  final String episode;
  final int size;
  final int seeders;
  final int leechers;
  final int snatches;
  final int season;
  final bool free;
  final bool snatched;
  final LocalStatus? local;
}

class SeriesDefault {
  SeriesDefault({
    required this.name,
    required this.category,
    this.tag,
    this.resolution,
  });
  SeriesDefault.fromJson(Json j)
    : name = _str(j['name']),
      tag = j['tag'] == null ? null : _str(j['tag']),
      category = _str(j['category']),
      resolution = j['resolution'] == null ? null : _str(j['resolution']);

  final String name;
  final String? tag;
  final String category;
  final String? resolution;

  static SeriesDefault? maybe(dynamic j) =>
      j is Map ? SeriesDefault.fromJson(jsonMap(j)) : null;

  /// '🏷 tag + 📁 category + 📐 res' like the bot's default_label.
  String get label => [
    if (tag != null && tag!.isNotEmpty) '🏷 $tag',
    if (category.isNotEmpty) '📁 $category',
    if (resolution != null) '📐 $resolution',
  ].join(' + ');

  Map<String, dynamic> toJson() => {
    'name': name,
    'tag': tag,
    'category': category,
    'resolution': resolution,
  };
}

class Group {
  Group.fromJson(Json j)
    : gid = _str(j['gid']),
      nameEn = _str(j['name_en']),
      nameHe = _str(j['name_he']),
      year = _str(j['year']),
      cover = _str(j['cover']),
      imdb = _str(j['imdb']),
      cat = _str(j['cat']),
      torrents = [
        for (final t in jsonList(j['torrents'])) Release.fromJson(t),
      ],
      favorite = j['favorite'] == true,
      auto = j['auto'] == true,
      seriesDefault = SeriesDefault.maybe(j['default']);

  final String gid;
  final String nameEn;
  final String nameHe;
  final String year;
  final String cover;
  final String imdb;
  final String cat;
  final List<Release> torrents;
  bool favorite;
  bool auto;
  SeriesDefault? seriesDefault;

  String get title => nameEn.isNotEmpty
      ? nameEn
      : (nameHe.isNotEmpty ? nameHe : torrents.first.title);
  String get titleWithYear => year.isNotEmpty ? '$title ($year)' : title;
  String get query => nameEn.isNotEmpty ? nameEn : nameHe;
  bool get isSeries => torrents.any((t) => t.episode.isNotEmpty);

  /// Strongest qBittorrent status across the group's releases.
  LocalStatus? get bestLocal {
    for (final s in const ['done', 'dl', 'gone', 'hist']) {
      final hit = torrents.where((t) => t.local?.status == s);
      if (hit.isNotEmpty) return hit.first.local;
    }
    return null;
  }

  bool get anyFree => torrents.any((t) => t.free);
  bool get anySnatched => torrents.any((t) => t.snatched);
  int get totalSeeders => torrents.fold(0, (a, t) => a + t.seeders);
  List<String> get resolutions => ({
    for (final t in torrents)
      if (t.resolution.isNotEmpty) t.resolution,
  }.toList()..sort());
}

class SearchPage {
  SearchPage.fromJson(Json j)
    : query = _str(j['query']),
      cat = _str(j['cat']),
      page = _int(j['page']),
      pages = _int(j['pages']),
      groups = [
        for (final g in jsonList(j['groups'])) Group.fromJson(g),
      ];
  final String query;
  final String cat;
  final int page;
  final int pages;
  final List<Group> groups;
}

/// One page of the HeBits "newest uploads" feed (`GET /api/browse`).
///
/// Same group shape as [SearchPage]; the browse response carries no `query`.
/// A HeBits genre tag (Hebrew, as the site stores it) with an English label.
class Genre {
  Genre.fromJson(Json j) : tag = _str(j['tag']), label = _str(j['label']);
  final String tag;
  final String label;
}

class BrowsePage {
  BrowsePage.fromJson(Json j)
    : cat = _str(j['cat']),
      page = _int(j['page']),
      pages = _int(j['pages']),
      genre = j['genre'] == null ? null : _str(j['genre']),
      genres = [for (final g in jsonList(j['genres'])) Genre.fromJson(g)],
      groups = [
        for (final g in jsonList(j['groups'])) Group.fromJson(g),
      ];

  /// 'movies' | 'series', echoed back from the request.
  final String cat;
  final int page;
  final int pages;

  /// The genre tag this page was filtered by, or null for everything.
  final String? genre;

  /// Genres the server can filter by, in display order.
  final List<Genre> genres;
  final List<Group> groups;

  /// English label for [genre] (falls back to the tag itself).
  String? get genreLabel => genre == null
      ? null
      : genres.where((g) => g.tag == genre).map((g) => g.label).firstOrNull ??
            genre;

  /// The page we are on, never below 1 (a missing `page` coerces to 0).
  int get current => page < 1 ? 1 : page;

  /// Total pages, never below the page we are on and never below 1.
  int get pageCount => pages < current ? current : pages;

  bool get hasMore => current < pageCount;
}

class Torrent {
  Torrent.fromJson(Json j)
    : hash = _str(j['hash']),
      name = _str(j['name']),
      state = _str(j['state']),
      progress = _double(j['progress']),
      size = _int(j['size']),
      downloaded = _int(j['downloaded']),
      uploaded = _int(j['uploaded']),
      dlspeed = _int(j['dlspeed']),
      upspeed = _int(j['upspeed']),
      ratio = _double(j['ratio']),
      eta = _int(j['eta']),
      numSeeds = _int(j['num_seeds']),
      numLeechs = _int(j['num_leechs']),
      tags = stringList(j['tags']),
      category = _str(j['category']),
      addedOn = _int(j['added_on']),
      completionOn = _int(j['completion_on']),
      savePath = _str(j['save_path']);

  final String hash;
  final String name;
  final String state;
  final String category;
  final String savePath;
  final double progress;
  final double ratio;
  final int size;
  final int downloaded;
  final int uploaded;
  final int dlspeed;
  final int upspeed;
  final int eta;
  final int numSeeds;
  final int numLeechs;
  final int addedOn;
  final int completionOn;
  final List<String> tags;

  bool get paused =>
      const {'pausedDL', 'pausedUP', 'stoppedDL', 'stoppedUP'}.contains(state);
  bool get done => progress >= 1;
}

class Favorite {
  Favorite.fromJson(Json j)
    : gid = _str(j['gid']),
      name = _str(j['name']),
      query = _str(j['query']),
      auto = j['auto'] == true,
      lastEp = j['last_ep'] is List
          ? [for (final x in j['last_ep'] as List) _int(x)]
          : null,
      seriesDefault = SeriesDefault.maybe(j['default']);
  final String gid;
  final String name;
  final String query;
  final bool auto;
  final List<int>? lastEp;
  final SeriesDefault? seriesDefault;

  String? get lastEpLabel {
    final e = lastEp;
    if (e == null || e.length < 2) return null;
    final s = e[0].toString().padLeft(2, '0');
    return e[1] >= 999 ? 'S$s' : 'S${s}E${e[1].toString().padLeft(2, '0')}';
  }
}

class PlexSection {
  PlexSection.fromJson(Json j)
    : key = _str(j['key']),
      title = _str(j['title']),
      type = _str(j['type']),
      refreshing = j['refreshing'] == true;
  final String key;
  final String title;
  final String type;
  final bool refreshing;

  String get icon => switch (type) {
    'movie' => '🎬',
    'show' => '📺',
    'artist' => '🎵',
    'photo' => '🖼',
    _ => '📁',
  };
  String get label => '$icon $title';
}

/// One entry of the notification feed (what the bot would have messaged).
class Event {
  Event.fromJson(Json j)
    : id = _int(j['id']),
      ts = DateTime.tryParse(_str(j['ts']))?.toLocal() ?? DateTime.now(),
      read = j['read'] == true,
      type = _str(j['type']),
      raw = j;
  final int id;
  final DateTime ts;
  final bool read;
  final String type;
  final Map<String, dynamic> raw;

  String get series => _str(raw['series']);
  String get gid => _str(raw['gid']);
  String get name => _str(raw['name']);
  String get category => _str(raw['category']);
  String get state => _str(raw['state']);
  bool get autoScan => raw['auto_scan'] == true;
  double get progress => _double(raw['progress']);
  int get hours => _int(raw['hours']);
  List<String> get episodes => stringList(raw['episodes']);
  List<String> get libraries => stringList(raw['libraries']);
  String get error => _str(raw['error']);
  SeriesDefault? get seriesDefault => SeriesDefault.maybe(raw['default']);
  List<Release> get releases => [
    for (final r in jsonList(raw['releases'])) Release.fromJson(r),
  ];
}

class AppSettings {
  AppSettings.fromJson(Json j)
    : qbitRefreshHours = _int(j['qbit_refresh_hours']),
      favCheckHours = _int(j['fav_check_hours']),
      watchPollSeconds = _int(j['watch_poll_seconds']),
      stallAlertHours = _int(j['stall_alert_hours']),
      autoPlexScan = j['auto_plex_scan'] == true,
      plexMap = {
        for (final e in jsonMap(j['plex_map']).entries) e.key: _str(e.value),
      };
  final int qbitRefreshHours;
  final int favCheckHours;
  final int watchPollSeconds;
  final int stallAlertHours;
  final bool autoPlexScan;
  final Map<String, String> plexMap;
}

class Status {
  Status.fromJson(Json j)
    : snapshotTorrents = j['snapshot'] is Map
          ? _int(jsonMap(j['snapshot'])['torrents'])
          : null,
      snapshotUpdated = j['snapshot'] is Map
          ? DateTime.tryParse(
              _str(jsonMap(j['snapshot'])['updated']),
            )?.toLocal()
          : null,
      favorites = _int(j['favorites']),
      history = _int(j['history']),
      watches = _int(j['watches']),
      defaults = _int(j['defaults']),
      cookieConfigured = j['cookie_configured'] == true,
      plexUrl = _str(j['plex_url']),
      plexAuth = _str(j['plex_auth']),
      qbit = _str(j['qbit']),
      telegram = j['telegram'] == true,
      unreadEvents = _int(j['unread_events']),
      settings = AppSettings.fromJson(jsonMap(j['settings'])),
      settingsLocked = j['settings_locked'] == true,
      role = _str(j['role']).isEmpty ? 'admin' : _str(j['role']),
      userLogin = j['user_login'] == true,
      userPages = {
        for (final e in jsonMap(j['user_pages']).entries)
          e.key: e.value == true,
      },
      cacheCovers = _int(jsonMap(j['cache'])['covers']),
      cacheBytes = _int(jsonMap(j['cache'])['bytes']),
      cacheMaxBytes = _int(jsonMap(j['cache'])['max_bytes']),
      cacheClearEveryHours = _double(jsonMap(j['cache'])['clear_every_hours']),
      cacheClearedAt = DateTime.tryParse(
        _str(jsonMap(j['cache'])['cleared_at']),
      )?.toLocal();
  final int? snapshotTorrents;
  final DateTime? snapshotUpdated;
  final int favorites;
  final int history;
  final int watches;
  final int defaults;
  final int unreadEvents;
  final bool cookieConfigured;
  final bool telegram;
  final String plexUrl;
  final String plexAuth;
  final String qbit;
  final AppSettings settings;
  final bool settingsLocked;

  /// 'admin' or 'user' — which password this session logged in with.
  final String role;

  /// Whether the server has a USER_PASSWORD (so user access matters).
  final bool userLogin;

  /// Pages a user login may open, as set by the admin in Settings.
  final Map<String, bool> userPages;
  final int cacheCovers;
  final int cacheBytes;
  final int cacheMaxBytes;
  final double cacheClearEveryHours;
  final DateTime? cacheClearedAt;
}

// ---------------------------------------------------------------- NAS agents

class NasSystem {
  NasSystem.fromJson(Json j)
    : name = _str(j['name']),
      model = _str(j['model']),
      firmware = _str(j['firmware']),
      health = _str(j['health']),
      uptimeSeconds = _int(j['uptime_seconds']),
      tempC = j['temp_c'] is num ? (j['temp_c'] as num).round() : null,
      cpuTempC = j['cpu_temp_c'] is num
          ? (j['cpu_temp_c'] as num).round()
          : null,
      cpuPercent = j['cpu_percent'] is num
          ? (j['cpu_percent'] as num).toDouble()
          : null,
      memoryTotalMb = j['memory_total_mb'] is num
          ? (j['memory_total_mb'] as num).toDouble()
          : null,
      memoryFreeMb = j['memory_free_mb'] is num
          ? (j['memory_free_mb'] as num).toDouble()
          : null;
  final String name;
  final String model;
  final String firmware;
  final String health;
  final int uptimeSeconds;
  final int? tempC;
  final int? cpuTempC;
  final double? cpuPercent;
  final double? memoryTotalMb;
  final double? memoryFreeMb;
}

class NasDisk {
  NasDisk.fromJson(Json j)
    : slot = _str(j['slot']),
      model = _str(j['model']),
      serial = _str(j['serial']),
      capacity = _str(j['capacity']),
      type = _str(j['type']),
      health = _str(j['health']),
      tempC = j['temp_c'] is num ? (j['temp_c'] as num).round() : null;
  final String slot;
  final String model;
  final String serial;
  final String capacity;
  final String type;
  final String health;
  final int? tempC;
}

class NasFolder {
  NasFolder.fromJson(Json j)
    : name = _str(j['name']),
      usedBytes = _int(j['used_bytes']);
  final String name;
  final int usedBytes;
}

class NasVolume {
  NasVolume.fromJson(Json j)
    : label = _str(j['label']),
      status = _str(j['status']),
      totalBytes = _int(j['total_bytes']),
      freeBytes = _int(j['free_bytes']),
      usedPercent = j['used_percent'] is num
          ? (j['used_percent'] as num).toDouble()
          : null,
      folders = [for (final f in jsonList(j['folders'])) NasFolder.fromJson(f)];
  final String label;
  final String status;
  final int totalBytes;
  final int freeBytes;
  final double? usedPercent;
  final List<NasFolder> folders;
}

/// One report from agent/qnap_agent.py.
class NasReport {
  NasReport.fromJson(Json j)
    : ok = j['ok'] != false,
      error = _str(j['error']),
      system = NasSystem.fromJson(jsonMap(j['system'])),
      disks = [for (final d in jsonList(j['disks'])) NasDisk.fromJson(d)],
      volumes = [for (final v in jsonList(j['volumes'])) NasVolume.fromJson(v)];
  final bool ok;
  final String error;
  final NasSystem system;
  final List<NasDisk> disks;
  final List<NasVolume> volumes;
}

class NasAgent {
  NasAgent.fromJson(Json j)
    : name = _str(j['name']),
      receivedAt = DateTime.tryParse(_str(j['received_at']))?.toLocal(),
      online = j['online'] == true,
      refreshPending = j['refresh_pending'] == true,
      alerts = stringList(j['alerts']),
      report = NasReport.fromJson(jsonMap(j['report']));
  final String name;
  final DateTime? receivedAt;
  final bool online;
  final bool refreshPending;
  final List<String> alerts;
  final NasReport report;
}

/// GET /api/nas: every agent plus the alert thresholds.
class NasView {
  NasView.fromJson(Json j)
    : configured = j['configured'] == true,
      agents = [for (final a in jsonList(j['agents'])) NasAgent.fromJson(a)],
      usagePercent = _double(jsonMap(j['thresholds'])['usage_percent']),
      diskTempC = _int(jsonMap(j['thresholds'])['disk_temp_c']),
      refreshTimeoutSeconds = _or(jsonMap(j['refresh'])['timeout_seconds'], 45),
      refreshPollSeconds = _or(jsonMap(j['refresh'])['poll_seconds'], 2),
      pageReloadSeconds = _or(jsonMap(j['refresh'])['page_reload_seconds'], 60);
  final bool configured;
  final List<NasAgent> agents;
  final double usagePercent;
  final int diskTempC;

  /// Refresh-now / auto-reload timing, configured in the server's .env.
  final int refreshTimeoutSeconds;
  final int refreshPollSeconds;
  final int pageReloadSeconds;

  static int _or(dynamic v, int fallback) =>
      v is num && v > 0 ? v.round() : fallback;
}
