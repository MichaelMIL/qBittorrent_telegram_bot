"""Background loops: qBittorrent snapshot refresh and new-episode alerts."""

import asyncio
import html
import logging

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application

from . import config
from .hebits import HebitsError, hebits_search
from .qbit import decorate_local_status, fetch_qbit_torrents
from .storage import load_favorites, save_favorites, sleep_interval
from .utils import episode_key, episode_tag, fmt_size

log = logging.getLogger("qbit-bot")

async def qbit_cache_refresher():
    """Background task: refresh the qBittorrent snapshot every few hours so
    search markers stay useful even when the client is briefly unreachable."""
    while True:
        try:
            torrents = await asyncio.to_thread(fetch_qbit_torrents)
            log.info("qBittorrent cache refreshed: %d torrents", len(torrents))
        except Exception as e:
            log.warning("qBittorrent cache refresh failed: %s", e)
        await sleep_interval("qbit_refresh_hours")


# titles of releases we notified about, so the add-button flow can name them
NOTIFIED_TITLES: dict[int, str] = {}


def collect_new_episodes() -> list[dict]:
    """Check every favorite on HeBits for episodes newer than its watermark.

    Returns [{text, keyboard}] messages to send; updates each favorite's
    "last_ep" watermark so an episode is only announced once. On the first
    check of a favorite, just records the current newest episode silently.
    """
    favorites = load_favorites()
    notifications = []
    changed = False
    for gid, entry in favorites.items():
        try:
            groups, _ = hebits_search(entry["query"])
        except (HebitsError, requests.RequestException) as e:
            log.warning("favorites check failed for %s: %s", entry["name"], e)
            continue
        group = next((g for g in groups if str(g.get("gid")) == gid), None)
        if group is None:
            continue
        keyed = [
            (episode_key(t["title"]), t)
            for t in group["torrents"]
            if episode_key(t["title"])
        ]
        if not keyed:
            continue
        current_max = max(k for k, _ in keyed)
        stored = entry.get("last_ep")
        if stored is None:
            # baseline = newest episode the user already HAS (downloaded or
            # snatched), so an undownloaded newer episode is announced right
            # away; only with no downloads at all do we baseline to the site's
            # newest to avoid spamming the whole back-catalog
            decorate_local_status([group])
            have = [
                k
                for k, t in keyed
                if t.get("snatched") or (t.get("local") or ("",))[0] in ("done", "dl")
            ]
            stored = list(max(have)) if have else list(current_max)
            entry["last_ep"] = stored
            changed = True
            if tuple(stored) >= current_max:
                continue
        new = sorted(
            ((k, t) for k, t in keyed if k > tuple(stored)),
            key=lambda kt: (kt[0], kt[1]["seeders"] or 0),
            reverse=True,
        )
        if not new:
            continue
        entry["last_ep"] = list(current_max)
        changed = True

        episodes = sorted({episode_tag(t["title"]) for _, t in new}, reverse=True)
        plural = "s" if len(episodes) > 1 else ""
        lines = [
            f"🆕 <b>{html.escape(entry['name'])}</b> — new episode{plural}: "
            f"{', '.join(episodes)}",
            "",
            "Pick a version to add to qBittorrent:",
        ]
        rows = []
        for k, t in new[:12]:
            NOTIFIED_TITLES[t["id"]] = t["title"]
            tech = t["resolution"] or "?"
            marks = "🆓" if t["free"] else ""
            label = (
                f"⬇️{marks} 🌱{t['seeders']} · "
                f"{episode_tag(t['title'])} · {tech} · {fmt_size(t['size'])}"
            )
            rows.append([InlineKeyboardButton(label[:60], callback_data=f"nf:{t['id']}")])
        rows.append([InlineKeyboardButton("✖️ Dismiss", callback_data="sx")])
        notifications.append({"text": "\n".join(lines), "kb": InlineKeyboardMarkup(rows)})
    if changed:
        save_favorites(favorites)
    return notifications


async def favorites_episode_checker(app: "Application"):
    """Background task: every few hours, announce new episodes of favorites."""
    while True:
        try:
            notifications = await asyncio.to_thread(collect_new_episodes)
            for note in notifications:
                for uid in config.ALLOWED_USER_IDS:
                    await app.bot.send_message(
                        uid, note["text"], reply_markup=note["kb"], parse_mode=ParseMode.HTML
                    )
            if notifications:
                log.info("sent %d new-episode notification(s)", len(notifications))
        except Exception as e:
            log.warning("favorites episode check failed: %s", e)
        await sleep_interval("fav_check_hours")
