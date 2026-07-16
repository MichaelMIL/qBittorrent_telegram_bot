#!/usr/bin/env python3
"""Telegram bot for managing qBittorrent torrents (with tags) over the Web UI API."""

import asyncio
import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

import qbittorrentapi
import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

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
HEBITS_COOKIE = os.environ.get("HEBITS_COOKIE", "").strip()

PAGE_SIZE = 8
SEARCH_RESULTS = 10

HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")
QBIT_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qbit_cache.json")
QBIT_REFRESH_SECONDS = 3 * 3600
FAVORITES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favorites.json")

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("qbit-bot")


# ---------------------------------------------------------------- qBittorrent

def qb() -> qbittorrentapi.Client:
    client = qbittorrentapi.Client(**QBIT)
    client.auth_log_in()
    return client


STATE_EMOJI = {
    "downloading": "⬇️",
    "forcedDL": "⬇️",
    "metaDL": "🔍",
    "allocating": "⏳",
    "uploading": "🌱",
    "forcedUP": "🌱",
    "stalledUP": "✅",
    "stalledDL": "🐌",
    "pausedDL": "⏸",
    "stoppedDL": "⏸",
    "pausedUP": "☑️",
    "stoppedUP": "☑️",
    "queuedDL": "🕐",
    "queuedUP": "🕐",
    "checkingDL": "🔬",
    "checkingUP": "🔬",
    "checkingResumeData": "🔬",
    "error": "❌",
    "missingFiles": "❌",
    "moving": "📦",
}


