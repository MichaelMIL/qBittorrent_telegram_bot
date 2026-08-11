"""JSON stores: download history, favorites, settings, qBittorrent snapshot,
completion watches, and per-series add defaults.

Handlers run on the event loop while background jobs write from worker
threads, so every read-modify-write here happens under one process-wide
lock — cross-thread writers must use the composite helpers (add_watch,
update_favorite, …) instead of load → mutate → save."""

import asyncio
import json
import threading
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

_lock = threading.RLock()


def _load(path: str) -> dict:
    with _lock:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}


def _save(path: str, data: dict) -> None:
    with _lock:
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ settings

def load_settings() -> dict:
    return {**DEFAULT_SETTINGS, **_load(SETTINGS_PATH)}


def save_setting(key: str, value) -> None:
    with _lock:
        settings = load_settings()
        settings[key] = value
        _save(SETTINGS_PATH, settings)
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


# ------------------------------------------------------------------ history

def load_history() -> dict:
    """hebits torrent id (str) -> {hash, name, added}."""
    return _load(HISTORY_PATH)


def record_history(hebits_id, info_hash: str, name: str) -> None:
    with _lock:
        history = load_history()
        history[str(hebits_id)] = {
            "hash": info_hash,
            "name": name,
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _save(HISTORY_PATH, history)


# ------------------------------------------------------------------ favorites

def load_favorites() -> dict:
    """HeBits group id (str) -> {name, query, added, last_ep?, auto?}."""
    return _load(FAVORITES_PATH)


def save_favorites(favorites: dict) -> None:
    _save(FAVORITES_PATH, favorites)


def set_favorite(gid: str, entry: dict) -> None:
    with _lock:
        favorites = load_favorites()
        favorites[gid] = entry
        save_favorites(favorites)


def remove_favorite(gid: str) -> bool:
    with _lock:
        favorites = load_favorites()
        if favorites.pop(gid, None) is None:
            return False
        save_favorites(favorites)
        return True


def update_favorite(gid: str, **fields) -> None:
    """Atomically update fields of one favorite (no-op if it was removed)."""
    with _lock:
        favorites = load_favorites()
        entry = favorites.get(gid)
        if entry is None:
            return
        entry.update(fields)
        save_favorites(favorites)


# ------------------------------------------------------------------ watches

def load_watches() -> dict:
    """info-hash (str, lowercase) -> {name, chat_ids, added, alerted?,
    stalled_since?} of torrents whose completion should be announced."""
    return _load(WATCH_PATH)


def add_watch(info_hash: str, name: str, chat_ids: list[int]) -> None:
    with _lock:
        watches = load_watches()
        watches[info_hash.lower()] = {
            "name": name,
            "chat_ids": list(chat_ids),
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _save(WATCH_PATH, watches)


def remove_watch(info_hash: str) -> None:
    with _lock:
        watches = load_watches()
        if watches.pop(info_hash, None) is not None:
            _save(WATCH_PATH, watches)


def update_watch(info_hash: str, **fields) -> None:
    """Atomically set (or, with None, clear) marker fields on one watch."""
    with _lock:
        watches = load_watches()
        entry = watches.get(info_hash)
        if entry is None:
            return
        for key, value in fields.items():
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value
        _save(WATCH_PATH, watches)


# ------------------------------------------------------------------ notified

NOTIFIED_KEEP = 300


def record_notified(tid: int, meta: dict) -> None:
    """Persist a notified release's metadata (title, gid, series) so its add
    button keeps working across bot restarts. Oldest entries are pruned."""
    with _lock:
        data = _load(NOTIFIED_PATH)
        data.pop(str(tid), None)  # re-insert at the end so it counts as newest
        data[str(tid)] = meta
        while len(data) > NOTIFIED_KEEP:
            del data[next(iter(data))]
        _save(NOTIFIED_PATH, data)


def get_notified(tid: int) -> dict:
    return _load(NOTIFIED_PATH).get(str(tid), {})


# ------------------------------------------------------------------ defaults

def load_series_defaults() -> dict:
    """HeBits group id (str) -> {name, tag, category, resolution}."""
    return _load(SERIES_DEFAULTS_PATH)


def save_series_defaults(defaults: dict) -> None:
    _save(SERIES_DEFAULTS_PATH, defaults)


# ------------------------------------------------------------------ snapshot

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
    with _lock:
        with open(QBIT_CACHE_PATH, "w") as f:
            json.dump(data, f, ensure_ascii=False)


def load_qbit_cache() -> list[CachedTorrent] | None:
    with _lock:
        try:
            with open(QBIT_CACHE_PATH) as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
    try:
        return [CachedTorrent(**t) for t in data["torrents"]]
    except (ValueError, TypeError, KeyError):
        return None
