"""Application wiring and entry point."""

import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import config, storage
from .handlers import (
    cmd_cancel,
    cmd_categories,
    cmd_check,
    cmd_cookie,
    cmd_favorites,
    cmd_help,
    cmd_list,
    cmd_refresh,
    cmd_search,
    cmd_settings,
    cmd_start,
    cmd_tags,
    on_callback,
    on_document,
    on_text,
)
from .jobs import favorites_episode_checker, qbit_cache_refresher

log = logging.getLogger("qbit-bot")


def main():
    if not config.ALLOWED_USER_IDS:
        raise SystemExit("Set ALLOWED_USER_IDS in .env — the bot must not be open to everyone.")

    async def start_background_jobs(app_: Application):
        storage.interval_changed = asyncio.Event()
        app_.create_task(qbit_cache_refresher())
        app_.create_task(favorites_episode_checker(app_))

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(start_background_jobs)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("tags", cmd_tags))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("cookie", cmd_cookie))
    app.add_handler(CommandHandler("favorites", cmd_favorites))
    app.add_handler(CommandHandler("fav", cmd_favorites))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
