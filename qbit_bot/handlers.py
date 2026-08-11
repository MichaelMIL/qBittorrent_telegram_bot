"""Telegram command, message, and callback handlers."""

import asyncio
import html
import logging
from datetime import datetime, timezone
from functools import wraps

import qbittorrentapi
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from . import config
from .hebits import (
    HebitsError,
    hebits_download,
    hebits_search,
    hebits_whoami,
    save_hebits_cookie,
)
from .jobs import collect_new_episodes, watch_plex_scan
from .plex import PlexError, plex_refresh, plex_sections
from .qbit import decorate_local_status, fetch_qbit_torrents, qb
from .storage import (
    add_watch,
    get_notified,
    load_favorites,
    load_series_defaults,
    load_settings,
    record_history,
    remove_favorite,
    save_series_defaults,
    save_setting,
    set_favorite,
    update_favorite,
)
from .utils import episode_key, magnet_info_hash, torrent_info_hash
from .views import (
    MAIN_KEYBOARD,
    back_keyboard,
    build_add_cat_keyboard,
    build_add_tag_keyboard,
    build_detail,
    build_ds_cat_keyboard,
    build_ds_tag_keyboard,
    build_list,
    build_resolution_keyboard,
    build_search,
    build_tag_menu,
    build_use_default_keyboard,
    categories_overview,
    default_label,
    favorite_menu,
    favorites_overview,
    plex_library_picker,
    plex_map_overview,
    plex_overview,
    plex_section_label,
    search_detail,
    send_detail_card,
    settings_overview,
    tags_overview,
)

log = logging.getLogger("qbit-bot")

# ------------------------------------------------------------------ auth

def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id not in config.ALLOWED_USER_IDS:
            log.warning("Unauthorized access attempt from %s", user.id if user else "?")
            uid = user.id if user else "unknown"
            if update.callback_query:
                await update.callback_query.answer(
                    f"⛔ Not authorized. Your user id: {uid}", show_alert=True
                )
            elif update.message:
                await update.message.reply_text(
                    "⛔ You are not authorized to use this bot.\n"
                    f"Your Telegram user id is: <code>{uid}</code>\n"
                    "Ask the bot's owner to add it to ALLOWED_USER_IDS.",
                    parse_mode=ParseMode.HTML,
                )
            return
        try:
            return await func(update, context)
        except (HebitsError, PlexError) as e:
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


# ------------------------------------------------------------------ commands

