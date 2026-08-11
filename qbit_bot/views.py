"""All message texts and keyboards the bot renders."""

import asyncio
import html
import json
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from . import config
from .config import (
    INTERVAL_CHOICES,
    PAGE_SIZE,
    QBIT_CACHE_PATH,
    SEARCH_RESULTS,
    STALL_ALERT_CHOICES,
    WATCH_POLL_CHOICES,
)
from .hebits import fetch_cover, hebits_search
from .plex import plex_sections
from .qbit import decorate_local_status, get_categories, get_tags, qb
from .storage import (
    load_favorites,
    load_history,
    load_series_defaults,
    load_settings,
    load_watches,
)
from .utils import (
    STATE_EMOJI,
    episode_tag,
    fmt_eta,
    fmt_size,
    local_mark,
    progress_bar,
    season_label,
    season_of,
)

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


def default_label(default: dict) -> str:
    """Human-readable '🏷 tag + 📁 category + 📐 res' summary of a series default."""
    return " + ".join(
        x
        for x in (
            f"🏷 {default['tag']}" if default.get("tag") else "",
            f"📁 {default['category']}" if default.get("category") else "",
            f"📐 {default['resolution']}" if default.get("resolution") else "",
        )
        if x
    )


RES_CHOICES = ("2160p", "1080p", "720p", "480p")


def build_resolution_keyboard(prefix: str = "dr") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(r, callback_data=f"{prefix}:{r}") for r in RES_CHOICES]]
    rows.append([InlineKeyboardButton("🌐 Any resolution", callback_data=f"{prefix}:any")])
    return InlineKeyboardMarkup(rows)


# keyboards for the set-a-default wizard launched from the favorites view

def build_ds_tag_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    tags = get_tags(context)
    rows = [
        [InlineKeyboardButton(f"🏷 {tag}", callback_data=f"ds:t:{i}")]
        for i, tag in enumerate(tags)
    ]
    rows.append(
        [
            InlineKeyboardButton("➕ New tag", callback_data="ds:t:new"),
            InlineKeyboardButton("No tag", callback_data="ds:t:none"),
        ]
    )
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="ds:x")])
    return InlineKeyboardMarkup(rows)


def build_ds_cat_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    cats = get_categories(context)
    rows = [
        [InlineKeyboardButton(f"📁 {cat}", callback_data=f"ds:c:{i}")]
        for i, cat in enumerate(cats)
    ]
    rows.append([InlineKeyboardButton("➕ New category", callback_data="ds:c:new")])
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="ds:x")])
    return InlineKeyboardMarkup(rows)


def build_use_default_keyboard(default: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"✅ Use default ({default_label(default)})"[:60],
                    callback_data="ud:y",
                )
            ],
            [InlineKeyboardButton("🔧 Choose tag & category manually", callback_data="ud:n")],
            [
                InlineKeyboardButton("🗑 Forget default", callback_data="ud:f"),
                InlineKeyboardButton("✖️ Cancel", callback_data="at:cancel"),
            ],
        ]
    )


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


