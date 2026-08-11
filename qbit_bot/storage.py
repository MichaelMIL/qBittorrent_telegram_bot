"""JSON stores: download history, favorites, settings, qBittorrent snapshot,
completion watches, and per-series add defaults."""

import asyncio
import json
from datetime import datetime, timezone

from .config import (
    DEFAULT_SETTINGS,
    FAVORITES_PATH,
    HISTORY_PATH,
    NOTIFIED_PATH,
    QBIT_CACHE_PATH,
    SERIES_DEFAULTS_PATH,
    SETTINGS_PATH,
    WATCH_PATH,
)

# set when an interval changes so sleeping background loops wake immediately
interval_changed: asyncio.Event | None = None

def load_history() -> dict:
    """hebits torrent id (str) -> {hash, name, added}."""
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)


def save_setting(key: str, value) -> None:
    settings = load_settings()
    settings[key] = value
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=1)
    if interval_changed is not None:
        interval_changed.set()


async def sleep_interval(key: str) -> None:
    """Sleep for the configured interval; wake early if the interval changes."""
    seconds = load_settings()[key] * 3600
    if interval_changed is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(interval_changed.wait(), timeout=seconds)
        interval_changed.clear()
    except asyncio.TimeoutError:
        pass


def load_favorites() -> dict:
    """HeBits group id (str) -> {name, query, added}."""
    try:
        with open(FAVORITES_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_favorites(favorites: dict) -> None:
    with open(FAVORITES_PATH, "w") as f:
        json.dump(favorites, f, ensure_ascii=False, indent=1)


def load_watches() -> dict:
    """info-hash (str, lowercase) -> {name, chat_ids, added} of torrents whose
    completion should be announced."""
    try:
        with open(WATCH_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_watches(watches: dict) -> None:
    with open(WATCH_PATH, "w") as f:
        json.dump(watches, f, ensure_ascii=False, indent=1)


def add_watch(info_hash: str, name: str, chat_ids: list[int]) -> None:
    watches = load_watches()
    watches[info_hash.lower()] = {
        "name": name,
        "chat_ids": list(chat_ids),
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_watches(watches)


NOTIFIED_KEEP = 300


def record_notified(tid: int, meta: dict) -> None:
    """Persist a notified release's metadata (title, gid, series) so its add
    button keeps working across bot restarts. Oldest entries are pruned."""
    try:
        with open(NOTIFIED_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.pop(str(tid), None)  # re-insert at the end so it counts as newest
    data[str(tid)] = meta
    while len(data) > NOTIFIED_KEEP:
        del data[next(iter(data))]
    with open(NOTIFIED_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def get_notified(tid: int) -> dict:
    try:
        with open(NOTIFIED_PATH) as f:
            return json.load(f).get(str(tid), {})
    except (OSError, ValueError):
        return {}


def load_series_defaults() -> dict:
    """HeBits group id (str) -> {name, tag, category}."""
    try:
        with open(SERIES_DEFAULTS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_series_defaults(defaults: dict) -> None:
    with open(SERIES_DEFAULTS_PATH, "w") as f:
        json.dump(defaults, f, ensure_ascii=False, indent=1)


def record_history(hebits_id, info_hash: str, name: str) -> None:
    history = load_history()
    history[str(hebits_id)] = {
        "hash": info_hash,
        "name": name,
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)


class CachedTorrent:
    """Snapshot of a qBittorrent torrent, interchangeable with the live object."""

    def __init__(self, hash: str, name: str, progress: float):
        self.hash, self.name, self.progress = hash, name, progress


def save_qbit_cache(torrents) -> None:
    data = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "torrents": [
            {"hash": t.hash, "name": t.name, "progress": t.progress} for t in torrents
        ],
    }
    with open(QBIT_CACHE_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False)


def load_qbit_cache() -> list[CachedTorrent] | None:
    try:
        with open(QBIT_CACHE_PATH) as f:
            data = json.load(f)
        return [CachedTorrent(**t) for t in data["torrents"]]
    except (OSError, ValueError, TypeError, KeyError):
        return None