@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🫡 <b>At your service!</b> I'm your personal torrent butler — I talk to "
        "qBittorrent and to your HeBits account so you never have to leave this chat.\n"
        "\n"
        "🔎 <b>Finding things</b>\n"
        "Just type a name (try <i>fauda</i>) and I'll search HeBits — filter "
        "🎬 movies / 📺 series, flip through seasons, and see every release with "
        "its resolution, size and seeders. Magnet links and .torrent files work too.\n"
        "\n"
        "⬇️ <b>Adding things</b>\n"
        "Every add walks through a tiny flow: pick a 🏷 <b>tag</b>, then a 📁 "
        "<b>category</b>. That's how your library stays tidy — and how you find "
        "things again with /tags and /categories. After adding an episode, one "
        "tap 📌 saves that choice as the <b>series default</b> — the next "
        "episode then asks “use the default?” and adds instantly.\n"
        "\n"
        "🔔 <b>When it's done</b>\n"
        "I watch every download I add and message you the moment it's finished "
        "<i>and</i> the files are moved into place.\n"
        "\n"
        "🎞 <b>Plex</b>\n"
        "/plex (or the 🎞 Plex button) lists your Plex libraries — one tap "
        "scans a library, or all of them, for new files. Perfect right after "
        "a download-complete ping.\n"
        "\n"
        "📚 <b>Managing things</b>\n"
        "/list shows everything in qBittorrent — tap a torrent to pause, resume, "
        "re-tag, or delete it (with or without its files).\n"
        "\n"
        "⭐ <b>Favorites</b> (the good part)\n"
        "Star a series from its card, then /fav opens it in two taps. Every 3 "
        "hours I quietly check your favorites — when a new episode drops, I ping "
        "you with the available versions so you just tap the one you want. 🍿\n"
        "Or go fully hands-free: flip ⚡ <b>auto-add</b> on a favorite (in /fav) "
        "and I'll grab new episodes myself — best release in your preferred "
        "resolution, filed under the series default.\n"
        "\n"
        "🧭 <b>Marker cheat-sheet</b>\n"
        "🆓 freeleech · ✔️ snatched on HeBits · ✅ downloaded · ⏬ downloading · "
        "📥 added before, gone now\n"
        "\n"
        "⚙️ <b>/settings</b> — status &amp; maintenance: refresh the qBittorrent "
        "list, check favorites for episodes, scan Plex libraries, tune the "
        "auto-check intervals.\n"
        "\n"
        "📖 /help — command cheat-sheet\n"
        "🛟 /cancel — bail out of any flow, no questions asked\n"
        "\n"
        "👇 The buttons below are always there — no typing needed.",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD,
    )


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>Command cheat-sheet</b>\n"
        "\n"
        "<b>Search &amp; add</b>\n"
        "/search &lt;name&gt; — search HeBits (or just type a name)\n"
        "🧲 send a magnet link or .torrent file to add it directly\n"
        "\n"
        "<b>Library</b>\n"
        "/list — browse &amp; manage torrents\n"
        "/tags — browse by tag\n"
        "/categories — browse by category\n"
        "\n"
        "<b>Favorites</b>\n"
        "/favorites or /fav — your starred series\n"
        "/check — scan favorites for new episodes now\n"
        "\n"
        "<b>Maintenance</b>\n"
        "/settings — status, auto-check intervals &amp; tools\n"
        "/plex — scan Plex libraries for new files\n"
        "/refresh — re-read the torrent list from qBittorrent\n"
        "/cookie — check or update the HeBits session cookie\n"
        "\n"
        "<b>Misc</b>\n"
        "/cancel — cancel the current flow\n"
        "/start — the full tour\n"
        "/help — this list",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KEYBOARD,
    )


@restricted
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await asyncio.to_thread(build_list, context, "a", 0)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await asyncio.to_thread(tags_overview, context)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await asyncio.to_thread(categories_overview, context)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def run_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    # NEVER attach the reply keyboard to a message that gets deleted or
    # edited away: clients tie the button bar to the message that carried it,
    # so deleting that message hides the bar. The placeholder stays bare and
    # is edited into the results.
    msg = await update.message.reply_text(f"🔎 Searching HeBits for “{query}”…")
    try:
        text, kb = await asyncio.to_thread(build_search, context, query, "a", 1)
    except Exception:
        try:
            await msg.delete()
        except Exception:
            pass
        raise  # the restricted() wrapper reports the error
    await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


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
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = settings_overview()
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_plex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = await asyncio.to_thread(plex_overview)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def start_plex_scan(message, context: ContextTypes.DEFAULT_TYPE, targets: list[dict]):
    """Trigger scans for the given sections, announce them, and watch until done."""
    for s in targets:
        await asyncio.to_thread(plex_refresh, s["key"])
    names = ", ".join(plex_section_label(s) for s in targets)
    status = await message.reply_text(f"🔍 Plex is scanning {names}…")
    context.application.create_task(watch_plex_scan(status, targets))


async def run_favorites_check(message) -> None:
    """Check all favorites for new episodes and report into the chat."""
    # bare placeholder — a deleted message must never carry the reply keyboard
    loading = await message.reply_text("⏳ Checking favorites for new episodes…")
    try:
        notifications = await asyncio.to_thread(collect_new_episodes)
    except Exception as e:
        await loading.edit_text(f"❌ Check failed: {e}")
        return
    if not notifications:
        await loading.edit_text("✅ No new episodes for your favorites.")
        return
    await loading.delete()
    for note in notifications:
        await message.reply_text(
            note["text"], reply_markup=note["kb"], parse_mode=ParseMode.HTML
        )


@restricted
async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_favorites_check(update.message)


