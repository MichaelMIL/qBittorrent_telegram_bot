# qBittorrent Telegram Bot + Web App

A personal Telegram bot — and a matching web app for phones and desktops — that
manages the qBittorrent instance on your Mac and searches your
[HeBits](https://hebits.net) account: search with posters and season
navigation, add with tags and categories, track downloads, star favorite
series, and get pinged when a new episode drops. Both front ends share one
backend, so favorites, series defaults, watches and settings are the same
everywhere.

## Features

- **Search HeBits** by typing any text — results are grouped by movie/show,
  filterable (🌐 All / 🎬 Movies / 📺 Series) with page navigation. Tap a
  result for a detail card with the poster, Hebrew + English titles, an IMDB
  link, and one download button per release. TV shows are organized by season
  (newest first, season packs on top) with season buttons and paging built in
- **Add** via search, magnet link, or `.torrent` file — every add walks
  through a tag → category flow (existing, new, or none) to keep the library
  tidy
- **Completion pings** — every torrent added through the bot is watched in
  the background; once the download hits 100% *and* qBittorrent has finished
  moving the files to their final location, the bot messages you (name +
  category) with a 🎞 *Scan Plex now* button right on the message. With
  **auto-scan** on (in `/settings`), the scan starts by itself instead —
  only the Plex library mapped to the torrent's category (`/settings` →
  *Category → Plex library map*; unmapped categories scan everything)
- **Stuck-download alerts** — watched downloads that hit an error state or
  sit stalled for hours (threshold configurable, or off) trigger a one-time
  warning instead of silently never finishing
- **Series defaults** — after adding an episode, one tap (📌) remembers its
  tag + category as the default for that series, then asks for a preferred
  resolution (2160p/1080p/720p/480p/any). Picking any future episode (from
  search or a new-episode alert) then asks "use the default?" — ✅ adds it
  instantly, or choose manually / forget the default
- **⚡ Auto-add** — flip the ⚡ toggle on a favorite (in `/fav`) and new
  episodes are grabbed automatically: the best-seeded release in the series'
  preferred resolution is added with its default tag + category, and you get
  a summary message instead of buttons. The ⚡/💤 icon opens a per-series
  menu: toggle auto-add, and set or ✏️ edit the default (tag → category →
  resolution) right there. Episodes
  not yet available in that resolution fall back to the normal
  pick-a-version notification, and so does anything that fails to add
- **Manage** — `/list` shows everything in qBittorrent; tap a torrent to see
  progress/speeds/ETA, pause/resume, toggle tags, or delete it (with or
  without files, always with confirmation). Browse by `/tags` or `/categories`
- **Download indicators** — search results are matched against qBittorrent
  (exact info-hash for bot-added torrents, normalized release name otherwise)
  and lead with live status icons:
  `✅✔️ 🌱437 · 3. S05E11 · 1080p · 1.9 GiB`
  (✅ downloaded · ⏬ downloading with % · 📥 added before, gone now ·
  ✔️ snatched on HeBits · 🆓 freeleech)
- **Favorites** — star a series from its card; `/fav` reopens it fresh in two
  taps. A background check announces **new episodes** with one button per
  available version; the baseline is the newest episode you actually *have*,
  so an undownloaded episode is offered on the very first check. Each episode
  is announced once
- **Plex scans** — `/plex` (or the button in `/settings`) lists your Plex
  libraries with one tap to scan any of them — or all at once — for new
  files, e.g. right after a completion ping. Every scan posts a "🔍
  scanning…" message that flips to "✅ finished (took 41s)" when Plex is
  done. Works token-less on the LAN via Plex's allowed-without-auth list,
  or with `PLEX_TOKEN` (see setup)
- **Settings** — `/settings` shows status (snapshot age, favorites, watched
  downloads, cookie, Plex) with maintenance buttons and tunables that apply
  immediately and persist: qBittorrent refresh & episode-check intervals
  (1–24 h), completion-check frequency (15–120 s), stuck-download alert
  threshold (off–24 h), the Plex auto-scan toggle, and the category →
  library map
