// An in-process stand-in for qbit_web's API so widget tests can exercise
// every screen with realistic data and no qBittorrent / HeBits / Plex.
import 'dart:convert';
import 'dart:io';

class FakeServer {
  FakeServer({this.password = 'secret'});
  final String password;
  late HttpServer _server;
  final List<String> calls = [];
  final Map<String, dynamic> settings = {
    'qbit_refresh_hours': 3,
    'fav_check_hours': 3,
    'watch_poll_seconds': 30,
    'stall_alert_hours': 6,
    'auto_plex_scan': false,
    'plex_map': {'tv': '2'},
  };
  bool favAuto = false;
  bool settingsLocked = false; // SETTINGS_PASSWORD set on the server
  int nasRefreshRequests = 0; // POST /api/nas/refresh count
  DateTime nasReportedAt = DateTime.now().toUtc();
  String? userPassword = 'user'; // null = no USER_PASSWORD on the server
  String get userToken => 'user-tok';
  final Map<String, bool> userPages = {
    'browse': true,
    'search': true,
    'add': true,
    'library': false,
    'favorites': false,
    'activity': false,
    'plex': false,
    'nas': false,
  };
  int cacheClears = 0;
  String get settingsToken => 'settings-$password';

  // ---- GET /api/browse knobs -------------------------------------------
  /// One entry per browse request, as 'cat/page' (the plain [calls] list has
  /// no query string, and browse is all about which page was asked for).
  final List<String> browseCalls = [];

  /// The `genre` query parameter of each browse request ('' when absent).
  final List<String> browseGenres = [];
  int browsePages = 1;

  /// Extra single-release groups per browse page (`<Cat> Fill <page>-<k>`),
  /// to make a page tall enough to scroll.
  int browseFill = 0;

  /// Non-200 makes every browse request fail with [browseDetail].
  int browseStatus = 200;
  String browseDetail = 'HeBits cookie expired — set it again in Settings.';

  /// Answer with zero groups (the "nothing new" empty state).
  bool browseEmpty = false;

  /// Include a group with no releases, which the grid has to skip.
  bool browseGhost = false;

  /// Per-'cat/page' server-side delay, to make response races deterministic.
  final Map<String, Duration> browseDelay = {};

  /// gids passed to POST /api/favorites.
  final List<String> favAdded = [];

  Map<String, dynamic>? seriesDefault = {
    'name': 'Fauda (2015)',
    'tag': 'michael',
    'category': 'tv',
    'resolution': '1080p',
  };

  String get url => 'http://127.0.0.1:${_server.port}';
  String get token => 'tok-$password';

  Future<void> start() async {
    _server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _server.listen(_handle);
  }

  Future<void> stop() => _server.close(force: true);