@restricted
async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Refreshing the qBittorrent list…")
    try:
        torrents = await asyncio.to_thread(fetch_qbit_torrents)
    except Exception as e:
        await msg.edit_text(
            f"❌ Couldn't reach qBittorrent ({e.__class__.__name__}) — "
            "the last snapshot stays in place."
        )
        return
    done = sum(1 for t in torrents if t.progress >= 1)
    await msg.edit_text(
        f"✅ qBittorrent list refreshed — {len(torrents)} torrents, {done} completed."
    )


@restricted
async def cmd_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cookie = " ".join(context.args or []).strip()

    if not cookie:
        # status check
        if not config.HEBITS_COOKIE:
            await update.message.reply_text(
                "No HeBits cookie configured.\n\n"
                "Send: /cookie <Cookie header from your browser>\n"
                "(DevTools → Network → any hebits.net request → Request Headers → Cookie)\n\n"
                "Or run hebits_cookie.py to grab it from your browser automatically."
            )
            return
        user = await asyncio.to_thread(hebits_whoami, config.HEBITS_COOKIE)
        if user:
            await update.message.reply_text(f"✅ HeBits cookie is valid — logged in as “{user}”.")
        else:
            await update.message.reply_text(
                "❌ The stored HeBits cookie no longer works.\n"
                "Log in with a browser and send: /cookie <new Cookie header>"
            )
        return

    user = await asyncio.to_thread(hebits_whoami, cookie)
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
        for key in ("pending_add", "add_tag", "awaiting", "set_default", "default_setup")
    ]
    await update.message.reply_text(
        "Cancelled." if any(popped) else "Nothing to cancel.",
        reply_markup=MAIN_KEYBOARD,
    )


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
            await asyncio.to_thread(
                lambda: qb().torrents_add_tags(tags=tag, torrent_hashes=torrent_hash)
            )
            detail, kb = await asyncio.to_thread(build_detail, context, torrent_hash)
            await update.message.reply_text(
                f"✅ Tag “{tag}” added.\n\n{detail}", reply_markup=kb, parse_mode=ParseMode.HTML
            )
        elif kind == "new_tag_add":
            context.user_data["add_tag"] = tag
            await update.message.reply_text(
                f"🏷 Tag “{tag}” noted. Category?",
                reply_markup=await asyncio.to_thread(build_add_cat_keyboard, context),
            )
        elif kind == "new_cat_add":
            cat = text.strip()

            def _create():
                try:
                    qb().torrents_create_category(name=cat)
                except qbittorrentapi.exceptions.Conflict409Error:
                    pass  # category already exists — just use it

            await asyncio.to_thread(_create)
            await do_add(update, context, context.user_data.pop("add_tag", None), cat)
        elif kind in ("new_tag_ds", "new_cat_ds"):  # typed name in the ⚡ default wizard
            setup = context.user_data.get("default_setup")
            if not setup:
                await update.message.reply_text("Expired — tap ⚡ on the favorite again.")
                return
            if kind == "new_tag_ds":
                setup["tag"] = tag
                await update.message.reply_text(
                    f"🏷 “{tag}” noted. Now pick a 📁 category:",
                    reply_markup=await asyncio.to_thread(build_ds_cat_keyboard, context),
                )
            else:
                cat = text.strip()

                def _create_ds():
                    try:
                        qb().torrents_create_category(name=cat)
                    except qbittorrentapi.exceptions.Conflict409Error:
                        pass  # category already exists — just use it

                await asyncio.to_thread(_create_ds)
                setup["category"] = cat
                await update.message.reply_text(
                    f"📁 “{cat}” it is. 📐 Preferred resolution?",
                    reply_markup=build_resolution_keyboard("ds:r"),
                )
        return

    button_actions = {
        "📚 List": cmd_list,
        "⭐ Favorites": cmd_favorites,
        "🆕 Check": cmd_check,
        "🏷 Tags": cmd_tags,
        "📁 Categories": cmd_categories,
        "🎞 Plex": cmd_plex,
        "⚙️ Settings": cmd_settings,
    }
    if text in button_actions:
        await button_actions[text](update, context)
        return

    if text.startswith("magnet:"):
        context.user_data["pending_add"] = {"magnet": text}
        await update.message.reply_text(
            "🧲 Got the magnet link. Tag it?",
            reply_markup=await asyncio.to_thread(build_add_tag_keyboard, context),
        )
    elif config.HEBITS_COOKIE:
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
        reply_markup=await asyncio.to_thread(build_add_tag_keyboard, context),
        parse_mode=ParseMode.HTML,
    )