def fmt_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def fmt_eta(seconds: int) -> str:
    if seconds >= 8640000:  # qBittorrent's "infinity"
        return "∞"
    h, m = divmod(seconds // 60, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def progress_bar(fraction: float, width: int = 10) -> str:
    filled = round(fraction * width)
    return "▓" * filled + "░" * (width - filled)


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


# ---------------------------------------------------------- download history

def torrent_info_hash(data: bytes) -> str:
    """v1 info-hash (sha1 hex, as qBittorrent reports it) of a .torrent file.

    Minimal bencode walk that finds the raw byte span of the top-level "info"
    dict — no external dependency needed.
    """

    def skip(i: int) -> int:
        c = data[i : i + 1]
        if c == b"i":
            return data.index(b"e", i) + 1
        if c in (b"l", b"d"):
            i += 1
            while data[i : i + 1] != b"e":
                i = skip(i)
            return i + 1
        colon = data.index(b":", i)
        return colon + 1 + int(data[i:colon])

    if data[:1] != b"d":
        raise ValueError("not a bencoded dict")
    i = 1
    while data[i : i + 1] != b"e":
        colon = data.index(b":", i)
        key_len = int(data[i:colon])
        key = data[colon + 1 : colon + 1 + key_len]
        i = colon + 1 + key_len
        j = skip(i)
        if key == b"info":
            return hashlib.sha1(data[i:j]).hexdigest()
        i = j
    raise ValueError("no info dict in torrent")


def load_history() -> dict:
    """hebits torrent id (str) -> {hash, name, added}."""
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


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


def record_history(hebits_id, info_hash: str, name: str) -> None:
    history = load_history()
    history[str(hebits_id)] = {
        "hash": info_hash,
        "name": name,
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ HeBits

HEBITS_CATS = {
    1: "🎬 Movies",
    2: "📺 TV",
    3: "🎭 Theater",
    4: "💻 Apps",
    5: "🎮 Games",
    6: "🎵 Music",
    7: "📖 Books",
    8: "🎬 Movie Packs",
    9: "🔞 Porn",
    10: "📦 Other",
}


class HebitsError(Exception):
    pass


def hebits_whoami(cookie: str) -> str | None:
    """Return the logged-in username if the cookie is valid, else None."""
    try:
        r = requests.get(
            f"{HEBITS_URL}/ajax.php",
            params={"action": "index"},
            headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        data = r.json()
        if data.get("status") == "success":
            return data["response"].get("username") or "(unknown)"
    except (requests.RequestException, ValueError):
        pass
    return None


def save_hebits_cookie(cookie: str) -> None:
    """Persist the cookie to .env and use it for this running process."""
    global HEBITS_COOKIE
    HEBITS_COOKIE = cookie
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = [l.rstrip("\n") for l in f if not l.startswith("HEBITS_COOKIE=")]
    lines.append(f"HEBITS_COOKIE={cookie}")
    with open(env_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def hebits_request(path: str, params: dict) -> requests.Response:
    if not HEBITS_COOKIE:
        raise HebitsError(
            "HeBits search isn't configured. Run hebits_cookie.py, or send:\n"
            "/cookie <your hebits.net Cookie header>"
        )
    r = requests.get(
        f"{HEBITS_URL}/{path}",
        params=params,
        headers={"Cookie": HEBITS_COOKIE, "User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    return r


EPISODE_RE = re.compile(r"[Ss](\d{1,2})[\s._-]?[Ee](\d{1,3})")
SEASON_RE = re.compile(r"[Ss](\d{1,2})(?![0-9Ee])")


def episode_key(title: str) -> tuple[int, int] | None:
    """(season, episode) parsed from a release name. Season packs (no episode
    number) get a high episode value so they rank first in newest-first order."""
    m = EPISODE_RE.search(title)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = SEASON_RE.search(title)
    if m:
        return int(m.group(1)), 999
    return None


def episode_tag(title: str) -> str:
    """Short 'S01E02' / 'S01' tag for display, or '' if none found."""
    m = EPISODE_RE.search(title)
    if m:
        return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    m = SEASON_RE.search(title)
    if m:
        return f"S{int(m.group(1)):02d}"
    return ""


def hebits_search(query: str, cat: str = "a", page: int = 1) -> tuple[list[dict], int]:
    """Search HeBits (Gazelle JSON API).

    cat: 'a' = all, or a HeBits category id ('1' movies, '2' series, …).
    Returns (flat list of torrent dicts, total pages).
    """
    params = {
        "action": "browse",
        "searchstr": query,
        "group_results": 1,
        "order_by": "seeders",
        "order_way": "desc",
        "page": page,
    }
    if cat != "a":
        params[f"filter_cat[{cat}]"] = 1
    r = hebits_request("ajax.php", params)
    try:
        data = r.json()
    except ValueError:
        raise HebitsError(
            "HeBits returned a non-JSON page — your cookie has probably expired. "
            "Log in with a browser and send /cookie <new Cookie header>."
        )
    if data.get("status") != "success":
        raise HebitsError(f"HeBits API error: {data.get('error', data.get('status'))}")

    groups = []
    for group in data["response"].get("results", []):
        raw_torrents = group.get("torrents") or ([group] if "torrentId" in group else [])
        torrents = []
        for t in raw_torrents:
            if "torrentId" not in t:
                continue
            torrents.append(
                {
                    "id": t["torrentId"],
                    "title": t.get("release") or group.get("groupName") or f"#{t['torrentId']}",
                    "resolution": t.get("resolution") or "",
                    "codec": t.get("codec") or "",
                    "container": t.get("container") or "",
                    "subs": t.get("subbing") or "",
                    "size": int(t.get("size") or 0),
                    "seeders": t.get("seeders", 0),
                    "leechers": t.get("leechers", 0),
                    "snatches": t.get("snatches", 0),
                    "free": bool(t.get("isFreeleech")),
                    "snatched": bool(t.get("hasSnatched")),
                }
            )
        if not torrents:
            continue
        # episodic groups sort newest first, with full-season packs at the top
        # of their season (S02 pack, S02E03, S02E02, …, then S01…; best-seeded
        # release first within the same episode); untagged releases go last
        if any(episode_key(t["title"]) for t in torrents):
            torrents.sort(
                key=lambda t: (*(episode_key(t["title"]) or (-1, -1)), t["seeders"] or 0),
                reverse=True,
            )
        else:
            torrents.sort(key=lambda t: t["seeders"] or 0, reverse=True)
        groups.append(
            {
                "gid": group.get("groupId"),
                "name_en": group.get("groupNameAlt") or "",
                "name_he": group.get("groupName") or "",
                "year": group.get("groupYear") or "",
                "cover": group.get("cover") or "",
                "imdb": group.get("catalogue") or "",
                "cat": HEBITS_CATS.get(group.get("categoryID"), ""),
                "torrents": torrents,
            }
        )
    return groups, int(data["response"].get("pages") or 1)


def fetch_cover(url: str) -> bytes | None:
    """Download a cover image from this machine (avoids Telegram's servers being
    geo-blocked by hosts like imgur/ibb). Returns None if it isn't a usable image.
    The HeBits cookie is only sent to hebits.net — never to third-party hosts."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
    }
    if urlparse(url).netloc.endswith("hebits.net"):
        headers["Cookie"] = HEBITS_COOKIE
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.ok and r.headers.get("content-type", "").startswith("image/") and r.content:
            return r.content
    except requests.RequestException:
        pass
    return None


def hebits_download(torrent_id: int) -> bytes:
    r = hebits_request("torrents.php", {"action": "download", "id": torrent_id})
    if not r.content.startswith(b"d"):  # .torrent files are bencoded dicts
        raise HebitsError(
            "HeBits didn't return a .torrent file — your cookie has probably expired. "
            "Log in with a browser and send /cookie <new Cookie header>."
        )
    return r.content


# ------------------------------------------------------------------ auth

def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in ALLOWED_USER_IDS:
            log.warning("Unauthorized access attempt from %s", user.id if user else "?")
            if update.callback_query:
                await update.callback_query.answer("Not authorized.", show_alert=True)
            elif update.message:
                await update.message.reply_text("⛔ You are not authorized to use this bot.")
            return
        try:
            return await func(update, context)
        except HebitsError as e:
            msg = f"❌ {e}"
            if update.callback_query:
                await update.callback_query.answer(msg[:190], show_alert=True)
            elif update.message:
                await update.message.reply_text(msg)
        except requests.RequestException as e:
            msg = f"❌ HeBits request failed: {e.__class__.__name__}"
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            elif update.message:
                await update.message.reply_text(msg)
        except qbittorrentapi.exceptions.APIConnectionError:
            msg = "❌ Can't reach qBittorrent. Is the Web UI enabled and the host reachable?"
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            elif update.message:
                await update.message.reply_text(msg)
        except qbittorrentapi.exceptions.LoginFailed:
            msg = "❌ qBittorrent login failed — check QBIT_USERNAME / QBIT_PASSWORD."
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            elif update.message:
                await update.message.reply_text(msg)

    return wrapper


# ------------------------------------------------------------------ views

def build_list(context: ContextTypes.DEFAULT_TYPE, flt: str, page: int):
    """Return (text, keyboard) for the torrent list view.

    flt: 'a' = all, 't<i>' = tag index, 'c<i>' = category index (into the caches).
    """
    client = qb()
    tags = get_tags(context, client)
    cats = get_categories(context, client)

    tag = cat = None
    if flt.startswith("t"):
        i = int(flt[1:])
        if i < len(tags):
            tag = tags[i]
    elif flt.startswith("c"):
        i = int(flt[1:])
        if i < len(cats):
            cat = cats[i]

    if tag:
        torrents = client.torrents_info(tag=tag)
        title = f"🏷 <b>{html.escape(tag)}</b>"
    elif cat:
        torrents = client.torrents_info(category=cat)
        title = f"📁 <b>{html.escape(cat)}</b>"
    else:
        torrents = client.torrents_info()
        title = "📚 <b>All torrents</b>"
    torrents = sorted(torrents, key=lambda t: t.added_on, reverse=True)
    if not torrents:
        text = f"{title}\n\nNothing here."
    else:
        text = f"{title} — {len(torrents)} torrent(s)\nSelect one to manage it:"

    pages = max(1, (len(torrents) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    chunk = torrents[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    rows = []
    for t in chunk:
        emoji = STATE_EMOJI.get(t.state, "❓")
        name = t.name if len(t.name) <= 35 else t.name[:34] + "…"
        rows.append(
            [InlineKeyboardButton(f"{emoji} {name} · {t.progress:.0%}", callback_data=f"t:{t.hash}")]
        )

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"l:{flt}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"l:{flt}:{page + 1}"))
        rows.append(nav)

    bottom = [InlineKeyboardButton("🔄 Refresh", callback_data=f"l:{flt}:{page}")]
    if tag or cat:
        bottom.append(InlineKeyboardButton("📚 All", callback_data="l:a:0"))
    bottom.append(InlineKeyboardButton("🏷 Tags", callback_data="tags"))
    bottom.append(InlineKeyboardButton("📁 Cats", callback_data="cats"))
    rows.append(bottom)

    context.user_data["last_list"] = (flt, page)
    return text, InlineKeyboardMarkup(rows)


def build_detail(context: ContextTypes.DEFAULT_TYPE, torrent_hash: str):
    client = qb()
    torrents = client.torrents_info(torrent_hashes=torrent_hash)
    if not torrents:
        return "Torrent not found (already removed?).", back_keyboard(context)
    t = torrents[0]

    emoji = STATE_EMOJI.get(t.state, "❓")
    tag_line = ", ".join(x.strip() for x in t.tags.split(",")) if t.tags else "—"
    lines = [
        f"{emoji} <b>{html.escape(t.name)}</b>",
        "",
        f"{progress_bar(t.progress)} {t.progress:.1%}",
        f"State: <code>{t.state}</code>",
        f"Size: {fmt_size(t.size)}",
        f"⬇️ {fmt_size(t.dlspeed)}/s   ⬆️ {fmt_size(t.upspeed)}/s",
        f"Ratio: {t.ratio:.2f}   ETA: {fmt_eta(t.eta)}",
        f"🏷 Tags: {html.escape(tag_line)}",
    ]
    if t.category:
        lines.append(f"📁 Category: {html.escape(t.category)}")

    paused = t.state in ("pausedDL", "pausedUP", "stoppedDL", "stoppedUP")
    play_pause = (
        InlineKeyboardButton("▶️ Resume", callback_data=f"r:{t.hash}")
        if paused
        else InlineKeyboardButton("⏸ Pause", callback_data=f"p:{t.hash}")
    )
    rows = [
        [play_pause, InlineKeyboardButton("🔄 Refresh", callback_data=f"t:{t.hash}")],
        [
            InlineKeyboardButton("🏷 Tags", callback_data=f"m:{t.hash}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"d:{t.hash}"),
        ],
        [back_button(context)],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def back_button(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardButton:
    tag_idx, page = context.user_data.get("last_list", ("a", 0))
    return InlineKeyboardButton("« Back to list", callback_data=f"l:{tag_idx}:{page}")


def back_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[back_button(context)]])


def build_tag_menu(context: ContextTypes.DEFAULT_TYPE, torrent_hash: str):
    client = qb()
    torrents = client.torrents_info(torrent_hashes=torrent_hash)
    if not torrents:
        return "Torrent not found.", back_keyboard(context)
    t = torrents[0]
    current = {x.strip() for x in t.tags.split(",") if x.strip()}
    tags = get_tags(context, client)

    rows = []
    for i, tag in enumerate(tags):
        mark = "✅" if tag in current else "◻️"
        rows.append([InlineKeyboardButton(f"{mark} {tag}", callback_data=f"g:{t.hash}:{i}")])
    rows.append([InlineKeyboardButton("➕ New tag", callback_data=f"nt:{t.hash}")])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"t:{t.hash}")])

    name = t.name if len(t.name) <= 60 else t.name[:59] + "…"
    text = f"🏷 Tags for <b>{html.escape(name)}</b>\nTap to toggle:"
    return text, InlineKeyboardMarkup(rows)


def build_add_tag_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    tags = get_tags(context)
    rows = [
        [InlineKeyboardButton(f"🏷 {tag}", callback_data=f"at:{i}")]
        for i, tag in enumerate(tags)
    ]
    rows.append(
        [
            InlineKeyboardButton("➕ New tag", callback_data="at:new"),
            InlineKeyboardButton("No tag", callback_data="at:none"),
        ]
    )
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="at:cancel")])
    return InlineKeyboardMarkup(rows)


def build_add_cat_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    cats = get_categories(context)
    rows = [
        [InlineKeyboardButton(f"📁 {cat}", callback_data=f"ac:{i}")]
        for i, cat in enumerate(cats)
    ]
    rows.append(
        [
            InlineKeyboardButton("➕ New category", callback_data="ac:new"),
            InlineKeyboardButton("No category", callback_data="ac:none"),
        ]
    )
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="ac:cancel")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------------ commands

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>qBittorrent bot</b>\n\n"
        "• /list — browse &amp; manage torrents\n"
        "• /tags — browse by tag\n"
        "• /categories — browse by category\n"
        "• /search &lt;name&gt; — search HeBits (or just type the name)\n"
        "• /favorites (or /fav) — your starred series, one tap away\n"
        "• /cookie — check or update the HeBits session cookie\n"
        "• Send a <b>magnet link</b> or a <b>.torrent file</b> to add a torrent\n"
        "• /cancel — cancel a pending action",
        parse_mode=ParseMode.HTML,
    )


@restricted
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = build_list(context, "a", 0)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = tags_overview(context)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


def tags_overview(context: ContextTypes.DEFAULT_TYPE):
    tags = get_tags(context)
    footer = [
        InlineKeyboardButton("📚 All torrents", callback_data="l:a:0"),
        InlineKeyboardButton("📁 Categories", callback_data="cats"),
    ]
    if not tags:
        return "No tags yet. Add one from a torrent's tag menu.", InlineKeyboardMarkup([footer])
    rows = [
        [InlineKeyboardButton(f"🏷 {tag}", callback_data=f"l:t{i}:0")]
        for i, tag in enumerate(tags)
    ]
    rows.append(footer)
    return "🏷 <b>Tags</b> — pick one to filter:", InlineKeyboardMarkup(rows)


def categories_overview(context: ContextTypes.DEFAULT_TYPE):
    cats = get_categories(context)
    footer = [
        InlineKeyboardButton("📚 All torrents", callback_data="l:a:0"),
        InlineKeyboardButton("🏷 Tags", callback_data="tags"),
    ]
    if not cats:
        return "No categories defined in qBittorrent.", InlineKeyboardMarkup([footer])
    rows = [
        [InlineKeyboardButton(f"📁 {cat}", callback_data=f"l:c{i}:0")]
        for i, cat in enumerate(cats)
    ]
    rows.append(footer)
    return "📁 <b>Categories</b> — pick one to filter:", InlineKeyboardMarkup(rows)


@restricted
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = categories_overview(context)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


SEARCH_FILTERS = [("a", "🌐 All"), ("1", "🎬 Movies"), ("2", "📺 Series")]


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


def fetch_qbit_torrents():
    """Live torrent list from qBittorrent; refreshes the on-disk snapshot too."""
    torrents = qb().torrents_info()
    save_qbit_cache(torrents)
    return torrents


async def qbit_cache_refresher():
    """Background task: refresh the qBittorrent snapshot every few hours so
    search markers stay useful even when the client is briefly unreachable."""
    while True:
        try:
            torrents = await asyncio.to_thread(fetch_qbit_torrents)
            log.info("qBittorrent cache refreshed: %d torrents", len(torrents))
        except Exception as e:
            log.warning("qBittorrent cache refresh failed: %s", e)
        await asyncio.sleep(QBIT_REFRESH_SECONDS)


def normalize_name(name: str) -> str:
    """Normalize a release name for matching (dots/spaces/case don't matter)."""
    return re.sub(r"[\W_]+", "", name.lower())


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


def local_mark(t: dict) -> str:
    """Short status marker for a release the bot has downloaded before."""
    st = t.get("local")
    if not st:
        return ""
    if st[0] == "done":
        return "✅"
    if st[0] == "dl":
        return f"⏬{st[1]:.0%}"
    return "📥"  # added before: now gone from qBittorrent, or client unreachable


def build_search(context: ContextTypes.DEFAULT_TYPE, query: str, cat: str, page: int):
    """Run a HeBits search and return (text, keyboard) for the results view."""
    results, pages = hebits_search(query, cat=cat, page=page)
    results = results[:SEARCH_RESULTS]
    decorate_local_status(results)
    context.user_data["search"] = results
    context.user_data["search_view"] = (query, cat, page)

    filter_row = [
        InlineKeyboardButton(("• " if c == cat else "") + label, callback_data=f"f:{c}")
        for c, label in SEARCH_FILTERS
    ]

    if not results:
        return (
            f"🔎 No results on HeBits for “{html.escape(query)}”.",
            InlineKeyboardMarkup([filter_row]),
        )

    lines = [f"🔎 <b>{html.escape(query)}</b>", ""]
    for i, g in enumerate(results):
        ts = g["torrents"]
        name = g["name_en"] or g["name_he"] or ts[0]["title"]
        if g["year"]:
            name += f" ({g['year']})"
        if g["name_he"] and g["name_he"] not in name:
            name += f" — {g['name_he']}"
        marks = ""
        if any(t["free"] for t in ts):
            marks += " 🆓"
        if any(t["snatched"] for t in ts):
            marks += " ✔️"
        # strongest local status across the group's releases
        for status in ("done", "dl", "gone", "hist"):
            hit = next((t for t in ts if t.get("local", ("",))[0] == status), None)
            if hit:
                marks += f" {local_mark(hit)}"
                break
        if len(ts) == 1:
            t = ts[0]
            detail = " · ".join(x for x in (t["resolution"], fmt_size(t["size"])) if x)
            detail += f" · 🌱 {t['seeders']}"
        else:
            reso = " / ".join(sorted({t["resolution"] for t in ts if t["resolution"]}))
            detail = f"{len(ts)} releases ({reso}) · 🌱 {sum(t['seeders'] or 0 for t in ts)}"
        lines.append(
            f"<b>{i + 1}.</b> {html.escape(name)}\n"
            f"      {g['cat']} · {detail}{marks}"
        )
    lines.append("")
    lines.append(
        "Tap a number to pick a release.\n"
        "🆓 freeleech · ✔️ snatched · ✅ downloaded · ⏬ downloading · 📥 added before"
    )

    nums = [InlineKeyboardButton(str(i + 1), callback_data=f"sd:{i}") for i in range(len(results))]
    keyboard = [filter_row] + [nums[i : i + 5] for i in range(0, len(nums), 5)]

    if pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"sp:{page - 1}"))
        nav.append(InlineKeyboardButton(f"page {page}/{pages}", callback_data="noop"))
        if page < pages:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"sp:{page + 1}"))
        keyboard.append(nav)

    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def send_detail_card(message, res: dict, gi: int) -> None:
    """Send a detail card (poster if possible, text otherwise) as a new message."""
    caption, kb = search_detail(res, gi)
    if res["cover"]:
        # always download the image locally and upload the bytes — never
        # hand the URL to Telegram: its servers get geo-blocked by hosts
        # like imgur/ibb ("not viewable in your region" placeholders), and
        # tracker-related URLs shouldn't be fetched by third parties at all
        img = fetch_cover(res["cover"])
        if img:
            try:
                await message.reply_photo(
                    img, caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML
                )
                return
            except Exception:
                pass
    await message.reply_text(
        caption, reply_markup=kb, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


def favorites_overview() -> tuple[str, InlineKeyboardMarkup]:
    favorites = load_favorites()
    if not favorites:
        return (
            "No favorites yet. Open a series from a search and tap ⭐ Add to favorites.",
            InlineKeyboardMarkup([]),
        )
    rows = []
    for gid, entry in sorted(favorites.items(), key=lambda kv: kv[1]["name"].lower()):
        name = entry["name"] if len(entry["name"]) <= 32 else entry["name"][:31] + "…"
        rows.append(
            [
                InlineKeyboardButton(f"⭐ {name}", callback_data=f"fv:o:{gid}"),
                InlineKeyboardButton("🗑", callback_data=f"fv:d:{gid}"),
            ]
        )
    return "⭐ <b>Favorites</b> — tap to open:", InlineKeyboardMarkup(rows)


async def run_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    msg = await update.message.reply_text(f"🔎 Searching HeBits for “{query}”…")
    text, kb = build_search(context, query, "a", 1)
    await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


RELEASES_PER_PAGE = 10


def season_of(title: str) -> int:
    """Season number for bucketing; -1 for releases without an episode tag."""
    k = episode_key(title)
    return k[0] if k else -1


def season_label(season: int) -> str:
    return f"S{season:02d}" if season >= 0 else "Other"


def search_detail(
    group: dict, gi: int, season: int | None = None, page: int = 0
) -> tuple[str, InlineKeyboardMarkup]:
    """Caption + keyboard for one search result group.

    Releases are bucketed by season (newest season shown first) with page
    navigation inside a season; non-episodic groups get plain pagination.
    """
    torrents = group["torrents"]
    buckets: dict[int, list[tuple[int, dict]]] = {}
    for ti, t in enumerate(torrents):
        buckets.setdefault(season_of(t["title"]), []).append((ti, t))
    seasons = sorted(buckets, reverse=True)  # newest first, "Other" (-1) last

    if season is None or season not in buckets:
        season = seasons[0]
    items = buckets[season]
    pages = max(1, (len(items) + RELEASES_PER_PAGE - 1) // RELEASES_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * RELEASES_PER_PAGE : (page + 1) * RELEASES_PER_PAGE]

    header = group["name_en"] or group["name_he"] or torrents[0]["title"]
    if group["year"]:
        header += f" ({group['year']})"
    if group["name_he"] and group["name_he"] not in header:
        header += f" — {group['name_he']}"

    lines = [f"{group['cat'] or '📄'} <b>{html.escape(header)}</b>"]
    if group["imdb"]:
        lines.append(f'🔗 <a href="{html.escape(group["imdb"])}">IMDB</a>')
    lines.append("")
    where = f"{season_label(season)} — " if len(seasons) > 1 else ""
    paging = f" (page {page + 1}/{pages})" if pages > 1 else ""
    plural = "s" if len(items) != 1 else ""
    lines.append(f"<b>{where}{len(items)} release{plural}{paging} — pick one:</b>")

    # photo captions are capped at 1024 chars — only spell out each release
    # when the page is short; the buttons carry the key facts regardless
    detailed = len(chunk) <= 5
    rows = []
    for n, (ti, t) in enumerate(chunk):
        local = local_mark(t)
        marks = ("🆓" if t["free"] else "") + ("✔️" if t["snatched"] else "")
        if detailed:
            title = t["title"] if len(t["title"]) <= 55 else t["title"][:54] + "…"
            extra = f" · 💬 {t['subs']}" if t["subs"] else ""
            lines.append(
                f"\n<b>{n + 1}.</b> <code>{html.escape(title)}</code>\n"
                f"      🌱 {t['seeders']} / 🩸 {t['leechers']} · ⏬ {t['snatches']}{extra} {marks}{local}"
            )
        tech = " ".join(x for x in (t["resolution"], t["codec"]) if x) or t["container"] or "?"
        ep = episode_tag(t["title"])
        if ep:
            tech = f"{ep} · {tech}"
        # downloaded state replaces the ⬇️ icon so it's visible at a glance
        label = f"{local or '⬇️'} {n + 1}. {tech} · {fmt_size(t['size'])} · 🌱{t['seeders']} {marks}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"s:{gi}:{ti}")])

    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"sd:{gi}:{season}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data=f"sd:{gi}:{season}:{page + 1}"))
        rows.append(nav)

    if len(seasons) > 1:
        if len(seasons) <= 6:
            rows.append(
                [
                    InlineKeyboardButton(
                        ("• " if s == season else "") + season_label(s),
                        callback_data="noop" if s == season else f"sd:{gi}:{s}:0",
                    )
                    for s in seasons
                ]
            )
        else:
            si = seasons.index(season)
            nav = []
            if si < len(seasons) - 1:  # older season exists
                nav.append(
                    InlineKeyboardButton(
                        f"⬅️ {season_label(seasons[si + 1])}",
                        callback_data=f"sd:{gi}:{seasons[si + 1]}:0",
                    )
                )
            nav.append(InlineKeyboardButton(f"· {season_label(season)} ·", callback_data="noop"))
            if si > 0:  # newer season exists
                nav.append(
                    InlineKeyboardButton(
                        f"{season_label(seasons[si - 1])} ➡️",
                        callback_data=f"sd:{gi}:{seasons[si - 1]}:0",
                    )
                )
            rows.append(nav)

    is_fav = str(group.get("gid")) in load_favorites()
    fav_label = "💔 Remove favorite" if is_fav else "⭐ Add to favorites"
    rows.append(
        [
            InlineKeyboardButton(fav_label, callback_data=f"fv:t:{gi}:{season}:{page}"),
            InlineKeyboardButton("✖️ Close", callback_data="sx"),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(rows)


@restricted
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args or [])
    if not query:
        await update.message.reply_text("Usage: /search <name>\n(or just send me the name as a message)")
        return
    await run_search(update, context, query)


@restricted
async def cmd_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = favorites_overview()
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookie = " ".join(context.args or []).strip()

    if not cookie:
        # status check
        if not HEBITS_COOKIE:
            await update.message.reply_text(
                "No HeBits cookie configured.\n\n"
                "Send: /cookie <Cookie header from your browser>\n"
                "(DevTools → Network → any hebits.net request → Request Headers → Cookie)\n\n"
                "Or run hebits_cookie.py to grab it from your browser automatically."
            )
            return
        user = hebits_whoami(HEBITS_COOKIE)
        if user:
            await update.message.reply_text(f"✅ HeBits cookie is valid — logged in as “{user}”.")
        else:
            await update.message.reply_text(
                "❌ The stored HeBits cookie no longer works.\n"
                "Log in with a browser and send: /cookie <new Cookie header>"
            )
        return

    user = hebits_whoami(cookie)
    if not user:
        await update.message.reply_text(
            "❌ That cookie didn't work — HeBits doesn't recognize the session.\n"
            "Make sure you copied the whole Cookie header while logged in."
        )
        return

    save_hebits_cookie(cookie)
    # remove the message containing the session cookie from the chat
    try:
        await update.message.delete()
        await update.effective_chat.send_message(
            f"✅ Cookie saved — logged in as “{user}”. "
            "(I deleted your message so the cookie doesn't linger in the chat.)"
        )
    except Exception:
        await update.message.reply_text(f"✅ Cookie saved — logged in as “{user}”.")


@restricted
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    popped = [
        context.user_data.pop(key, None)
        for key in ("pending_add", "add_tag", "awaiting")
    ]
    await update.message.reply_text("Cancelled." if any(popped) else "Nothing to cancel.")


# ------------------------------------------------------------------ adding

@restricted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    awaiting = context.user_data.pop("awaiting", None)
    if awaiting:
        kind = awaiting[0]
        tag = text.replace(",", " ").strip()
        if kind == "new_tag_torrent":
            torrent_hash = awaiting[1]
            qb().torrents_add_tags(tags=tag, torrent_hashes=torrent_hash)
            detail, kb = build_detail(context, torrent_hash)
            await update.message.reply_text(
                f"✅ Tag “{tag}” added.\n\n{detail}", reply_markup=kb, parse_mode=ParseMode.HTML
            )
        elif kind == "new_tag_add":
            context.user_data["add_tag"] = tag
            await update.message.reply_text(
                f"🏷 Tag “{tag}” noted. Category?",
                reply_markup=build_add_cat_keyboard(context),
            )
        elif kind == "new_cat_add":
            cat = text.strip()
            try:
                qb().torrents_create_category(name=cat)
            except qbittorrentapi.exceptions.Conflict409Error:
                pass  # category already exists — just use it
            await do_add(update, context, context.user_data.pop("add_tag", None), cat)
        return

    if text.startswith("magnet:"):
        context.user_data["pending_add"] = {"magnet": text}
        await update.message.reply_text(
            "🧲 Got the magnet link. Tag it?",
            reply_markup=build_add_tag_keyboard(context),
        )
    elif HEBITS_COOKIE:
        # any other text is treated as a HeBits search
        await run_search(update, context, text)
    else:
        await update.message.reply_text(
            "Send a magnet link or a .torrent file, or use /list."
        )


@restricted
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not (doc.file_name or "").lower().endswith(".torrent"):
        await update.message.reply_text("That doesn't look like a .torrent file.")
        return
    file = await doc.get_file()
    data = bytes(await file.download_as_bytearray())
    context.user_data["pending_add"] = {"file": data, "name": doc.file_name}
    await update.message.reply_text(
        f"📄 Got <b>{html.escape(doc.file_name)}</b>. Tag it?",
        reply_markup=build_add_tag_keyboard(context),
        parse_mode=ParseMode.HTML,
    )


async def do_add(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    tag: str | None,
    category: str | None,
):
    """Add the pending torrent with optional tag and category. Works from message or callback."""
    pending = context.user_data.pop("pending_add", None)
    reply = (
        update_or_query.message.reply_text
        if isinstance(update_or_query, Update)
        else update_or_query.edit_message_text
    )
    if not pending:
        await reply("Nothing pending — send a magnet link or .torrent file first.")
        return

    client = qb()
    kwargs = {}
    if tag:
        kwargs["tags"] = tag
    if category:
        kwargs["category"] = category
    if "magnet" in pending:
        result = client.torrents_add(urls=pending["magnet"], **kwargs)
        what = "magnet"
    else:
        result = client.torrents_add(torrent_files=pending["file"], **kwargs)
        what = pending.get("name", ".torrent file")

    if result == "Ok.":
        if pending.get("hebits_id") and "file" in pending:
            try:
                record_history(
                    pending["hebits_id"],
                    torrent_info_hash(pending["file"]),
                    pending.get("name", ""),
                )
            except (ValueError, OSError) as e:
                log.warning("could not record download history: %s", e)
        parts = []
        if tag:
            parts.append(f"tag “{tag}”")
        if category:
            parts.append(f"category “{category}”")
        suffix = f" with {' and '.join(parts)}" if parts else ""
        await reply(f"✅ Added {what}{suffix}.")
    else:
        await reply(f"⚠️ qBittorrent rejected it ({result}). Duplicate torrent?")


# ------------------------------------------------------------------ callbacks

@restricted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    async def render(text, kb):
        try:
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            # e.g. tapping Refresh when nothing changed
            if "not modified" not in str(e).lower():
                raise

    if data == "noop":
        await query.answer()
        return

    if data == "tags":
        await query.answer()
        await render(*tags_overview(context))
        return

    if data == "cats":
        await query.answer()
        await render(*categories_overview(context))
        return

    action, _, rest = data.partition(":")

    if action == "l":  # list: l:<filter>:<page>  (filter: a | t<i> | c<i>)
        flt, _, page = rest.partition(":")
        await query.answer()
        await render(*build_list(context, flt, int(page or 0)))

    elif action == "t":  # detail
        await query.answer()
        await render(*build_detail(context, rest))

    elif action in ("p", "r"):  # pause / resume
        client = qb()
        if action == "p":
            client.torrents_pause(torrent_hashes=rest)
            await query.answer("Paused")
        else:
            client.torrents_resume(torrent_hashes=rest)
            await query.answer("Resumed")
        await render(*build_detail(context, rest))

    elif action == "m":  # tag menu
        await query.answer()
        await render(*build_tag_menu(context, rest))

    elif action == "g":  # toggle tag: g:<hash>:<idx>
        torrent_hash, _, idx = rest.partition(":")
        tags = context.bot_data.get("tags", [])
        i = int(idx)
        if i >= len(tags):
            await query.answer("Tag list changed, refreshing…")
        else:
            tag = tags[i]
            client = qb()
            t = client.torrents_info(torrent_hashes=torrent_hash)
            current = {x.strip() for x in t[0].tags.split(",") if x.strip()} if t else set()
            if tag in current:
                client.torrents_remove_tags(tags=tag, torrent_hashes=torrent_hash)
                await query.answer(f"Removed “{tag}”")
            else:
                client.torrents_add_tags(tags=tag, torrent_hashes=torrent_hash)
                await query.answer(f"Added “{tag}”")
        await render(*build_tag_menu(context, torrent_hash))

    elif action == "nt":  # new tag for torrent
        context.user_data["awaiting"] = ("new_tag_torrent", rest)
        await query.answer()
        await query.message.reply_text("Type the new tag name (or /cancel):")

    elif action == "d":  # delete confirmation
        await query.answer()
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🗑 Remove torrent only", callback_data=f"dc:{rest}:0")],
                [InlineKeyboardButton("💥 Remove + delete files", callback_data=f"dc:{rest}:1")],
                [InlineKeyboardButton("✖️ Cancel", callback_data=f"t:{rest}")],
            ]
        )
        await render("⚠️ <b>Delete this torrent?</b>\nThis cannot be undone.", kb)

    elif action == "dc":  # delete confirmed: dc:<hash>:<0|1>
        torrent_hash, _, flag = rest.partition(":")
        with_files = flag == "1"
        client = qb()
        t = client.torrents_info(torrent_hashes=torrent_hash)
        name = t[0].name if t else "torrent"
        client.torrents_delete(delete_files=with_files, torrent_hashes=torrent_hash)
        await query.answer("Deleted")
        note = " and its files were deleted" if with_files else " (files kept)"
        await render(
            f"🗑 <b>{html.escape(name)}</b> removed{note}.",
            back_keyboard(context),
        )

    elif action in ("f", "sp"):  # search filter / search page
        view = context.user_data.get("search_view")
        if not view:
            await query.answer("Search expired — type a new search.", show_alert=True)
            return
        q, cat, page = view
        if action == "f":
            cat, page = rest, 1
        else:
            page = int(rest)
        await query.answer()
        text, kb = build_search(context, q, cat, page)
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

    elif action == "sd":  # search result detail with poster + release picker
        results = context.user_data.get("search", [])
        parts = rest.split(":")
        i = int(parts[0])
        if i >= len(results):
            await query.answer("Search results expired — search again.", show_alert=True)
            return
        res = results[i]
        await query.answer()

        if len(parts) == 3:  # season/page navigation → edit the card in place
            caption, kb = search_detail(res, i, season=int(parts[1]), page=int(parts[2]))
            try:
                if query.message.photo:
                    await query.edit_message_caption(
                        caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML
                    )
                else:
                    await query.edit_message_text(
                        caption, reply_markup=kb, parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    raise
            return

        await send_detail_card(query.message, res, i)

    elif action == "fv":  # favorites: fv:t:<gi>:<season>:<page> | fv:o:<gid> | fv:d:<gid>
        sub, _, arg = rest.partition(":")
        favorites = load_favorites()

        if sub == "t":  # toggle favorite from a detail card
            gi_s, season_s, page_s = arg.split(":")
            results = context.user_data.get("search", [])
            gi = int(gi_s)
            if gi >= len(results):
                await query.answer("Search expired — search again.", show_alert=True)
                return
            res = results[gi]
            gid = str(res.get("gid"))
            if gid in favorites:
                del favorites[gid]
                await query.answer("Removed from favorites")
            else:
                name = res["name_en"] or res["name_he"] or res["torrents"][0]["title"]
                if res["year"]:
                    name += f" ({res['year']})"
                favorites[gid] = {
                    "name": name,
                    "query": res["name_en"] or res["name_he"],
                    "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                await query.answer("⭐ Added to favorites")
            save_favorites(favorites)
            caption, kb = search_detail(res, gi, season=int(season_s), page=int(page_s))
            try:
                if query.message.photo:
                    await query.edit_message_caption(
                        caption=caption, reply_markup=kb, parse_mode=ParseMode.HTML
                    )
                else:
                    await query.edit_message_text(
                        caption, reply_markup=kb, parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    raise

        elif sub == "o":  # open a favorite: fresh search, jump to its card
            entry = favorites.get(arg)
            if not entry:
                await query.answer("Not in favorites anymore.", show_alert=True)
                return
            await query.answer(f"Loading {entry['name']}…")
            groups, _ = hebits_search(entry["query"])
            group = next((g for g in groups if str(g.get("gid")) == arg), None)
            if group is None:
                await query.message.reply_text(
                    f"Couldn't find “{entry['name']}” on HeBits anymore."
                )
                return
            decorate_local_status([group])
            context.user_data["search"] = [group]
            context.user_data["search_view"] = (entry["query"], "a", 1)
            await send_detail_card(query.message, group, 0)

        elif sub == "d":  # remove from the favorites list view
            if arg in favorites:
                del favorites[arg]
                save_favorites(favorites)
                await query.answer("Removed")
            else:
                await query.answer()
            await render(*favorites_overview())

    elif action == "sx":  # close a search detail message
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            await query.edit_message_reply_markup(reply_markup=None)

    elif action == "s":  # release picked → download .torrent, start add flow
        gi_s, _, ti_s = rest.partition(":")
        results = context.user_data.get("search", [])
        gi, ti = int(gi_s), int(ti_s)
        if gi >= len(results) or ti >= len(results[gi]["torrents"]):
            await query.answer("Search results expired — search again.", show_alert=True)
            return
        t = results[gi]["torrents"][ti]
        await query.answer("Fetching .torrent…")
        data_bytes = hebits_download(t["id"])
        context.user_data["pending_add"] = {
            "file": data_bytes,
            "name": t["title"],
            "hebits_id": t["id"],
        }
        await query.message.reply_text(
            f"📄 <b>{html.escape(t['title'])}</b>\nTag it?",
            reply_markup=build_add_tag_keyboard(context),
            parse_mode=ParseMode.HTML,
        )

    elif action == "at":  # tag choice while adding (step 1 of 2)
        if rest == "cancel":
            context.user_data.pop("pending_add", None)
            context.user_data.pop("add_tag", None)
            await query.answer("Cancelled")
            await query.edit_message_text("✖️ Add cancelled.")
        elif rest == "new":
            context.user_data["awaiting"] = ("new_tag_add",)
            await query.answer()
            await query.edit_message_text("Type the tag name for this torrent (or /cancel):")
        else:
            if rest == "none":
                tag = None
            else:
                tags = context.bot_data.get("tags", [])
                i = int(rest)
                tag = tags[i] if i < len(tags) else None
            context.user_data["add_tag"] = tag
            await query.answer()
            label = f"🏷 “{tag}”" if tag else "No tag"
            await query.edit_message_text(
                f"{label}. Now pick a category:",
                reply_markup=build_add_cat_keyboard(context),
            )

    elif action == "ac":  # category choice while adding (step 2 of 2)
        if rest == "cancel":
            context.user_data.pop("pending_add", None)
            context.user_data.pop("add_tag", None)
            await query.answer("Cancelled")
            await query.edit_message_text("✖️ Add cancelled.")
        elif rest == "new":
            context.user_data["awaiting"] = ("new_cat_add",)
            await query.answer()
            await query.edit_message_text("Type the category name for this torrent (or /cancel):")
        else:
            if rest == "none":
                cat = None
            else:
                cats = context.bot_data.get("cats", [])
                i = int(rest)
                cat = cats[i] if i < len(cats) else None
            await query.answer()
            await do_add(query, context, context.user_data.pop("add_tag", None), cat)


# ------------------------------------------------------------------ main

def main():
    if not ALLOWED_USER_IDS:
        raise SystemExit("Set ALLOWED_USER_IDS in .env — the bot must not be open to everyone.")

    async def start_background_jobs(app_: Application):
        app_.create_task(qbit_cache_refresher())

    app = Application.builder().token(BOT_TOKEN).post_init(start_background_jobs).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("tags", cmd_tags))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("cookie", cmd_cookie))
    app.add_handler(CommandHandler("favorites", cmd_favorites))
    app.add_handler(CommandHandler("fav", cmd_favorites))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