  Future<void> _handle(HttpRequest req) async {
    final path = req.uri.path;
    final method = req.method;
    calls.add('$method $path');
    final body = await utf8.decoder.bind(req).join();
    final isJson =
        body.isNotEmpty &&
        req.headers.contentType?.mimeType == 'application/json';
    final json = isJson
        ? jsonDecode(body) as Map<String, dynamic>
        : <String, dynamic>{};

    Future<void> send(Object data, {int status = 200}) async {
      req.response.statusCode = status;
      req.response.headers.contentType = ContentType.json;
      req.response.write(jsonEncode(data));
      await req.response.close();
    }

    if (path == '/api/auth') {
      return send({
        'required': true,
        'user_login': userPassword != null,
        'settings_locked': settingsLocked,
        'version': 2,
      });
    }
    if (path == '/api/login') {
      if (json['password'] == password) {
        return send({'token': token, 'role': 'admin'});
      }
      if (userPassword != null && json['password'] == userPassword) {
        return send({'token': userToken, 'role': 'user'});
      }
      return send({'detail': 'Wrong password'}, status: 401);
    }
    final auth = req.headers.value('authorization') ?? '';
    final supplied = auth.startsWith('Bearer ')
        ? auth.substring(7)
        : (req.uri.queryParameters['token'] ?? '');
    final role = supplied == token
        ? 'admin'
        : supplied == userToken
        ? 'user'
        : null;
    if (role == null) return send({'detail': 'Not authorized'}, status: 401);
    if (role == 'user') {
      // the real server maps endpoint prefixes to pages; mirror the ones
      // the tests touch
      final adminOnly =
          path.startsWith('/api/settings') ||
          path.startsWith('/api/cookie') ||
          path.startsWith('/api/cache');
      final needsLibrary = path.startsWith('/api/torrents');
      if (adminOnly || (needsLibrary && userPages['library'] != true)) {
        return send({
          'detail': "This page isn't enabled for the user login",
        }, status: 403);
      }
    }

    final unlocked =
        !settingsLocked ||
        req.headers.value('x-settings-token') == settingsToken;

    switch ((method, path)) {
      case ('POST', '/api/settings/unlock'):
        if (json['password'] != 'lock') {
          return send({'detail': 'Wrong settings password'}, status: 401);
        }
        return send({'token': settingsToken});
      case ('POST', '/api/cache/clear'):
        if (!unlocked) {
          return send({'detail': 'Settings are locked'}, status: 403);
        }
        cacheClears++;
        return send({
          'cleared': {'covers': 7, 'bytes': 123456},
          'cache': {'covers': 0, 'bytes': 0, 'clear_every_hours': 24},
        });
      case ('GET', '/api/status'):
        return send({
          'snapshot': {
            'torrents': 42,
            'updated': DateTime.now().toUtc().toIso8601String(),
          },
          'favorites': 1,
          'history': 12,
          'watches': 2,
          'defaults': 1,
          'cookie_configured': true,
          'plex_url': 'http://localhost:32400',
          'plex_auth': 'lan',
          'qbit': 'localhost:8080',
          'telegram': true,
          'settings': settings,
          'unread_events': 3,
          'settings_locked': settingsLocked,
          'role': role,
          'user_login': userPassword != null,
          'user_pages': userPages,
          'cache': {
            'covers': 7,
            'bytes': 123456,
            'max_bytes': 1073741824,
            'clear_every_hours': 168,
            'cleared_at': null,
          },
        });
      case ('GET', '/api/settings'):
        return send({
          'settings': settings,
          'choices': {
            'qbit_refresh_hours': [1, 2, 3, 6, 12, 24],
            'fav_check_hours': [1, 2, 3, 6, 12, 24],
            'watch_poll_seconds': [15, 30, 60, 120],
            'stall_alert_hours': [0, 3, 6, 12, 24],
          },
          'resolutions': ['2160p', '1080p', '720p', '480p'],
          'hebits_cats': <String, String>{},
        });
      case ('PATCH', '/api/settings'):
        if (!unlocked) {
          return send({'detail': 'Settings are locked'}, status: 403);
        }
        if (json['key'] == 'user_pages') {
          for (final e in (json['value'] as Map).entries) {
            userPages['${e.key}'] = e.value == true;
          }
          settings['user_pages'] = userPages;
          return send({'settings': settings});
        }
        settings[json['key'] as String] = json['value'];
        return send({'settings': settings});
      case ('GET', '/api/search'):
        return send({
          'query': req.uri.queryParameters['q'],
          'cat': 'a',
          'page': 1,
          'pages': 2,
          'groups': [fauda, movie],
        });
      case ('GET', '/api/browse'):
        final cat = req.uri.queryParameters['cat'] ?? '';
        final page = int.tryParse(req.uri.queryParameters['page'] ?? '1') ?? 1;
        browseCalls.add('$cat/$page');
        final genre = req.uri.queryParameters['genre'] ?? '';
        browseGenres.add(genre);
        final delay = browseDelay['$cat/$page'];
        if (delay != null) await Future<void>.delayed(delay);
        if (browseStatus != 200) {
          return send({'detail': browseDetail}, status: browseStatus);
        }
        return send({
          'cat': cat,
          'page': page,
          'pages': browsePages,
          'genre': genre.isEmpty ? null : genre,
          'genres': [
            {'tag': 'דרמה', 'label': 'Drama'},
            {'tag': 'קומדיה', 'label': 'Comedy'},
          ],
          'groups': browseEmpty ? <Object>[] : browseGroups(cat, page),
        });
      case ('GET', '/api/group'):
        return send(fauda);
      case ('GET', '/api/torrents'):
        return send({'torrents': torrents});
      case ('GET', '/api/torrents/aaa'):
        return send(torrents[0]);
      case ('POST', '/api/torrents/aaa/pause'):
      case ('POST', '/api/torrents/aaa/resume'):
        return send({'ok': true});
      case ('POST', '/api/torrents/aaa/tags'):
        return send(torrents[0]);
      case ('DELETE', '/api/torrents/aaa'):
        return send({
          'ok': true,
          'name': torrents[0]['name'],
          'files_deleted': false,
        });
      case ('GET', '/api/tags'):
        return send({
          'tags': ['michael', 'kids'],
        });
      case ('GET', '/api/categories'):
        return send({
          'categories': ['movies', 'tv'],
        });
      case ('GET', '/api/favorites'):
        return send({
          'favorites': [
            {
              'gid': '1234',
              'name': 'Fauda (2015)',
              'query': 'Fauda',
              'auto': favAuto,
              'last_ep': [5, 10],
              'default': seriesDefault,
              'default_label': seriesDefault == null
                  ? null
                  : '🏷 michael + 📁 tv + 📐 1080p',
            },
          ],
        });
      case ('POST', '/api/favorites'):
        favAdded.add('${json['gid']}');
        return send({'gid': json['gid'], 'name': json['name'], 'auto': false});
      case ('PATCH', '/api/favorites/1234'):
        favAuto = json['auto'] == true;
        return send({'gid': '1234', 'name': 'Fauda (2015)', 'auto': favAuto});
      case ('POST', '/api/favorites/check'):
        return send({'notifications': <Object>[]});
      case ('GET', '/api/defaults'):
        return send({
          'defaults': {'1234': seriesDefault},
        });
      case ('PUT', '/api/defaults/1234'):
        seriesDefault = json;
        return send({'gid': '1234', 'default': json, 'label': 'saved'});
      case ('DELETE', '/api/defaults/1234'):
        seriesDefault = null;
        return send({'ok': true});
      case ('POST', '/api/add/hebits'):
        return send({
          'ok': true,
          'name': json['title'],
          'hash': 'h',
          'watched': true,
          'offer_default': json['category'] != null && seriesDefault == null,
          'gid': json['gid'],
          'series': json['series'],
        });
      case ('GET', '/api/events'):
        return send({'events': events, 'unread': 3});
      case ('POST', '/api/events/read'):
        for (final e in events) {
          e['read'] = true;
        }
        return send({'ok': true});
      case ('POST', '/api/nas/refresh'):
        nasRefreshRequests++;
        // pretend the agent answered right away
        nasReportedAt = DateTime.now().toUtc().add(const Duration(seconds: 1));
        return send({
          'requested': <String>['qnap'],
        });
      case ('GET', '/api/nas'):
        return send({
          'configured': true,
          'thresholds': {'usage_percent': 90, 'disk_temp_c': 55},
          'agents': [
            {
              'name': 'qnap',
              'received_at': nasReportedAt.toIso8601String(),
              'online': true,
              'alerts': ['disk:2:temp', 'vol:DataVol1:usage'],
              'report': {
                'kind': 'qnap',
                'ok': true,
                'error': null,
                'system': {
                  'name': 'Media NAS',
                  'model': 'TS-464',
                  'firmware': '5.2.0',
                  'health': 'good',
                  'uptime_seconds': 864000,
                  'temp_c': 41,
                  'cpu_percent': 7.5,
                  'cpu_temp_c': 48,
                  'memory_total_mb': 7800,
                  'memory_free_mb': 5100,
                },
                'disks': [
                  {
                    'slot': 1,
                    'model': 'WD Red 8TB',
                    'serial': 'X1',
                    'capacity': '7.28 TB',
                    'type': 'hdd',
                    'health': 'good',
                    'temp_c': 38,
                  },
                  {
                    'slot': 2,
                    'model': 'WD Red 8TB',
                    'serial': 'X2',
                    'capacity': '7.28 TB',
                    'type': 'hdd',
                    'health': 'good',
                    'temp_c': 61,
                  },
                ],
                'volumes': [
                  {
                    'label': 'DataVol1',
                    'status': 'Ready',
                    'total_bytes': 14000000000000,
                    'free_bytes': 900000000000,
                    'used_percent': 93.6,
                    'folders': [
                      {'name': 'Media', 'used_bytes': 9000000000000},
                    ],
                  },
                ],
              },
            },
          ],
        });
      case ('GET', '/api/plex/sections'):
        return send({'sections': sections});
      case ('POST', '/api/plex/scan'):
        return send({'scanning': sections});
      case ('GET', '/api/cookie'):
        return send({'configured': true, 'valid': true, 'user': 'michael'});
      case ('POST', '/api/refresh'):
        return send({'torrents': 42, 'completed': 40});
      case ('GET', '/api/cover'):
        req.response.statusCode = 404;
        return req.response.close();
    }
    return send({'detail': 'no fake for $method $path'}, status: 404);
  }

