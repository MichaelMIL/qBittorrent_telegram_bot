"""Background loops: qBittorrent snapshot refresh, new-episode alerts (with
⚡ auto-add for favorites that have a series default), and download-completion
notifications."""

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application

from . import config
from .hebits import HebitsError, hebits_download, hebits_search
from .qbit import decorate_local_status, fetch_qbit_torrents, qb
from .storage import (
    add_watch,
    load_favorites,
    load_series_defaults,
    load_watches,
    record_history,
    record_notified,
    save_favorites,
    save_watches,
    sleep_interval,
)
from .utils import episode_key, episode_tag, fmt_size, torrent_info_hash
from .views import default_label

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


WATCH_POLL_SECONDS = 30
# torrent finished downloading but qBittorrent is still shuffling its files
SETTLING_STATES = ("moving", "checkingUP", "checkingResumeData")


async def completion_notifier(app: "Application"):
    """Background task: announce bot-added torrents once the download is
    complete AND qBittorrent has finished moving the files into place."""
    while True:
        await asyncio.sleep(WATCH_POLL_SECONDS)
        watches = load_watches()
        if not watches:
            continue
        try:
            torrents = await asyncio.to_thread(
                lambda: qb().torrents_info(torrent_hashes=list(watches))
            )
        except Exception as e:
            log.warning("completion check failed: %s", e)
            continue
        by_hash = {t.hash.lower(): t for t in torrents}
        changed = False
        for info_hash, entry in list(watches.items()):
            t = by_hash.get(info_hash)
            if t is None:
                # not in the client: either just added (metadata still coming
                # in) or deleted by the user — give up after a grace period
                try:
                    added = datetime.fromisoformat(entry["added"])
                except (KeyError, ValueError):
                    added = None
                if added is None or datetime.now(timezone.utc) - added > timedelta(minutes=10):
                    del watches[info_hash]
                    changed = True
                continue
            if t.progress >= 1 and t.state not in SETTLING_STATES:
                where = f"\n📁 {html.escape(t.category)}" if t.category else ""
                text = (
                    f"🏁 <b>{html.escape(t.name)}</b>\n"
                    f"Download complete — files are in their final location.{where}"
                )
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🎞 Scan Plex now", callback_data="px:aq")]]
                )
                # chat_id: pre-chat_ids watch entries from older bot versions
                recipients = entry.get("chat_ids") or [entry.get("chat_id")]
                sent = False
                for chat_id in filter(None, recipients):
                    try:
                        await app.bot.send_message(
                            chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb
                        )
                        sent = True
                    except Exception as e:
                        log.warning("completion notification failed: %s", e)
                if not sent:
                    continue  # keep the watch and retry next cycle
                log.info("completion announced: %s", t.name)
                del watches[info_hash]
                changed = True
        if changed:
            save_watches(watches)


def auto_add_new(new: list, default: dict, series: str) -> tuple[list, list]:
    """Auto-add the best release of each new episode of an ⚡ favorite.

    Only releases matching the series' preferred resolution qualify; an
    episode not (yet) out in that resolution — or whose add fails — is left
    for the regular pick-a-version notification. Returns (remaining, added).
    """
    by_key: dict[tuple, list[dict]] = {}
    for k, t in new:
        by_key.setdefault(k, []).append(t)  # seeders desc within an episode
    want = default.get("resolution")
    remaining, added = [], []
    for k in sorted(by_key, reverse=True):
        releases = by_key[k]
        pick = next((t for t in releases if not want or t["resolution"] == want), None)
        if pick is None:
            remaining += [(k, t) for t in releases]
            continue
        try:
            data = hebits_download(pick["id"])
            kwargs = {}
            if default.get("tag"):
                kwargs["tags"] = default["tag"]
            if default.get("category"):
                kwargs["category"] = default["category"]
            result = qb().torrents_add(torrent_files=data, **kwargs)
            if result != "Ok.":
                raise RuntimeError(f"qBittorrent said {result!r}")
        except Exception as e:
            log.warning("auto-add failed for %s: %s", pick["title"], e)
            remaining += [(k, t) for t in releases]
            continue
        log.info("auto-added %s (%s)", pick["title"], series)
        added.append(pick)
        try:
            info_hash = torrent_info_hash(data)
            record_history(pick["id"], info_hash, pick["title"])
            add_watch(info_hash, pick["title"], list(config.ALLOWED_USER_IDS))
        except (ValueError, OSError) as e:
            log.warning("auto-add bookkeeping failed for %s: %s", pick["title"], e)
    return remaining, added


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

        # ⚡ favorites: grab qualifying releases outright, announce the rest
        default = load_series_defaults().get(gid) if entry.get("auto") else None
        if default:
            new, added = auto_add_new(new, default, entry["name"])
            if added:
                lines = [
                    f"⚡ <b>{html.escape(entry['name'])}</b> — auto-added with "
                    f"{default_label(default)}:"
                ]
                for t in added:
                    lines.append(
                        f"• {episode_tag(t['title'])} · {t['resolution'] or '?'} · "
                        f"{fmt_size(t['size'])} · 🌱{t['seeders']}"
                    )
                notifications.append({"text": "\n".join(lines), "kb": None})
            if not new:
                continue

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
            record_notified(
                t["id"], {"title": t["title"], "gid": gid, "series": entry["name"]}
            )
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
