# qBittorrent Telegram bot + web app

Two front ends over one Python backend:

- `qbit_bot/` — the Telegram bot (python-telegram-bot). `bot.py` starts it
  **and** the web server.
- `qbit_web/` — FastAPI JSON API (`/api/…`, docs at `/api/docs`) over the same
  `qbit_bot` services; also serves the Flutter build from `webapp/build/web`.
  `web.py` runs it without Telegram.
- `webapp/` — the Flutter web app (package `qbit_web`). **All Flutter work
  happens in `webapp/`**: run `flutter analyze`, `flutter test`, and
  `flutter build web` from that directory. Widget tests drive the real app
  against `test/fake_server.dart`, an in-process fake of the API.
- `data/` — runtime JSON state shared by both front ends (favorites, watches,
  series defaults, settings, the `events.json` notification feed).

Python: `.venv/bin/python`, deps in `requirements.txt`. Never commit `.env`.

## Flutter app — current state vs. CONVENTIONS.md

The app predates the agent suite and is deliberately small: plain
`ChangeNotifier` + `InheritedNotifier` (`lib/state.dart`), `Navigator` pushes,
`package:http` (`lib/api/client.dart`, typed `Json` responses), hand-written
models (`lib/models.dart`), Material 3 screens under `lib/screens/`. It is
analyzer-clean under `very_good_analysis` (two rules relaxed with reasons in
`analysis_options.yaml`).

`lib/core/` holds the suite's scaffold (`Result`/`Failure`, `backend_config`,
`l10n` extension); `flutter gen-l10n` is wired but user-facing strings are not
yet in ARB files. When adding features, prefer extending the existing patterns
over a wholesale migration to Riverpod/go_router/freezed/dio unless the user
asks for that migration explicitly — it is a large change with no functional
gain for a single-user LAN app.

<!-- flutter-agent-suite:start -->
## Flutter Agent Suite
This project uses the Flutter agent suite in `.claude/agents/flutter-*.md`.
- For any non-trivial Flutter work (new feature, bug fix touching more than one
  layer, refactor, release) delegate to the `flutter-orchestrator` agent instead
  of implementing directly. `/flutter-feature <request>` is the shortcut.
- `CONVENTIONS.md` is the single source of truth for stack, architecture,
  error handling (`Result<T>` / `Failure`), localization, and the Definition of
  Done. Read it before changing Dart code; every agent enforces it.
- The backend mode lives in `lib/core/config/backend_config.dart`.
<!-- flutter-agent-suite:end -->