  static Map<String, dynamic> release(
    int id,
    String title,
    String res,
    int seeders, {
    bool free = false,
    bool snatched = false,
    Map<String, dynamic>? local,
    int season = 5,
  }) => {
    'id': id,
    'title': title,
    'resolution': res,
    'codec': 'H.264',
    'container': 'MKV',
    'subs': 'Hebrew',
    'size': 2040109465,
    'seeders': seeders,
    'leechers': 3,
    'snatches': 120,
    'free': free,
    'snatched': snatched,
    'local': local,
    'episode': RegExp(r'S\d\dE\d\d').firstMatch(title)?.group(0) ?? '',
    'season': season,
  };

  Map<String, dynamic> get fauda => {
    'gid': '1234',
    'name_en': 'Fauda',
    'name_he': 'פאודה',
    'year': '2015',
    'cover': 'https://example.com/fauda.jpg',
    'imdb': 'https://www.imdb.com/title/tt4565380/',
    'cat': '📺 TV',
    'favorite': true,
    'auto': favAuto,
    'default': seriesDefault,
    'torrents': [
      release(1, 'Fauda.S05E11.1080p.WEB.H264-NTb', '1080p', 437, free: true),
      release(
        2,
        'Fauda.S05E10.1080p.WEB.H264-NTb',
        '1080p',
        200,
        snatched: true,
        local: {'status': 'done'},
      ),
      release(
        3,
        'Fauda.S05E09.720p.WEB.H264-NTb',
        '720p',
        50,
        local: {'status': 'dl', 'progress': 0.42},
      ),
      release(4, 'Fauda.S04E12.1080p.WEB.H264-NTb', '1080p', 20, season: 4),
    ],
  };

