# qBittorrent Telegram Bot

Manage the qBittorrent instance on your Mac from Telegram: browse torrents by tag,
add via magnet link or `.torrent` file, toggle tags, pause/resume, and remove
torrents (optionally together with their downloaded files).

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

Existing data files are migrated from the project root into `data/`
automatically on first start.

## 1. Enable the qBittorrent Web UI (on the Mac)

1. Open qBittorrent → **Preferences** (⌘,) → **Web UI**
2. Check **Web User Interface (Remote control)**
3. Note the **port** (default `8080`) and set a **username / password**
4. If the bot runs on another machine, make sure the Mac is reachable on your
   LAN (System Settings → Network → note its IP, e.g. `192.168.1.50`) and that
   the macOS firewall allows incoming connections for qBittorrent.

Verify it works by opening `http://<mac-ip>:8080` in a browser.

## 2. Create the Telegram bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow the prompts → copy the **token**
2. Get your numeric Telegram user ID (e.g. message [@userinfobot](https://t.me/userinfobot))

## 3. Configure & run

```bash
cd qBittorrent_telegram_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your bot token, user ID, and qBittorrent host/credentials

python bot.py
```

The bot only responds to the user IDs listed in `ALLOWED_USER_IDS`.

## HeBits search (optional)

The bot can search your [HeBits](https://hebits.net) account and add results
directly. HeBits' login page uses a captcha, so the bot authenticates with your
browser session cookie (the same approach Jackett uses).

**Easiest — automatic capture from your browser:**

```bash
pip install browser_cookie3
python hebits_cookie.py
```

Log in at hebits.net first (tick *keep me logged in*), then run the script on
the machine where that browser lives. It finds the hebits.net cookies in
Firefox/Chrome/Brave/Edge/Safari, verifies the session against the HeBits API
(it prints your username on success), and writes `HEBITS_COOKIE` into `.env`.
If your browser locks its cookie database, close it and rerun. `--paste` skips
detection and lets you paste the Cookie header manually.

**Or from Telegram, no restart needed:**

1. Log in to hebits.net in your browser
2. DevTools (F12) → **Network** tab → reload → click any hebits.net request →
   **Request Headers** → copy the whole `Cookie` value
3. Send the bot: `/cookie <paste>` — it validates the session, saves it, and
   deletes your message so the cookie doesn't sit in the chat history

`/cookie` with no arguments checks whether the stored session is still valid.
When the cookie expires, search replies tell you exactly that — just repeat
either method.

## Usage

A **persistent button bar** sits under the text box (appears after /start):
📚 List · ⭐ Favorites · 🆕 Check · 🏷 Tags · 📁 Categories · ⚙️ Settings —
each tap runs the matching command, so day-to-day use needs no typing at all
(typing is only for searching and naming new tags/categories).

- **/list** — browse all torrents; tap one to see progress, pause/resume, tag, or delete it
- **/tags** — pick a tag to see only torrents with that tag
- **/categories** — pick a qBittorrent category to filter by
- **/search `<name>`** (or just type any text) — search HeBits, sorted by seeders,
  with 🌐 All / 🎬 Movies / 📺 Series filter buttons and page navigation. Results
  are **grouped by movie/show**: one entry per title showing how many releases
  exist and their resolutions (e.g. "4 releases (1080p / 4K)"), plus 🆓 freeleech
  and ✔️ already-snatched markers. Tap a number for a detail card with the
  **poster image**, Hebrew + English titles, an IMDB link, and **one download
  button per release** (episode · resolution · codec · size · seeders) — pick
  one and it goes into the tag → category add flow. TV shows are organized by
  **season** (newest first, episodes newest-first) with season buttons and page
  navigation built into the card
- **/favorites** (or **/fav**) — your starred series. Star any show from its
  detail card (⭐ Add to favorites); opening a favorite re-fetches it fresh so
  you land on the newest season with live download markers. Remove with 💔 on
  the card or 🗑 in the list. Stored in `favorites.json`
- **New-episode alerts** — every 3 hours the bot checks each favorite on HeBits;
  when a new episode or season pack appears it messages you with one button per
  available version (episode · resolution · size · seeders) — tap one and it
  goes into the usual tag → category add flow. Each episode is announced once
  (a per-favorite watermark in `favorites.json` tracks the newest seen episode;
  the first check after starring just records the current state silently)
- **/settings** — status overview (snapshot age, favorites count, cookie state)
  with maintenance buttons: refresh the qBittorrent list, check favorites for
  new episodes, validate the HeBits cookie. `/refresh` and `/check` are
  command shortcuts for the first two. The **auto-check intervals** (qBittorrent
  snapshot refresh and episode check) are configurable there too — pick
  1/2/3/6/12/24 hours per timer; changes apply immediately and persist in
  `bot_settings.json`
- **Download indicators** — search results are checked against qBittorrent's
  live torrent list: ⏬ 43% downloading, ✅ completed, 📥 added via the bot
  before but no longer in qBittorrent. Bot-added torrents match exactly by
  info-hash (recorded in `history.json`); anything else in qBittorrent matches
  by release name, so torrents added outside the bot are recognized too. ✔️
  still marks anything your HeBits account ever snatched
- **Send a magnet link** or a **`.torrent` file** — the bot asks for a tag, then a category (existing, new, or none), then adds it
- **Delete** always asks for confirmation and lets you choose *remove torrent only* or *remove + delete files*
- **/cancel** — abort a pending add or tag entry

## Run it permanently (optional)

If you run the bot on the Mac itself, keep it alive with `launchd`, or simply:

```bash
nohup python bot.py >/tmp/qbit-bot.log 2>&1 &
```

On Linux, a systemd user service works well:

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