async def start_add_flow(message, context: ContextTypes.DEFAULT_TYPE, title: str):
    """Kick off the add flow for the pending torrent: offer the series default
    in one tap when there is one, otherwise start the tag → category flow."""
    pending = context.user_data.get("pending_add") or {}
    default = load_series_defaults().get(pending.get("gid") or "")
    if default:
        await message.reply_text(
            f"📄 <b>{html.escape(title)}</b>\n"
            f"📌 This series has a default: {default_label(default)}. Use it?",
            reply_markup=build_use_default_keyboard(default),
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"📄 <b>{html.escape(title)}</b>\nTag it?",
            reply_markup=await asyncio.to_thread(build_add_tag_keyboard, context),
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

    kwargs = {}
    if tag:
        kwargs["tags"] = tag
    if category:
        kwargs["category"] = category

    def _add():
        client = qb()
        if "magnet" in pending:
            return client.torrents_add(urls=pending["magnet"], **kwargs)
        return client.torrents_add(torrent_files=pending["file"], **kwargs)

    result = await asyncio.to_thread(_add)
    what = "magnet" if "magnet" in pending else pending.get("name", ".torrent file")

    if result == "Ok.":
        info_hash = None
        try:
            info_hash = (
                magnet_info_hash(pending["magnet"])
                if "magnet" in pending
                else torrent_info_hash(pending["file"])
            )
        except (ValueError, OSError) as e:
            log.warning("could not compute info-hash: %s", e)
        if pending.get("hebits_id") and "file" in pending and info_hash:
            try:
                record_history(pending["hebits_id"], info_hash, pending.get("name", ""))
            except OSError as e:
                log.warning("could not record download history: %s", e)

        # watch the torrent so the user is pinged once it's downloaded & moved
        watch_note = ""
        chat = (
            update_or_query.effective_chat
            if isinstance(update_or_query, Update)
            else update_or_query.message.chat if update_or_query.message else None
        )
        if info_hash and chat:
            try:
                add_watch(info_hash, pending.get("name", what), [chat.id])
                watch_note = "\n🔔 I'll message you when it's downloaded and in place."
            except OSError as e:
                log.warning("could not register completion watch: %s", e)

        parts = []
        if tag:
            parts.append(f"tag “{tag}”")
        if category:
            parts.append(f"category “{category}”")
        suffix = f" with {' and '.join(parts)}" if parts else ""

        # for an episode of a known series, offer to remember this choice
        kb = None
        gid = pending.get("gid")
        if gid and category and episode_key(pending.get("name", "")):
            existing = load_series_defaults().get(gid)
            if not existing or (existing.get("category"), existing.get("tag")) != (category, tag):
                context.user_data["set_default"] = {
                    "gid": gid,
                    "name": pending.get("series") or pending.get("name", ""),
                    "tag": tag,
                    "category": category,
                }
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                f"📌 Make 📁 “{category}” this series' default"[:60],
                                callback_data="df",
                            )
                        ]
                    ]
                )
        await reply(f"✅ Added {what}{suffix}.{watch_note}", reply_markup=kb)
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
        await render(*await asyncio.to_thread(tags_overview, context))
        return

    if data == "cats":
        await query.answer()
        await render(*await asyncio.to_thread(categories_overview, context))
        return

    action, _, rest = data.partition(":")

    if action == "l":  # list: l:<filter>:<page>  (filter: a | t<i> | c<i>)
        flt, _, page = rest.partition(":")
        await query.answer()
        await render(*await asyncio.to_thread(build_list, context, flt, int(page or 0)))

    elif action == "t":  # detail
        await query.answer()
        await render(*await asyncio.to_thread(build_detail, context, rest))

    elif action in ("p", "r"):  # pause / resume

        def _toggle_state():
            client = qb()
            if action == "p":
                client.torrents_pause(torrent_hashes=rest)
            else:
                client.torrents_resume(torrent_hashes=rest)

        await asyncio.to_thread(_toggle_state)
        await query.answer("Paused" if action == "p" else "Resumed")
        await render(*await asyncio.to_thread(build_detail, context, rest))

    elif action == "m":  # tag menu
        await query.answer()
        await render(*await asyncio.to_thread(build_tag_menu, context, rest))

    elif action == "g":  # toggle tag: g:<hash>:<idx>
        torrent_hash, _, idx = rest.partition(":")
        tags = context.bot_data.get("tags", [])
        i = int(idx)
        if i >= len(tags):
            await query.answer("Tag list changed, refreshing…")
        else:
            tag = tags[i]

            def _toggle_tag():
                client = qb()
                t = client.torrents_info(torrent_hashes=torrent_hash)
                current = {x.strip() for x in t[0].tags.split(",") if x.strip()} if t else set()
                if tag in current:
                    client.torrents_remove_tags(tags=tag, torrent_hashes=torrent_hash)
                    return f"Removed “{tag}”"
                client.torrents_add_tags(tags=tag, torrent_hashes=torrent_hash)
                return f"Added “{tag}”"

            await query.answer(await asyncio.to_thread(_toggle_tag))
        await render(*await asyncio.to_thread(build_tag_menu, context, torrent_hash))

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

        def _delete():
            client = qb()
            t = client.torrents_info(torrent_hashes=torrent_hash)
            client.torrents_delete(delete_files=with_files, torrent_hashes=torrent_hash)
            return t[0].name if t else "torrent"

        name = await asyncio.to_thread(_delete)
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
        text, kb = await asyncio.to_thread(build_search, context, q, cat, page)
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
                remove_favorite(gid)
                await query.answer("Removed from favorites")
            else:
                name = res["name_en"] or res["name_he"] or res["torrents"][0]["title"]
                if res["year"]:
                    name += f" ({res['year']})"
                set_favorite(
                    gid,
                    {
                        "name": name,
                        "query": res["name_en"] or res["name_he"],
                        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    },
                )
                await query.answer("⭐ Added to favorites")
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
            await query.answer()
            loading = await query.message.reply_text(
                f"⏳ Loading <b>{html.escape(entry['name'])}</b> from HeBits…",
                parse_mode=ParseMode.HTML,
            )
            try:
                groups, _ = await asyncio.to_thread(hebits_search, entry["query"])
                group = next((g for g in groups if str(g.get("gid")) == arg), None)
                if group is None:
                    await loading.edit_text(
                        f"Couldn't find “{entry['name']}” on HeBits anymore."
                    )
                    return
                await asyncio.to_thread(decorate_local_status, [group])
                context.user_data["search"] = [group]
                context.user_data["search_view"] = (entry["query"], "a", 1)
                await send_detail_card(query.message, group, 0)
            except (HebitsError, requests.RequestException) as e:
                await loading.edit_text(f"❌ Loading failed: {e}")
                return
            await loading.delete()

        elif sub == "l":  # back to the favorites list
            await query.answer()
            await render(*favorites_overview())

        elif sub == "a":  # per-favorite options menu
            if arg not in favorites:
                await query.answer("Not in favorites anymore.", show_alert=True)
                await render(*favorites_overview())
            else:
                await query.answer()
                await render(*favorite_menu(arg))

        elif sub == "g":  # toggle ⚡ auto-add
            entry = favorites.get(arg)
            if not entry:
                await query.answer("Not in favorites anymore.", show_alert=True)
                await render(*favorites_overview())
            elif entry.get("auto"):
                update_favorite(arg, auto=False)
                await query.answer("💤 Auto-add off — I'll just notify you.")
                await render(*favorite_menu(arg))
            else:
                default = load_series_defaults().get(arg)
                if not default or not default.get("category"):
                    # no default yet — walk through setting one right here
                    context.user_data["default_setup"] = {
                        "gid": arg,
                        "name": entry["name"],
                        "enable": True,
                    }
                    await query.answer()
                    await render(
                        f"⚡ <b>{html.escape(entry['name'])}</b> needs a default "
                        "before I can auto-add its episodes.\n\n"
                        "Pick a 🏷 tag for them:",
                        await asyncio.to_thread(build_ds_tag_keyboard, context),
                    )
                    return
                update_favorite(arg, auto=True)
                await query.answer(f"⚡ Auto-add on: {default_label(default)}"[:190])
                await render(*favorite_menu(arg))

        elif sub == "e":  # edit (or set) the series default
            entry = favorites.get(arg)
            if not entry:
                await query.answer("Not in favorites anymore.", show_alert=True)
                await render(*favorites_overview())
            else:
                context.user_data["default_setup"] = {
                    "gid": arg,
                    "name": entry["name"],
                    "enable": False,
                }
                await query.answer()
                await render(
                    f"✏️ <b>{html.escape(entry['name'])}</b> — set the default "
                    "for new episodes.\n\nPick a 🏷 tag:",
                    await asyncio.to_thread(build_ds_tag_keyboard, context),
                )

        elif sub == "c":  # check all favorites for new episodes right now
            await query.answer("Checking favorites…")
            await run_favorites_check(query.message)

        elif sub == "d":  # remove from the favorites list view
            if remove_favorite(arg):
                await query.answer("Removed")
            else:
                await query.answer()
            await render(*favorites_overview())

    elif action == "st":  # settings actions
        if rest == "q":  # refresh qBittorrent snapshot
            await query.answer("Refreshing…")
            try:
                torrents = await asyncio.to_thread(fetch_qbit_torrents)
                await query.answer(f"Refreshed: {len(torrents)} torrents")
            except Exception as e:
                await query.answer(
                    f"qBittorrent unreachable ({e.__class__.__name__})", show_alert=True
                )
            await render(*settings_overview())
        elif rest == "c":  # check favorites now
            await query.answer("Checking favorites…")
            await run_favorites_check(query.message)
        elif rest == "k":  # validate the HeBits cookie
            await query.answer("Validating…")
            msg = await query.message.reply_text("⏳ Validating the HeBits cookie…")
            user = (
                await asyncio.to_thread(hebits_whoami, config.HEBITS_COOKIE)
                if config.HEBITS_COOKIE
                else None
            )
            if user:
                await msg.edit_text(f"✅ Cookie valid — logged in as “{user}”.")
            else:
                await msg.edit_text(
                    "❌ Cookie missing or expired — send /cookie <new Cookie header>."
                )
        elif rest == "r":  # reload the view
            await query.answer()
            await render(*settings_overview())
        elif rest == "tp":  # toggle auto Plex scan after downloads
            enabled = not load_settings()["auto_plex_scan"]
            save_setting("auto_plex_scan", enabled)
            await query.answer(
                "🎞 Auto-scan on — I'll scan Plex after every finished download."
                if enabled
                else "Auto-scan off — completion pings get a scan button instead."
            )
            await render(*settings_overview())
        elif rest in ("iq", "if", "iw", "is"):  # expand a value picker
            await query.answer()
            await render(*settings_overview(picker=rest[1]))
        elif rest[:2] in ("sq", "sf", "sw", "ss") and rest[2:3] == ":":  # set a value
            kind, _, raw = rest.partition(":")
            key, toast = {
                "sq": ("qbit_refresh_hours", f"Refresh every {raw} h"),
                "sf": ("fav_check_hours", f"Episode check every {raw} h"),
                "sw": ("watch_poll_seconds", f"Completion check every {raw} s"),
                "ss": (
                    "stall_alert_hours",
                    f"Stuck alert after {raw} h" if raw != "0" else "Stuck alerts off",
                ),
            }[kind]
            save_setting(key, int(raw))
            await query.answer(toast)
            await render(*settings_overview())

    elif action == "pm":  # category→library map: pm:l | pm:c:<i> | pm:s:<i>:<key|all>
        sub, _, arg = rest.partition(":")
        if sub == "l":
            await query.answer()
            await render(*await asyncio.to_thread(plex_map_overview, context))
        elif sub == "c":
            await query.answer()
            await render(*await asyncio.to_thread(plex_library_picker, context, int(arg)))
        elif sub == "s":
            i_s, _, key = arg.partition(":")
            cats = context.bot_data.get("cats", [])
            i = int(i_s)
            if i >= len(cats):
                await query.answer("Category list changed — reloading…")
            else:
                plex_map = load_settings()["plex_map"]
                if key == "all":
                    plex_map.pop(cats[i], None)
                else:
                    plex_map[cats[i]] = key
                save_setting("plex_map", plex_map)
                await query.answer("Saved")
            await render(*await asyncio.to_thread(plex_map_overview, context))

    elif action == "px":  # Plex: px:l = library list, px:s:<key> = scan one, px:a = scan all
        sub, _, key = rest.partition(":")
        if sub in ("s", "a", "aq"):
            sections = await asyncio.to_thread(plex_sections)
            targets = sections if sub != "s" else [s for s in sections if s["key"] == key]
            if not targets:
                await query.answer("Library not found — reloading…", show_alert=True)
                await render(*await asyncio.to_thread(plex_overview))
                return
            plural = "ies" if len(targets) != 1 else "y"
            await query.answer(f"🔍 Scanning {len(targets)} librar{plural}")
            await start_plex_scan(query.message, context, targets)
            if sub == "aq":  # from a completion ping — keep its text, drop the button
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except BadRequest:
                    pass
            else:
                await render(*await asyncio.to_thread(plex_overview))
        else:
            await query.answer()
            await render(*await asyncio.to_thread(plex_overview))

    elif action == "nf":  # add a release from a new-episode notification
        tid = int(rest)
        await query.answer("Fetching .torrent…")
        data_bytes = await asyncio.to_thread(hebits_download, tid)
        meta = get_notified(tid)
        name = meta.get("title") or f"HeBits torrent #{tid}"
        context.user_data["pending_add"] = {
            "file": data_bytes,
            "name": name,
            "hebits_id": tid,
            "gid": meta.get("gid"),
            "series": meta.get("series", ""),
        }
        await start_add_flow(query.message, context, name)

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
        res = results[gi]
        t = res["torrents"][ti]
        await query.answer("Fetching .torrent…")
        data_bytes = await asyncio.to_thread(hebits_download, t["id"])
        context.user_data["pending_add"] = {
            "file": data_bytes,
            "name": t["title"],
            "hebits_id": t["id"],
            "gid": str(res.get("gid") or "") or None,
            "series": res["name_en"] or res["name_he"] or t["title"],
        }
        await start_add_flow(query.message, context, t["title"])

    elif action == "ud":  # series default prompt: y = use, n = manual, f = forget
        pending = context.user_data.get("pending_add")
        if not pending:
            await query.answer("Nothing pending — pick a release again.", show_alert=True)
            return
        if rest == "y":
            default = load_series_defaults().get(pending.get("gid") or "", {})
            await query.answer()
            await do_add(query, context, default.get("tag"), default.get("category"))
        elif rest in ("n", "f"):
            note = ""
            if rest == "f":
                defaults = load_series_defaults()
                if defaults.pop(pending.get("gid") or "", None) is not None:
                    save_series_defaults(defaults)
                note = "🗑 Default forgotten. "
                await query.answer("Default forgotten")
            else:
                await query.answer()
            await query.edit_message_text(
                f"📄 <b>{html.escape(pending.get('name', ''))}</b>\n{note}Tag it?",
                reply_markup=await asyncio.to_thread(build_add_tag_keyboard, context),
                parse_mode=ParseMode.HTML,
            )

    elif action == "df":  # make the last add the series default → ask for resolution
        info = context.user_data.get("set_default")
        if not info:
            await query.answer("Expired — add an episode again first.", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            f"📐 Preferred resolution for “{info['name']}”?\n"
            "⚡ Auto-add only grabs new episodes in this resolution; anything "
            "else is offered as a notification instead.",
            reply_markup=build_resolution_keyboard(),
        )

    elif action == "dr":  # resolution picked → save the series default
        info = context.user_data.pop("set_default", None)
        if not info:
            await query.answer("Expired — add an episode again first.", show_alert=True)
            return
        defaults = load_series_defaults()
        defaults[info["gid"]] = {
            "name": info["name"],
            "tag": info["tag"],
            "category": info["category"],
            "resolution": None if rest == "any" else rest,
        }
        save_series_defaults(defaults)
        await query.answer("📌 Default saved")
        await query.edit_message_text(
            f"📌 Default for “{info['name']}”: {default_label(defaults[info['gid']])}.\n"
            "Next episodes of this series add in one tap — or flip on ⚡ auto-add "
            "in /fav and I'll grab them for you."
        )

    elif action == "ds":  # set-a-default wizard from favorites: ds:t|c|r:<arg> | ds:x
        setup = context.user_data.get("default_setup")
        sub, _, arg = rest.partition(":")
        if sub == "x":
            setup = context.user_data.pop("default_setup", None)
            await query.answer("Cancelled")
            if setup:
                await render(*favorite_menu(setup["gid"]))
            else:
                await render(*favorites_overview())
            return
        if not setup:
            await query.answer("Expired — tap ⚡ on the favorite again.", show_alert=True)
            return
        if sub == "t":  # tag picked
            if arg == "new":
                context.user_data["awaiting"] = ("new_tag_ds",)
                await query.answer()
                await query.message.reply_text("Type the tag name (or /cancel):")
                return
            if arg == "none":
                setup["tag"] = None
            else:
                tags = context.bot_data.get("tags", [])
                i = int(arg)
                if i >= len(tags):
                    await query.answer("Tag list changed — pick again.")
                    await render(
                        "Pick a 🏷 tag:",
                        await asyncio.to_thread(build_ds_tag_keyboard, context),
                    )
                    return
                setup["tag"] = tags[i]
            await query.answer()
            await render(
                f"⚡ <b>{html.escape(setup['name'])}</b>\nNow pick a 📁 category "
                "(this is where auto-added episodes go):",
                await asyncio.to_thread(build_ds_cat_keyboard, context),
            )
        elif sub == "c":  # category picked
            if arg == "new":
                context.user_data["awaiting"] = ("new_cat_ds",)
                await query.answer()
                await query.message.reply_text("Type the category name (or /cancel):")
                return
            cats = context.bot_data.get("cats", [])
            i = int(arg)
            if i >= len(cats):
                await query.answer("Category list changed — pick again.")
                await render(
                    "Pick a 📁 category:",
                    await asyncio.to_thread(build_ds_cat_keyboard, context),
                )
                return
            setup["category"] = cats[i]
            await query.answer()
            await render(
                f"⚡ <b>{html.escape(setup['name'])}</b>\n📐 Preferred resolution? "
                "Auto-add only grabs episodes in this resolution:",
                build_resolution_keyboard("ds:r"),
            )
        elif sub == "r":  # resolution picked → save default + turn auto-add on
            context.user_data.pop("default_setup", None)
            if not setup.get("category"):
                await query.answer("Expired — tap ⚡ on the favorite again.", show_alert=True)
                return
            defaults = load_series_defaults()
            defaults[setup["gid"]] = {
                "name": setup["name"],
                "tag": setup.get("tag"),
                "category": setup["category"],
                "resolution": None if arg == "any" else arg,
            }
            save_series_defaults(defaults)
            if setup.get("enable"):
                update_favorite(setup["gid"], auto=True)
                await query.answer("📌 Default saved — ⚡ auto-add is on")
            else:
                await query.answer("📌 Default saved")
            await render(*favorite_menu(setup["gid"]))

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
                reply_markup=await asyncio.to_thread(build_add_cat_keyboard, context),
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