  /// One page of the newest-uploads feed. Same shape as /api/search groups;
  /// the titles encode cat + page so every assertion can be an exact
  /// `find.text` and a stale page can never be mistaken for a fresh one.
  List<Map<String, dynamic>> browseGroups(String cat, int page) {
    final label = cat == 'movies' ? 'Movies' : 'Series';
    return [
      ..._baseBrowseGroups(cat, page),
      for (var k = 0; k < browseFill; k++)
        <String, dynamic>{
          ...movie,
          'gid': 'fill-$cat-$page-$k',
          'name_en': '$label Fill $page-$k',
          'name_he': '',
          'year': '2024',
          'favorite': false,
          'torrents': movie['torrents'],
        },
    ];
  }

  List<Map<String, dynamic>> _baseBrowseGroups(String cat, int page) {
    final label = cat == 'movies' ? 'Movies' : 'Series';
    return [
      // A release-less group: the grid must skip it (Group.title would throw).
      if (browseGhost)
        <String, dynamic>{
          ...movie,
          'gid': 'ghost-$cat-$page',
          'name_en': '$label Ghost $page',
          'name_he': '',
          'torrents': <Object>[],
        },
      // Favorite, freeleech, snatched and downloaded → every tile marker.
      <String, dynamic>{
        ...fauda,
        'gid': 'top-$cat-$page',
        'name_en': '$label Top $page',
      },
      // Not a favorite, one release still downloading.
      <String, dynamic>{
        ...movie,
        'gid': 'pick-$cat-$page',
        'name_en': '$label Pick $page',
        'name_he': '',
        'torrents': [
          release(
            600 + page,
            '$label.Pick.$page.1080p.WEB.H264-NTb',
            '1080p',
            9,
            local: {'status': 'dl', 'progress': 0.42},
            season: -1,
          ),
        ],
      },
    ];
  }

