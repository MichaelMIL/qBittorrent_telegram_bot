/// Backend configuration for this project.
///
/// The agent suite is backend-agnostic; the API/Contract, Security and Build
/// agents read [backendMode] to adapt their behavior.
///
/// This app talks to the Python backend in `qbit_web/` (FastAPI, JSON under
/// `/api/…`). The backend serves the Flutter build itself, so at runtime the
/// base URL is normally the page's own origin; `AppState` resolves it (and
/// lets the user override it on the connect screen for `flutter run` dev
/// builds). [apiBaseUrl] is only a compile-time default for that fallback.
enum BackendMode { rest, graphql, firebase, supabase }

/// Active backend for this project.
const BackendMode backendMode = BackendMode.rest;

/// Compile-time default base URL. Override per environment via
/// `--dart-define=API_BASE_URL=...` or `--dart-define-from-file=env/dev.json`.
/// Values passed this way are compiled into the binary: configuration, not
/// secrets.
const String apiBaseUrl = String.fromEnvironment('API_BASE_URL');