# persistent reply keyboard shown under the text box — taps are handled in
# on_text and routed to the matching command
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📚 List", "⭐ Favorites", "🆕 Check"],
        ["🏷 Tags", "📁 Categories", "🎞 Plex"],
        ["⚙️ Settings"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


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


SEARCH_FILTERS = [("a", "🌐 All"), ("1", "🎬 Movies"), ("2", "📺 Series")]


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
        img = await asyncio.to_thread(fetch_cover, res["cover"])
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
    footer = [InlineKeyboardButton("🆕 Check episodes", callback_data="fv:c")]
    if not favorites:
        return (
            "No favorites yet. Open a series from a search and tap ⭐ Add to favorites.",
            InlineKeyboardMarkup([footer]),
        )
    rows = []
    for gid, entry in sorted(favorites.items(), key=lambda kv: kv[1]["name"].lower()):
        name = entry["name"] if len(entry["name"]) <= 24 else entry["name"][:23] + "…"
        rows.append(
            [
                InlineKeyboardButton(f"⭐ {name}", callback_data=f"fv:o:{gid}"),
                InlineKeyboardButton(
                    "⚡" if entry.get("auto") else "💤", callback_data=f"fv:a:{gid}"
                ),
                InlineKeyboardButton("🗑", callback_data=f"fv:d:{gid}"),
            ]
        )
    rows.append(footer)
    text = (
        "⭐ <b>Favorites</b> — tap to open:\n"
        "⚡ auto-adds new episodes · 💤 just notifies — tap the icon for "
        "options (toggle, edit default)"
    )
    return text, InlineKeyboardMarkup(rows)


def favorite_menu(gid: str) -> tuple[str, InlineKeyboardMarkup]:
    """Per-favorite options: auto-add toggle and the series default."""
    entry = load_favorites().get(gid)
    if entry is None:
        return favorites_overview()
    default = load_series_defaults().get(gid)
    auto = bool(entry.get("auto"))
    lines = [
        f"⭐ <b>{html.escape(entry['name'])}</b>",
        "",
        f"📌 Default: {default_label(default) if default else 'not set'}",
        f"⚡ Auto-add: {'on — new episodes are grabbed automatically' if auto else 'off — new episodes just notify'}",
    ]
    rows = [
        [
            InlineKeyboardButton(
                "💤 Turn auto-add off" if auto else "⚡ Turn auto-add on",
                callback_data=f"fv:g:{gid}",
            )
        ],
        [
            InlineKeyboardButton(
                "✏️ Edit default" if default else "📌 Set default",
                callback_data=f"fv:e:{gid}",
            )
        ],
        [InlineKeyboardButton("« Favorites", callback_data="fv:l")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


RELEASES_PER_PAGE = 10


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
        tech = t["resolution"] or t["container"] or "?"
        ep = episode_tag(t["title"])
        if ep:
            tech = f"{ep} · {tech}"
        # icons lead: downloaded state (replaces ⬇️), freeleech/snatched, seeders
        label = (
            f"{local or '⬇️'}{marks} 🌱{t['seeders']} · "
            f"{n + 1}. {tech} · {fmt_size(t['size'])}"
        )
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


PLEX_TYPE_EMOJI = {"movie": "🎬", "show": "📺", "artist": "🎵", "photo": "🖼"}


def plex_section_label(section: dict) -> str:
    return f"{PLEX_TYPE_EMOJI.get(section['type'], '📁')} {section['title']}"


def plex_overview() -> tuple[str, InlineKeyboardMarkup]:
    sections = plex_sections()
    footer = [
        InlineKeyboardButton("🔄 Scan all", callback_data="px:a"),
        InlineKeyboardButton("🔃 Reload", callback_data="px:l"),
    ]
    if not sections:
        return "🎞 <b>Plex</b>\n\nNo libraries found.", InlineKeyboardMarkup([footer])
    rows = []
    for s in sections:
        state = " · ⏳ scanning…" if s["refreshing"] else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{plex_section_label(s)}{state}"[:60], callback_data=f"px:s:{s['key']}"
                )
            ]
        )
    rows.append(footer)
    return (
        "🎞 <b>Plex libraries</b> — tap one to scan it for new files:",
        InlineKeyboardMarkup(rows),
    )


