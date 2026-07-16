"""Environment, paths, and constants. Importing this module configures logging
and migrates legacy data files from the project root into data/."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
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

PAGE_SIZE = 8
SEARCH_RESULTS = 10

DEFAULT_SETTINGS = {"qbit_refresh_hours": 3, "fav_check_hours": 3}
INTERVAL_CHOICES = (1, 2, 3, 6, 12, 24)

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

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
