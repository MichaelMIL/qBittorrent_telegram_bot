"""Environment, paths, and constants. Importing this module configures logging
and migrates legacy data files from the project root into data/."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()  # required by bot.py only
ALLOWED_USER_IDS = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()
}
QBIT = dict(
    host=os.environ.get("QBIT_HOST", "localhost"),
    port=int(os.environ.get("QBIT_PORT", "8080")),
    username=os.environ.get("QBIT_USERNAME", "admin"),
    password=os.environ.get("QBIT_PASSWORD", ""),
    VERIFY_WEBUI_CERTIFICATE=False,
)

HEBITS_URL = "https://hebits.net"
# mutable: /cookie updates it at runtime via hebits.save_hebits_cookie
HEBITS_COOKIE = os.environ.get("HEBITS_COOKIE", "").strip()

PLEX_URL = os.environ.get("PLEX_URL", "http://localhost:32400").rstrip("/")
PLEX_TOKEN = os.environ.get("PLEX_TOKEN", "").strip()

# web app (qbit_web): served by bot.py alongside Telegram, or alone by web.py
WEB_ENABLED = os.environ.get("WEB_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0").strip()
WEB_PORT = int(os.environ.get("WEB_PORT", "8765"))
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "").strip()  # empty = no login
# second password just for the web app's Settings tab (empty = settings open)
SETTINGS_PASSWORD = os.environ.get("SETTINGS_PASSWORD", "").strip()
# poster cache (data/covers): re-encoded JPEGs, LRU-evicted above CACHE_MAX_MB,
# wiped every CACHE_CLEAR_HOURS (0 = never); defaults 1 GiB / weekly
CACHE_CLEAR_HOURS = float(os.environ.get("CACHE_CLEAR_HOURS", "168") or 0)
CACHE_MAX_MB = float(os.environ.get("CACHE_MAX_MB", "1024") or 0)
CACHE_MAX_WIDTH = int(os.environ.get("CACHE_MAX_WIDTH", "500"))  # px, posters
CACHE_JPEG_QUALITY = int(os.environ.get("CACHE_JPEG_QUALITY", "82"))
WEB_BUILD_DIR = BASE_DIR / "webapp" / "build" / "web"

PAGE_SIZE = 8
SEARCH_RESULTS = 10

DEFAULT_SETTINGS = {
    "qbit_refresh_hours": 3,
    "fav_check_hours": 3,
    "watch_poll_seconds": 30,   # completion-watch polling
    "stall_alert_hours": 6,     # 0 = stuck-download alerts off
    "auto_plex_scan": False,    # scan Plex automatically after a download
    "plex_map": {},             # qBittorrent category -> Plex section key
}
INTERVAL_CHOICES = (1, 2, 3, 6, 12, 24)
WATCH_POLL_CHOICES = (15, 30, 60, 120)
STALL_ALERT_CHOICES = (0, 3, 6, 12, 24)

# runtime state lives in data/; move any legacy files from the project root
DATA_DIR.mkdir(exist_ok=True)
for _name in ("history.json", "favorites.json", "qbit_cache.json", "bot_settings.json"):
    _old, _new = BASE_DIR / _name, DATA_DIR / _name
    if _old.exists() and not _new.exists():
        _old.rename(_new)

HISTORY_PATH = str(DATA_DIR / "history.json")
FAVORITES_PATH = str(DATA_DIR / "favorites.json")
QBIT_CACHE_PATH = str(DATA_DIR / "qbit_cache.json")
SETTINGS_PATH = str(DATA_DIR / "bot_settings.json")
WATCH_PATH = str(DATA_DIR / "watch.json")
SERIES_DEFAULTS_PATH = str(DATA_DIR / "series_defaults.json")
NOTIFIED_PATH = str(DATA_DIR / "notified.json")
EVENTS_PATH = str(DATA_DIR / "events.json")
COVERS_DIR = Path(os.environ.get("COVERS_DIR") or DATA_DIR / "covers")

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