def settings_overview(picker: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """Status summary + tunable settings + maintenance actions.

    picker: 'q'/'f'/'w'/'s' expands the value-picker row for that setting.
    """
    settings = load_settings()
    try:
        with open(QBIT_CACHE_PATH) as f:
            cache = json.load(f)
        updated = datetime.fromisoformat(cache["updated"])
        age = datetime.now(timezone.utc) - updated
        mins = int(age.total_seconds() // 60)
        ago = f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago"
        snapshot = f"{len(cache['torrents'])} torrents · updated {ago}"
    except (OSError, ValueError, KeyError):
        snapshot = "no snapshot yet"

    lines = [
        "⚙️ <b>Settings &amp; status</b>",
        "",
        f"🗄 qBittorrent snapshot: {snapshot}",
        f"⭐ Favorites: {len(load_favorites())}",
        f"🧾 Bot-added torrents on record: {len(load_history())}",
        f"🔔 Downloads being watched: {len(load_watches())}",
        f"📌 Series with a default category: {len(load_series_defaults())}",
        f"🍪 HeBits cookie: {'configured' if config.HEBITS_COOKIE else '❗ not set'}",
        f"🎞 Plex: {config.PLEX_URL} · {'token' if config.PLEX_TOKEN else 'LAN no-auth'}",
        "",
        "🎛 Tap a setting to change it:",
    ]

    def picker_row(kind: str, current, choices, fmt) -> list[InlineKeyboardButton]:
        return [
            InlineKeyboardButton(
                f"•{fmt(v)}" if v == current else fmt(v),
                callback_data="noop" if v == current else f"st:s{kind}:{v}",
            )
            for v in choices
        ]

    hours = lambda v: f"{v}h"
    stall_hours = settings["stall_alert_hours"]
    rows = [
        [
            InlineKeyboardButton(
                f"🗄 qBittorrent refresh: every {settings['qbit_refresh_hours']} h",
                callback_data="st:iq",
            )
        ]
    ]
    if picker == "q":
        rows.append(picker_row("q", settings["qbit_refresh_hours"], INTERVAL_CHOICES, hours))
    rows.append(
        [
            InlineKeyboardButton(
                f"⭐ Episode check: every {settings['fav_check_hours']} h",
                callback_data="st:if",
            )
        ]
    )
    if picker == "f":
        rows.append(picker_row("f", settings["fav_check_hours"], INTERVAL_CHOICES, hours))
    rows.append(
        [
            InlineKeyboardButton(
                f"🔔 Completion check: every {settings['watch_poll_seconds']} s",
                callback_data="st:iw",
            )
        ]
    )
    if picker == "w":
        rows.append(
            picker_row("w", settings["watch_poll_seconds"], WATCH_POLL_CHOICES, lambda v: f"{v}s")
        )
    rows.append(
        [
            InlineKeyboardButton(
                "🐌 Stuck-download alert: "
                + (f"after {stall_hours} h" if stall_hours else "off"),
                callback_data="st:is",
            )
        ]
    )
    if picker == "s":
        rows.append(
            picker_row(
                "s", stall_hours, STALL_ALERT_CHOICES, lambda v: f"{v}h" if v else "off"
            )
        )
    rows += [
        [
            InlineKeyboardButton(
                "🎞 Auto-scan Plex after downloads: "
                + ("✅ on" if settings["auto_plex_scan"] else "◻️ off"),
                callback_data="st:tp",
            )
        ],
        [InlineKeyboardButton("📁→🎞 Category → Plex library map", callback_data="pm:l")],
        [InlineKeyboardButton("🔄 Refresh qBittorrent list", callback_data="st:q")],
        [InlineKeyboardButton("🆕 Check favorites for episodes", callback_data="st:c")],
        [InlineKeyboardButton("🎞 Plex libraries", callback_data="px:l")],
        [InlineKeyboardButton("🍪 Validate HeBits cookie", callback_data="st:k")],
        [InlineKeyboardButton("🔃 Reload this view", callback_data="st:r")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def plex_map_overview(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    """Per-category Plex scan targets, used by auto-scan after downloads."""
    cats = get_categories(context)
    sections = plex_sections()
    by_key = {s["key"]: s for s in sections}
    plex_map = load_settings()["plex_map"]

    lines = [
        "📁→🎞 <b>Category → Plex library</b>",
        "",
        "When a download finishes, auto-scan only touches the library its "
        "category is mapped to (unmapped categories scan everything). "
        "Tap a category to change its target:",
    ]
    rows = []
    for i, cat in enumerate(cats):
        target = by_key.get(plex_map.get(cat))
        label = plex_section_label(target) if target else "🌐 all"
        rows.append(
            [InlineKeyboardButton(f"📁 {cat} → {label}"[:60], callback_data=f"pm:c:{i}")]
        )
    if not cats:
        lines.append("\nNo categories defined in qBittorrent yet.")
    rows.append([InlineKeyboardButton("« Settings", callback_data="st:r")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def plex_library_picker(
    context: ContextTypes.DEFAULT_TYPE, cat_idx: int
) -> tuple[str, InlineKeyboardMarkup]:
    cats = context.bot_data.get("cats", [])
    if cat_idx >= len(cats):
        return plex_map_overview(context)  # category cache changed — reload
    sections = plex_sections()
    rows = [
        [InlineKeyboardButton(plex_section_label(s), callback_data=f"pm:s:{cat_idx}:{s['key']}")]
        for s in sections
    ]
    rows.append([InlineKeyboardButton("🌐 All libraries", callback_data=f"pm:s:{cat_idx}:all")])
    rows.append([InlineKeyboardButton("« Back", callback_data="pm:l")])
    return (
        f"📁 <b>{html.escape(cats[cat_idx])}</b> — scan which Plex library "
        "when one of its downloads finishes?",
        InlineKeyboardMarkup(rows),
    )
