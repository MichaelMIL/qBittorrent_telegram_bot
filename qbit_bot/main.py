"""Application wiring and entry point: the Telegram bot plus (unless
WEB_ENABLED=0) the web app's API server, both on one asyncio loop so they
share background jobs, the settings wake-up event and the HeBits cookie."""

import asyncio
import logging

from telegram import Update
from telegram.error import Conflict, NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
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
    cmd_plex,
    cmd_refresh,
    cmd_search,
    cmd_settings,
    cmd_start,
    cmd_tags,
    on_callback,
    on_document,
    on_text,
)
from .jobs import completion_notifier, favorites_episode_checker, qbit_cache_refresher

log = logging.getLogger("qbit-bot")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors that escape the handlers as one clear line each; PTB's
    polling loop retries by itself."""
    err = context.error
    if isinstance(err, Conflict):
        log.error(
            "Telegram says another instance of this bot is polling with the same "
            "token (%s). Stop the other copy — bot.py must run exactly once.", err
        )
    elif isinstance(err, NetworkError):
        log.warning("Telegram network error (will retry): %s", err)
    else:
        log.exception("Unhandled error while processing %s", update, exc_info=err)


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN in .env (or run `python web.py` for the web app only).")
    if not config.ALLOWED_USER_IDS:
        raise SystemExit("Set ALLOWED_USER_IDS in .env — the bot must not be open to everyone.")

    # background work owned by the bot: the three job loops and (optionally)
    # the web server. Started once the application is initialized, stopped —
    # and awaited — when it stops, so shutdown leaves no pending tasks behind.
    tasks: list[asyncio.Task] = []
    web: dict = {}

    async def start_background_jobs(app_: Application):
        storage.interval_changed = asyncio.Event()
        loop = asyncio.get_running_loop()
        tasks[:] = [
            loop.create_task(qbit_cache_refresher(), name="qbit-cache-refresher"),
            loop.create_task(favorites_episode_checker(app_), name="episode-checker"),
            loop.create_task(completion_notifier(app_), name="completion-notifier"),
        ]
        if config.WEB_ENABLED:
            from qbit_web.server import make_server

            web["server"] = make_server()
            web["task"] = loop.create_task(web["server"].serve(), name="web-server")

    async def stop_background_jobs(app_: Application):
        for t in tasks:
            t.cancel()
        pending = list(tasks)
        if web:
            web["server"].should_exit = True  # graceful: finishes the lifespan
            pending.append(web["task"])
        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), 10)
        except asyncio.TimeoutError:
            log.warning("background tasks did not stop within 10 s")
        tasks.clear()
        web.clear()

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(start_background_jobs)
        .post_stop(stop_background_jobs)
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
    app.add_handler(CommandHandler("plex", cmd_plex))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    log.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
