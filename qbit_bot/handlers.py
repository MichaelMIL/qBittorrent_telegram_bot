"""Telegram command, message, and callback handlers."""

import asyncio
import html
import logging
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
from .jobs import NOTIFIED_TITLES, collect_new_episodes
from .qbit import decorate_local_status, fetch_qbit_torrents, qb
from .storage import (
    load_favorites,
    record_history,
    save_favorites,
    save_setting,
)
from .utils import torrent_info_hash
from .views import (
    MAIN_KEYBOARD,
    back_keyboard,
    build_add_cat_keyboard,
    build_add_tag_keyboard,
    build_detail,
    build_list,
    build_search,
    build_tag_menu,
    categories_overview,
    favorites_overview,
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
        "things again with /tags and /categories.\n"
        "\n"
        "📚 <b>Managing things</b>\n"
        "/list shows everything in qBittorrent — tap a torrent to pause, resume, "
        "re-tag, or delete it (with or without its files).\n"
        "\n"
        "⭐ <b>Favorites</b> (the good part)\n"
        "Star a series from its card, then /fav opens it in two taps. Every 3 "
        "hours I quietly check your favorites — when a new episode drops, I ping "
        "you with the available versions so you just tap the one you want. 🍿\n"
        "\n"
        "🧭 <b>Marker cheat-sheet</b>\n"
        "🆓 freeleech · ✔️ snatched on HeBits · ✅ downloaded · ⏬ downloading · "
        "📥 added before, gone now\n"
        "\n"
        "⚙️ <b>/settings</b> — status &amp; maintenance: refresh the qBittorrent "
        "list, check favorites for episodes, tune the auto-check intervals.\n"
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
    text, kb = build_list(context, "a", 0)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = tags_overview(context)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@restricted
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = categories_overview(context)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def run_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    # The placeholder re-asserts the persistent button bar (some clients hide
    # it after typed input). Telegram forbids editing messages sent with a
    # reply keyboard, so the placeholder is deleted and results sent fresh.
    msg = await update.message.reply_text(
        f"🔎 Searching HeBits for “{query}”…", reply_markup=MAIN_KEYBOARD
    )
    try:
        text, kb = build_search(context, query, "a", 1)
    finally:
        try:
            await msg.delete()
        except Exception:
            pass
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


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


async def run_favorites_check(message) -> None:
    """Check all favorites for new episodes and report into the chat."""
    # sent with the reply keyboard, so it must be deleted, not edited
    loading = await message.reply_text(
        "⏳ Checking favorites for new episodes…", reply_markup=MAIN_KEYBOARD
    )
    try:
        notifications = await asyncio.to_thread(collect_new_episodes)
    except Exception as e:
        await loading.delete()
        await message.reply_text(f"❌ Check failed: {e}")
        return
    await loading.delete()
    if not notifications:
        await message.reply_text("✅ No new episodes for your favorites.")
        return
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
        user = hebits_whoami(config.HEBITS_COOKIE)
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

    button_actions = {
        "📚 List": cmd_list,
        "⭐ Favorites": cmd_favorites,
        "🆕 Check": cmd_check,
        "🏷 Tags": cmd_tags,
        "📁 Categories": cmd_categories,
        "⚙️ Settings": cmd_settings,
    }
    if text in button_actions:
        await button_actions[text](update, context)
        return

    if text.startswith("magnet:"):
        context.user_data["pending_add"] = {"magnet": text}
        await update.message.reply_text(
            "🧲 Got the magnet link. Tag it?",
            reply_markup=build_add_tag_keyboard(context),
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
            await query.answer()
            loading = await query.message.reply_text(
                f"⏳ Loading <b>{html.escape(entry['name'])}</b> from HeBits…",
                parse_mode=ParseMode.HTML,
            )
            try:
                groups, _ = hebits_search(entry["query"])
                group = next((g for g in groups if str(g.get("gid")) == arg), None)
                if group is None:
                    await loading.edit_text(
                        f"Couldn't find “{entry['name']}” on HeBits anymore."
                    )
                    return
                decorate_local_status([group])
                context.user_data["search"] = [group]
                context.user_data["search_view"] = (entry["query"], "a", 1)
                await send_detail_card(query.message, group, 0)
            except (HebitsError, requests.RequestException) as e:
                await loading.edit_text(f"❌ Loading failed: {e}")
                return
            await loading.delete()

        elif sub == "c":  # check all favorites for new episodes right now
            await query.answer("Checking favorites…")
            await run_favorites_check(query.message)

        elif sub == "d":  # remove from the favorites list view
            if arg in favorites:
                del favorites[arg]
                save_favorites(favorites)
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
        elif rest in ("iq", "if"):  # expand an interval picker
            await query.answer()
            await render(*settings_overview(picker=rest[1]))
        elif rest.startswith("sq:") or rest.startswith("sf:"):  # set an interval
            kind, _, hours = rest.partition(":")
            key = "qbit_refresh_hours" if kind == "sq" else "fav_check_hours"
            save_setting(key, int(hours))
            await query.answer(f"Set to every {hours} h")
            await render(*settings_overview())

    elif action == "nf":  # add a release from a new-episode notification
        tid = int(rest)
        await query.answer("Fetching .torrent…")
        data_bytes = hebits_download(tid)
        name = NOTIFIED_TITLES.get(tid, f"HeBits torrent #{tid}")
        context.user_data["pending_add"] = {
            "file": data_bytes,
            "name": name,
            "hebits_id": tid,
        }
        await query.message.reply_text(
            f"📄 <b>{html.escape(name)}</b>\nTag it?",
            reply_markup=build_add_tag_keyboard(context),
            parse_mode=ParseMode.HTML,
        )

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
