import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/models.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Connection + session state shared by every screen, plus a light poll of
/// /api/status for the unread-notifications badge.
class AppState extends ChangeNotifier {
  AppState() : api = ApiClient(baseUrl: _defaultBaseUrl());

  final ApiClient api;
  bool ready = false; // prefs loaded, first /api/auth attempt done
  bool authRequired = false;
  bool settingsLocked = false; // server has SETTINGS_PASSWORD set
  bool connected = false; // server reachable and (if needed) logged in
  String? connectError;
  Status? status;
  Timer? _poll;

  /// Same origin as the page — the backend serves the build itself. Under
  /// `flutter run` (a dev server on another port) this is overridden by the
  /// saved server URL from the connect screen.
  static String _defaultBaseUrl() {
    final base = Uri.base;
    if (base.scheme.startsWith('http')) return base.origin;
    return 'http://localhost:8765';
  }

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    api.baseUrl = prefs.getString('baseUrl') ?? api.baseUrl;
    api.token = prefs.getString('token') ?? '';
    await connect();
    ready = true;
    notifyListeners();
  }

  Future<bool> connect({String? baseUrl}) async {
    if (baseUrl != null) {
      api.baseUrl = baseUrl.trim().replaceAll(RegExp(r'/+$'), '');
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('baseUrl', api.baseUrl);
    }
    connectError = null;
    try {
      final auth = await api.get('/api/auth');
      authRequired = auth['required'] == true;
      settingsLocked = auth['settings_locked'] == true;
      if (!settingsLocked) api.settingsToken = '';
      if (!authRequired) api.token = '';
      // /api/status also validates the token
      status = Status.fromJson(await api.get('/api/status'));
      connected = true;
    } on ApiException catch (e) {
      connected = false;
      if (e.unauthorized) {
        connectError = api.token.isEmpty
            ? null
            : 'Session expired — log in again';
        api.token = '';
      } else {
        connectError = e.message;
      }
    }
    _schedulePoll();
    notifyListeners();
    return connected;
  }

  Future<void> login(String password) async {
    final res = await api.post('/api/login', {'password': password});
    api.token = '${res['token'] ?? ''}';
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('token', api.token);
    await connect();
  }

  /// Whether the Settings tab may be shown right now.
  bool get settingsUnlocked => !settingsLocked || api.settingsToken.isNotEmpty;

  Future<void> unlockSettings(String password) async {
    final res = await api.post('/api/settings/unlock', {'password': password});
    api.settingsToken = '${res['token'] ?? ''}';
    notifyListeners();
  }

  void lockSettings() {
    api.settingsToken = '';
    notifyListeners();
  }

  Future<void> logout() async {
    api.token = '';
    api.settingsToken = '';
    connected = false;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
    notifyListeners();
  }

  Future<void> refreshStatus() async {
    if (!connected) return;
    try {
      status = Status.fromJson(await api.get('/api/status'));
      notifyListeners();
    } on ApiException catch (e) {
      if (e.unauthorized) {
        connected = false;
        api.token = '';
        connectError = 'Session expired — log in again';
        notifyListeners();
      }
    }
  }

  void _schedulePoll() {
    _poll?.cancel();
    if (connected) {
      _poll = Timer.periodic(
        const Duration(seconds: 30),
        (_) => refreshStatus(),
      );
    }
  }

  /// Signal that something changed the badge count (events read, etc.).
  void bumpUnread(int unread) {
    final s = status;
    if (s != null && s.unreadEvents != unread) {
      unawaited(refreshStatus());
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    api.close();
    super.dispose();
  }
}

class AppScope extends InheritedNotifier<AppState> {
  const AppScope({required AppState state, required super.child, super.key})
    : super(notifier: state);

  static AppState of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// Read without subscribing (for callbacks).
  static AppState read(BuildContext context) =>
      (context.getElementForInheritedWidgetOfExactType<AppScope>()!.widget
              as AppScope)
          .notifier!;
}
