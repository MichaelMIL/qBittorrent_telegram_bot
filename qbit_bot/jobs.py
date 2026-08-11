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
from .plex import PlexError, plex_refresh, plex_sections
from .qbit import decorate_local_status, fetch_qbit_torrents, qb
from .storage import (
    add_watch,
    load_favorites,
    load_series_defaults,
    load_settings,
    load_watches,
    record_history,
    record_notified,
    remove_watch,
    sleep_interval,
    update_favorite,
    update_watch,
)
from .utils import (
    episode_key,
    episode_tag,
    fmt_duration,
    fmt_size,
    torrent_info_hash,
)
from .views import default_label, plex_section_label

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


# torrent finished downloading but qBittorrent is still shuffling its files
SETTLING_STATES = ("moving", "checkingUP", "checkingResumeData")
ERROR_STATES = ("error", "missingFiles")

# background tasks (Plex scan watchers) held here so they aren't GC'd mid-run
_bg_tasks: set = set()


def _bg(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _send_all(app: "Application", chat_ids, text: str, kb=None) -> list[int]:
    """Send a message to every chat; returns the ids that actually got it."""
    sent = []
    for chat_id in filter(None, chat_ids):
        try:
            await app.bot.send_message(
                chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb
            )
            sent.append(chat_id)
        except Exception as e:
            log.warning("notification to %s failed: %s", chat_id, e)
    return sent


PLEX_SCAN_POLL_SECONDS = 5
PLEX_SCAN_TIMEOUT = 3600


async def watch_plex_scan(message, targets: list[dict]) -> None:
    """Follow triggered Plex scans and update the status message when the
    libraries' `refreshing` flags clear."""
    keys = {s["key"] for s in targets}
    names = ", ".join(plex_section_label(s) for s in targets)
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        await asyncio.sleep(PLEX_SCAN_POLL_SECONDS)
        elapsed = loop.time() - started
        try:
            sections = await asyncio.to_thread(plex_sections)
        except PlexError as e:
            await message.edit_text(f"⚠️ Lost track of the Plex scan: {e}")
            return
        if not any(s["key"] in keys and s["refreshing"] for s in sections):
            await message.edit_text(
                f"✅ Plex finished scanning {names} ({fmt_duration(elapsed)})."
            )
            return
        if elapsed > PLEX_SCAN_TIMEOUT:
            await message.edit_text(
                f"⚠️ Plex is still scanning {names} after "
                f"{fmt_duration(elapsed)} — I'll stop watching it."
            )
            return


def resolve_scan_targets(sections: list[dict], category: str | None, plex_map: dict) -> list[dict]:
    """Sections to scan for a finished download: the library its category is
    mapped to, or every library when the category is unmapped."""
    key = (plex_map or {}).get(category or "")
    return [s for s in sections if s["key"] == key] or list(sections)


async def scan_after_completion(app: "Application", chat_ids: list[int], category: str | None):
    """Auto-scan Plex after a completed download and report into the chat(s)."""
    try:
        sections = await asyncio.to_thread(plex_sections)
        targets = resolve_scan_targets(sections, category, load_settings().get("plex_map"))
        for s in targets:
            await asyncio.to_thread(plex_refresh, s["key"])
    except PlexError as e:
        log.warning("auto Plex scan failed: %s", e)
        await _send_all(app, chat_ids, f"⚠️ Auto Plex scan failed: {e}")
        return
    names = ", ".join(plex_section_label(s) for s in targets)
    for chat_id in filter(None, chat_ids):
        try:
            msg = await app.bot.send_message(chat_id, f"🔍 Plex is scanning {names}…")
        except Exception as e:
            log.warning("scan status message to %s failed: %s", chat_id, e)
            continue
        _bg(watch_plex_scan(msg, targets))


async def completion_notifier(app: "Application"):
    """Background task: announce bot-added torrents once the download is
    complete AND qBittorrent has finished moving the files into place;
    also alert on errored or long-stalled downloads."""
    while True:
        await asyncio.sleep(load_settings()["watch_poll_seconds"])
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
        settings = load_settings()
        for info_hash, entry in watches.items():
            t = by_hash.get(info_hash)
            # chat_id: pre-chat_ids watch entries from older bot versions
            recipients = entry.get("chat_ids") or [entry.get("chat_id")]
            if t is None:
                # not in the client: either just added (metadata still coming
                # in) or deleted by the user — give up after a grace period
                try:
                    added = datetime.fromisoformat(entry["added"])
                except (KeyError, ValueError):
                    added = None
                if added is None or datetime.now(timezone.utc) - added > timedelta(minutes=10):
                    remove_watch(info_hash)
                continue

            if t.progress >= 1 and t.state not in SETTLING_STATES:
                where = f"\n📁 {html.escape(t.category)}" if t.category else ""
                text = (
                    f"🏁 <b>{html.escape(t.name)}</b>\n"
                    f"Download complete — files are in their final location.{where}"
                )
                auto_scan = settings["auto_plex_scan"]
                kb = None
                if not auto_scan:
                    kb = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🎞 Scan Plex now", callback_data="px:aq")]]
                    )
                sent = await _send_all(app, recipients, text, kb)
                if not sent:
                    continue  # keep the watch and retry next cycle
                log.info("completion announced: %s", t.name)
                remove_watch(info_hash)
                if auto_scan:
                    _bg(scan_after_completion(app, sent, t.category))
                continue

            # problem alerts (once per problem; cleared when it recovers)
            if t.state in ERROR_STATES:
                if entry.get("alerted") != "error":
                    await _send_all(
                        app,
                        recipients,
                        f"❌ <b>{html.escape(t.name)}</b> ran into a problem "
                        f"(state: <code>{t.state}</code>) — check qBittorrent.",
                    )
                    update_watch(info_hash, alerted="error")
                continue
            stall_hours = settings["stall_alert_hours"]
            if stall_hours and t.state == "stalledDL":
                since_s = entry.get("stalled_since")
                if not since_s:
                    update_watch(
                        info_hash,
                        stalled_since=datetime.now(timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                    )
                elif entry.get("alerted") != "stall":
                    try:
                        since = datetime.fromisoformat(since_s)
                    except ValueError:
                        continue
                    if datetime.now(timezone.utc) - since > timedelta(hours=stall_hours):
                        await _send_all(
                            app,
                            recipients,
                            f"🐌 <b>{html.escape(t.name)}</b> has been stalled at "
                            f"{t.progress:.0%} for over {stall_hours} h — no "
                            "connectable seeds? Check /list.",
                        )
                        update_watch(info_hash, alerted="stall")
            elif entry.get("stalled_since") or entry.get("alerted"):
                update_watch(info_hash, stalled_since=None, alerted=None)  # recovered


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
            update_favorite(gid, last_ep=stored)
            if tuple(stored) >= current_max:
                continue
        new = sorted(
            ((k, t) for k, t in keyed if k > tuple(stored)),
            key=lambda kt: (kt[0], kt[1]["seeders"] or 0),
            reverse=True,
        )
        if not new:
            continue
        update_favorite(gid, last_ep=list(current_max))

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