- **Button bar** — a persistent reply keyboard (📚 List · ⭐ Favorites ·
  🆕 Check · 🏷 Tags · 📁 Categories · 🎞 Plex · ⚙️ Settings) makes daily
  use tap-only; typing is needed only for searches and naming new tags
- **Web app** — the same features in a browser (`http://<mac-ip>:8765`,
  works on mobile): a **New on HeBits** home screen (newest series and
  movies as poster tiles, paged), search results as poster tiles, a detail card with
  season chips and one row per release, the tag → category add flow with
  series defaults, magnet/.torrent adds, the live torrent list with
  pause/resume/tags/category/delete, favorites with ⚡ auto-add and the
  default wizard, an **Activity** feed with every notification (new
  episodes with add buttons, completion pings with a Scan Plex button,
  stuck alerts), Plex scans and all the settings. Admin and user logins
  (`ADMIN_PASSWORD` / `USER_PASSWORD`). See [Web app](#web-app)
- **Private** — the bot only serves the Telegram user IDs in
  `ALLOWED_USER_IDS`; anyone else gets a rejection message that includes
  their own user id, so adding a trusted person is as easy as having them
  message the bot and copying the id they're shown. All HeBits traffic
  (search, downloads, cover images) goes from your machine, never through
  Telegram's servers

## Project layout

```
bot.py                 entry point: Telegram bot + web app (python bot.py)
web.py                 entry point: web app only, no Telegram (python web.py)
hebits_cookie.py       standalone cookie-capture helper
qbit_bot/
  config.py            env, paths, constants
  utils.py             formatting, episode parsing, info-hash
  storage.py           JSON stores: history, favorites, settings, snapshot
  qbit.py              qBittorrent client + live status decoration
  hebits.py            HeBits API: search, download, covers, cookie
  plex.py              Plex API: list libraries, trigger scans
  views.py             message texts and keyboards
  jobs.py              background loops (snapshot refresh, episode alerts,
                       completion pings) — every alert is a plain "note"
                       recorded to the events feed and rendered for Telegram
  handlers.py          commands, callbacks, add flows
  main.py              application wiring (starts the web server too)
qbit_web/
  api.py               FastAPI JSON API over the qbit_bot services
  server.py            app factory; runs inside the bot's loop or standalone
webapp/                Flutter web app (lib/, test/; build with flutter build web)
data/                  runtime state (git-ignored): history.json,
                       favorites.json, qbit_cache.json, bot_settings.json,
                       watch.json, series_defaults.json, notified.json,
                       events.json (notification feed shown in the web app)
```

## Setup

### 1. Enable the qBittorrent Web UI (on the Mac)

1. qBittorrent → **Preferences** (⌘,) → **Web UI**
2. Check **Web User Interface (Remote control)**, note the port (default
   `8080`), set a username/password
3. If the bot runs on another machine, note the Mac's LAN IP and allow
   incoming connections in the macOS firewall. Verify with
   `http://<mac-ip>:8080` in a browser

### 2. Create the Telegram bot

1. [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**
2. Get your numeric user ID: just message **your new bot** once it's running —
   unauthorized users are shown their own id in the rejection message. For
   the very first start, leave `ALLOWED_USER_IDS` set to any number, message
   the bot, copy the id it shows you, then update `.env` and restart.

### 3. Configure & run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in token, user ID, qBittorrent host/credentials
python bot.py
```

The bot refuses to start with an empty `ALLOWED_USER_IDS`.

### 4. HeBits session cookie (for search)

HeBits' login page has a captcha, so the bot authenticates with your browser
session cookie (the same approach Jackett uses). Two ways to set it:

- **Automatic:** `pip install browser_cookie3 && python hebits_cookie.py` on
  the machine where you're logged in to hebits.net — it finds the cookie,
  validates the session (prints your username), and writes it to `.env`
- **From Telegram:** copy the `Cookie` request header from DevTools → Network
  and send `/cookie <paste>` — the bot validates it, saves it without a
  restart, and deletes your message so the cookie doesn't linger in chat

`/cookie` with no arguments (or the button in `/settings`) checks whether the
session is still valid. Tick *keep me logged in* on the site so it lasts;
when it expires, error messages say so explicitly.

### 5. Plex (optional, for library scans)

Set `PLEX_URL` in `.env` (default `http://localhost:32400`). For auth, pick
one:

- **No token (recommended for LAN):** leave `PLEX_TOKEN` empty and add the
  bot machine's IP to Plex → Settings → Network → *"List of IP addresses and
  networks that are allowed without auth"* (e.g. `127.0.0.1` when the bot
  runs on the Plex machine). Nothing can expire. If *Secure connections* is
  set to **Required**, switch it to **Preferred** so plain-HTTP LAN requests
  are accepted
- **Token:** set `PLEX_TOKEN` to the server's own long-lived token — on the
  Mac running Plex: `defaults read com.plexapp.plexmediaserver
  PlexOnlineToken`. (Avoid the "View XML" browser token — Plex documents it
  as temporary)

### 6. Web app (optional)

The backend serves the Flutter build itself, so it's one process. The built
bundle (`webapp/build/web`, minus CanvasKit which loads from Google's CDN) is
committed, so a host without Flutter just needs `git pull`. Rebuild it on the
machine that has Flutter whenever `webapp/` changes, and commit the result:

```bash
# on the dev machine, after changing webapp/
cd webapp && flutter build web && cd .. && git add webapp/build/web && git commit -m "Rebuild web app"

# .env: set the admin password — without one, anyone on your network can
# control qBittorrent through the app; USER_PASSWORD is optional
ADMIN_PASSWORD=something-long
USER_PASSWORD=something-else

python bot.py     # Telegram + web app on http://<mac-ip>:8765
python web.py     # web app only (no BOT_TOKEN needed); runs the same
                  # background jobs, notifications land in the Activity feed
```

Open `http://<mac-ip>:8765` from any browser on the LAN (add it to the phone's
home screen — it's a PWA). Two logins share the one password field:
`ADMIN_PASSWORD` sees and can do everything; `USER_PASSWORD` gets a restricted
app — only the pages the admin enables in Settings → *User access* (by default
New, Search and adding; Library, Favorites, Activity and Plex are off and
Settings is never shown). The server enforces the same rules on its API. The
login is remembered on the device; the small ⏏ Disconnect button (New tab's
app bar, or the bottom of the rail) forgets it. `WEB_HOST`, `WEB_PORT` and `WEB_ENABLED=0` (to
turn the server off in `bot.py`) are in `.env.example`, as are
`SETTINGS_PASSWORD` (locks the Settings tab behind a second password) and
`CACHE_CLEAR_HOURS` / `CACHE_MAX_MB` (posters are cached on disk in
`data/covers` as small JPEGs; the cache is capped at 1 GiB and wiped weekly by
default; the Settings tab has a Clear cache button too). The startup log
prints the reachable URLs. Interactive API docs: `/api/docs`.

Don't run `bot.py` and `web.py` at the same time — both run the background
jobs, so you'd get double notifications and double auto-adds.

## Web app

| Tab | What's there |
|---|---|
| 🆕 New (home) | the newest uploads on HeBits — the site's `series.php` / `movies.php` pages — as poster tiles, one tab per category, paged, pull-to-refresh, with a genre filter (drama, comedy, thriller, Israeli, …; filtered on the server, so paging stays correct). Same markers and detail card as search, so adding works the same way. On phones this is the first bottom-bar slot; Search is reached from its app bar |
| 🔎 Search | HeBits search with 🌐/🎬/📺 filter and paging; poster tiles with the same markers as the bot (✅ ⏬ 📥 🆓 ✔️). Tap a tile for the detail card: poster, titles, IMDB, ⭐ favorite toggle, season chips, one row per release. Tap a release to add it — the series default is offered first, otherwise tag → category (existing / new / none); afterwards you can 📌 make the choice the series default and pick a resolution. The ➕ button adds a magnet link or a .torrent file |
| 📚 Library | everything in qBittorrent, live (5 s), filter by tag / category / name. Tap a torrent for progress, speeds, ETA, peers, path, pause/resume, tags (toggle, new), category, delete (with or without files, confirmed) |
| ⭐ Favorites | starred series with their default and newest known episode; ⚡ switch toggles auto-add (walks you through setting a default if there is none); the ⋮ menu edits / forgets the default or removes the favorite; **Check episodes** runs the scan right now |
| 🔔 Activity | the notification feed: new episodes (tap a release to add it), auto-adds, completion pings (with **Scan Plex now**), stuck / error alerts, Plex scans. Unread count on the tab; swipe to dismiss |
| 🎞 Plex | libraries with one-tap scans and live "scanning…" state (top-level on wide screens, under Settings / Library on phones) |
| 🗄 NAS | disk health, temperatures and volume usage of the QNAP, reported by a small agent that runs on the machine next to it (see [QNAP agent](#qnap-agent)). Alerts for a bad disk, a hot disk, a full volume or a silent agent go to Telegram and the Activity feed |
| ⚙️ Settings | status, poster cache (posters are re-encoded small and kept on disk under `data/covers`, capped at 1 GiB with oldest-first eviction, wiped weekly; size, schedule and a **Clear cache** button), the four intervals, auto-scan toggle, category → Plex library map, refresh / check / validate cookie / update cookie, log out. With `SETTINGS_PASSWORD` set in `.env` the tab is locked behind that second password (asked once per session; the server also refuses settings changes, cookie updates and cache clears without it) |

Development: `cd webapp && flutter run -d chrome` starts the app on a dev
server; on the connect screen point it at the backend URL (CORS is open).
`flutter test` runs the widget tests against an in-process fake API.

## QNAP agent

The NAS page is fed by `agent/qnap_agent.py`, which runs on a machine that can
reach the QNAP's web UI (the Plex Mac), logs in with a user + password, and
posts a report every 5 minutes to the web app. On the server side set the same
random `AGENT_TOKEN` in `.env` (plus, optionally, `NAS_USAGE_ALERT_PERCENT`,
`NAS_DISK_TEMP_ALERT_C`, `AGENT_STALE_MINUTES`) and restart the bot.

On the Mac, from a clone of this repo:

```bash
cp agent/.env.example agent/.env   # QNAP_HOST/USER/PASSWORD, WEBAPP_URL, AGENT_TOKEN
agent/install_mac.sh               # copies to ~/qnap-agent, venv, test report, launchd job
```

`install_mac.sh` sends one test report before installing, then registers a
launchd job that starts at login and restarts on failure (log:
`/tmp/qnap-agent.log`). Re-run it to update; `--uninstall` removes the job;
`--daemon` installs it system-wide (`sudo`) so it runs at boot without a login
— handy if the Mac sits at the login screen after a reboot. Manual alternative:
`python qnap_agent.py --once` prints the report it would send.

The agent uses [python-qnapstats](https://github.com/colinodell/python-qnapstats)
(the library behind Home Assistant's QNAP integration); a read-only QNAP user
is enough. User logins see the NAS page only if the admin enables it.

## Commands

| Command | What it does |
|---|---|
| *(any text)* | search HeBits |
| `/search <name>` | same, explicitly |
| `/list` | browse & manage torrents |
| `/tags`, `/categories` | browse by label |
| `/favorites`, `/fav` | starred series |
| `/check` | scan favorites for new episodes now |
| `/settings` | status, intervals & maintenance |
| `/plex` | scan Plex libraries for new files |
| `/refresh` | re-read the torrent list from qBittorrent |
| `/cookie` | check or update the HeBits session |
| `/cancel` | abort the current flow |
| `/help` | command cheat-sheet |
| `/start` | full walkthrough + button bar |

## Run it permanently (optional)

```ini
# ~/.config/systemd/user/qbit-bot.service
[Unit]
Description=qBittorrent Telegram bot
After=network-online.target

[Service]
WorkingDirectory=%h/Desktop/qBittorrent_telegram_bot
ExecStart=%h/Desktop/qBittorrent_telegram_bot/.venv/bin/python bot.py
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now qbit-bot
```

On macOS, use `launchd` or simply
`nohup .venv/bin/python bot.py >/tmp/qbit-bot.log 2>&1 &`. The web app is
served by the same process.
