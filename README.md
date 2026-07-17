# qBittorrent Telegram Bot

A personal Telegram bot that manages the qBittorrent instance on your Mac and
searches your [HeBits](https://hebits.net) account — all from one chat: search
with posters and season navigation, add with tags and categories, track
downloads, star favorite series, and get pinged when a new episode drops.

## Features

- **Search HeBits** by typing any text — results are grouped by movie/show,
  filterable (🌐 All / 🎬 Movies / 📺 Series) with page navigation. Tap a
  result for a detail card with the poster, Hebrew + English titles, an IMDB
  link, and one download button per release. TV shows are organized by season
  (newest first, season packs on top) with season buttons and paging built in
- **Add** via search, magnet link, or `.torrent` file — every add walks
  through a tag → category flow (existing, new, or none) to keep the library
  tidy
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
- **Settings** — `/settings` shows status (snapshot age, favorites, cookie)
  with maintenance buttons and **configurable intervals** (1–24 h, default
  3 h) for the two background jobs: qBittorrent snapshot refresh and the
  episode check. Changes apply immediately and persist
- **Button bar** — a persistent reply keyboard (📚 List · ⭐ Favorites ·
  🆕 Check · 🏷 Tags · 📁 Categories · ⚙️ Settings) makes daily use
  tap-only; typing is needed only for searches and naming new tags
- **Private** — the bot only serves the Telegram user IDs in
  `ALLOWED_USER_IDS`; anyone else gets a rejection message that includes
  their own user id, so adding a trusted person is as easy as having them
  message the bot and copying the id they're shown. All HeBits traffic
  (search, downloads, cover images) goes from your machine, never through
  Telegram's servers

## Project layout

```
bot.py                 entry point (python bot.py)
hebits_cookie.py       standalone cookie-capture helper
qbit_bot/
  config.py            env, paths, constants
  utils.py             formatting, episode parsing, info-hash
  storage.py           JSON stores: history, favorites, settings, snapshot
  qbit.py              qBittorrent client + live status decoration
  hebits.py            HeBits API: search, download, covers, cookie
  views.py             message texts and keyboards
  jobs.py              background loops (snapshot refresh, episode alerts)
  handlers.py          commands, callbacks, add flows
  main.py              application wiring
data/                  runtime state (git-ignored): history.json,
                       favorites.json, qbit_cache.json, bot_settings.json
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
2. Get your numeric user ID (e.g. from [@userinfobot](https://t.me/userinfobot))

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
`nohup .venv/bin/python bot.py >/tmp/qbit-bot.log 2>&1 &`.