  final Map<String, Object?> movie = {
    'gid': '99',
    'name_en': 'Some Movie',
    'name_he': 'סרט',
    'year': '2025',
    'cover': '',
    'imdb': '',
    'cat': '🎬 Movies',
    'favorite': false,
    'auto': false,
    'default': null,
    'torrents': [
      release(5, 'Some.Movie.2025.2160p.WEB.H265-NTb', '2160p', 15, season: -1),
    ],
  };

  final List<Map<String, Object>> torrents = [
    {
      'hash': 'aaa',
      'name': 'Fauda.S05E10.1080p.WEB.H264-NTb',
      'state': 'downloading',
      'progress': 0.42,
      'size': 2040109465,
      'total_size': 2040109465,
      'downloaded': 856845975,
      'uploaded': 1000,
      'dlspeed': 5242880,
      'upspeed': 1024,
      'ratio': 0.01,
      'eta': 226,
      'num_seeds': 12,
      'num_leechs': 3,
      'tags': ['michael'],
      'category': 'tv',
      'added_on': 1757000000,
      'completion_on': 0,
      'save_path': '/Volumes/Media/TV',
    },
    {
      'hash': 'bbb',
      'name': 'Some.Movie.2025.2160p.WEB.H265-NTb',
      'state': 'stalledUP',
      'progress': 1.0,
      'size': 5040109465,
      'total_size': 5040109465,
      'downloaded': 5040109465,
      'uploaded': 7000000000,
      'dlspeed': 0,
      'upspeed': 0,
      'ratio': 1.39,
      'eta': 8640000,
      'num_seeds': 0,
      'num_leechs': 0,
      'tags': [],
      'category': 'movies',
      'added_on': 1756000000,
      'completion_on': 1756100000,
      'save_path': '/Volumes/Media/Movies',
    },
  ];

  final List<Map<String, Object>> events = [
    {
      'type': 'new_episodes',
      'series': 'The Bear (2022)',
      'gid': '5678',
      'episodes': ['S04E03'],
      'releases': [
        release(
          222,
          'The.Bear.S04E03.2160p.WEB.H265-NTb',
          '2160p',
          12,
          season: 4,
        ),
        release(
          223,
          'The.Bear.S04E03.1080p.WEB.H264-NTb',
          '1080p',
          88,
          free: true,
          season: 4,
        ),
      ],
      'id': 4,
      'ts': '2026-09-05T15:10:00+00:00',
      'read': false,
    },
    {
      'type': 'auto_added',
      'series': 'Fauda (2015)',
      'gid': '1234',
      'default': {
        'name': 'Fauda',
        'tag': 'michael',
        'category': 'tv',
        'resolution': '1080p',
      },
      'releases': [
        release(111, 'Fauda.S05E11.1080p.WEB.H264-NTb', '1080p', 437),
      ],
      'id': 3,
      'ts': '2026-09-05T14:00:00+00:00',
      'read': false,
    },
    {
      'type': 'stalled',
      'name': 'Some.Movie.2025.2160p',
      'hash': 'def',
      'progress': 0.42,
      'hours': 6,
      'id': 2,
      'ts': '2026-09-05T12:00:00+00:00',
      'read': false,
    },
    {
      'type': 'completed',
      'name': 'Fauda.S05E10.1080p.WEB.H264-NTb',
      'hash': 'abc',
      'category': 'tv',
      'auto_scan': false,
      'id': 1,
      'ts': '2026-09-05T10:00:00+00:00',
      'read': true,
    },
  ];

  final List<Map<String, Object>> sections = [
    {'key': '1', 'title': 'Movies', 'type': 'movie', 'refreshing': false},
    {'key': '2', 'title': 'TV Shows', 'type': 'show', 'refreshing': true},
  ];
}
