"""qBittorrent client access and live status decoration of search results."""

import logging

import qbittorrentapi
from telegram.ext import ContextTypes

from .config import QBIT
from .storage import load_history, load_qbit_cache, save_qbit_cache
from .utils import normalize_name

log = logging.getLogger("qbit-bot")

def qb() -> qbittorrentapi.Client:
    client = qbittorrentapi.Client(**QBIT)
    client.auth_log_in()
    return client


def get_tags(context: ContextTypes.DEFAULT_TYPE, client=None) -> list[str]:
    """Fetch all tags and cache them so callback data can use indices."""
    client = client or qb()
    tags = sorted(client.torrents_tags())
    context.bot_data["tags"] = tags
    return tags


def get_categories(context: ContextTypes.DEFAULT_TYPE, client=None) -> list[str]:
    """Fetch all categories and cache them so callback data can use indices."""
    client = client or qb()
    cats = sorted(client.torrents_categories())
    context.bot_data["cats"] = cats
    return cats


def fetch_qbit_torrents():
    """Live torrent list from qBittorrent; refreshes the on-disk snapshot too."""
    torrents = qb().torrents_info()
    save_qbit_cache(torrents)
    return torrents


def decorate_local_status(groups: list[dict]) -> None:
    """Mark releases that exist in qBittorrent with their live state.

    Matching is by info-hash for bot-added torrents (history.json) and by
    normalized release name for everything else in qBittorrent. Sets
    t["local"] to ("done",) | ("dl", progress) | ("gone",) | ("hist",) —
    "gone" = bot-added but no longer in the client, "hist" = bot-added and
    the client is unreachable.
    """
    history = load_history()
    torrents = [t for g in groups for t in g["torrents"]]
    if not torrents:
        return
    by_hash = by_name = None
    try:
        qbit_torrents = fetch_qbit_torrents()
    except Exception as e:
        log.warning("qBittorrent unreachable, using cached snapshot: %s", e)
        qbit_torrents = load_qbit_cache()
    if qbit_torrents is not None:
        by_hash = {q.hash: q for q in qbit_torrents}
        by_name = {normalize_name(q.name): q for q in qbit_torrents}
    for t in torrents:
        entry = history.get(str(t["id"]))
        if by_hash is None:
            if entry:
                t["local"] = ("hist",)
            continue
        qt = by_hash.get(entry["hash"]) if entry else None
        if qt is None:
            qt = by_name.get(normalize_name(t["title"]))
        if qt is not None:
            t["local"] = ("done",) if qt.progress >= 1 else ("dl", qt.progress)
        elif entry:
            t["local"] = ("gone",)
