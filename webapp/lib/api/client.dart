import 'dart:convert';

import 'package:http/http.dart' as http;

/// A decoded JSON object as returned by every qbit_web endpoint.
typedef Json = Map<String, dynamic>;

/// Error from the backend (or the network), with the server's `detail` text.
class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;

  bool get unauthorized => status == 401;

  @override
  String toString() => message;
}

/// Thin JSON client for the qbit_web API.
class ApiClient {
  ApiClient({required this.baseUrl, this.token = ''});

  String baseUrl;
  String token;
  final http.Client _http = http.Client();

  Uri _uri(String path, [Map<String, String?>? query]) {
    final q = <String, String>{};
    query?.forEach((k, v) {
      if (v != null) q[k] = v;
    });
    return Uri.parse(
      '$baseUrl$path',
    ).replace(queryParameters: q.isEmpty ? null : q);
  }

  Map<String, String> get _headers => {
    'Accept': 'application/json',
    if (token.isNotEmpty) 'Authorization': 'Bearer $token',
  };

  Future<Json> get(String path, [Map<String, String?>? query]) =>
      _send(() => _http.get(_uri(path, query), headers: _headers));

  Future<Json> post(String path, [Object? body]) => _send(
    () => _http.post(
      _uri(path),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: jsonEncode(body ?? {}),
    ),
  );

  Future<Json> put(String path, Object body) => _send(
    () => _http.put(
      _uri(path),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: jsonEncode(body),
    ),
  );

  Future<Json> patch(String path, Object body) => _send(
    () => _http.patch(
      _uri(path),
      headers: {..._headers, 'Content-Type': 'application/json'},
      body: jsonEncode(body),
    ),
  );

  Future<Json> delete(String path, [Map<String, String?>? query]) =>
      _send(() => _http.delete(_uri(path, query), headers: _headers));

  /// Multipart upload (used for .torrent files).
  Future<Json> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    Map<String, String> fields = const {},
  }) {
    return _send(() async {
      final req = http.MultipartRequest('POST', _uri(path))
        ..headers.addAll(_headers)
        ..fields.addAll(fields)
        ..files.add(
          http.MultipartFile.fromBytes('file', bytes, filename: filename),
        );
      final streamed = await req.send().timeout(const Duration(seconds: 60));
      return http.Response.fromStream(streamed);
    });
  }

  /// Drop idle connections (stops their keep-alive timers).
  void close() => _http.close();

  /// URL of the poster proxy for an external cover image. `<img>` tags can't
  /// send headers on the web, so the token rides along as a query parameter.
  String coverUrl(String url) => _uri('/api/cover', {
    'url': url,
    if (token.isNotEmpty) 'token': token,
  }).toString();

  Future<Json> _send(Future<http.Response> Function() call) async {
    http.Response res;
    try {
      res = await call().timeout(const Duration(seconds: 90));
    } on ApiException {
      rethrow;
    } on Exception {
      throw ApiException(0, "Can't reach the server ($baseUrl)");
    }
    Object? data;
    if (res.body.isNotEmpty) {
      try {
        data = jsonDecode(utf8.decode(res.bodyBytes));
      } on FormatException {
        data = null;
      }
    }
    final map = data is Map ? Json.from(data) : null;
    if (res.statusCode >= 400) {
      final detail = map?['detail'];
      throw ApiException(
        res.statusCode,
        detail is String
            ? detail
            : detail == null
            ? 'HTTP ${res.statusCode}'
            : jsonEncode(detail),
      );
    }
    // every endpoint answers with an object; anything else is wrapped
    return map ?? {'data': data};
  }
}
