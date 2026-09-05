"""FastAPI app factory + two ways to run it: inside the bot's event loop
(bot.py) or standalone with its own background jobs (web.py)."""

import asyncio
import contextlib
import logging
import socket
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from qbit_bot import config, storage
from qbit_bot.jobs import completion_notifier, favorites_episode_checker, qbit_cache_refresher

from . import agents, covers
from .api import install_error_handlers, public, router

log = logging.getLogger("qbit-web")


def create_app(run_jobs: bool) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # server-local tasks, both modes
        tasks = [asyncio.create_task(covers.sweeper()), asyncio.create_task(agents.watchdog())]
        if run_jobs:
            storage.interval_changed = asyncio.Event()
            tasks += [
                asyncio.create_task(qbit_cache_refresher()),
                asyncio.create_task(favorites_episode_checker(None)),
                asyncio.create_task(completion_notifier(None)),
            ]
        log.info("Web app: %s", "  ".join(urls()))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="qBittorrent web", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(  # lets `flutter run -d chrome` (another origin) talk to the API
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    install_error_handlers(app)
    app.include_router(public)
    app.include_router(router)

    if (config.WEB_BUILD_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(config.WEB_BUILD_DIR), html=True), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def no_build():
            return (
                "<h2>qBittorrent web API is running</h2>"
                "<p>The Flutter app isn't built yet. Run "
                "<code>cd webapp && flutter build web</code> and reload, or use "
                "<code>flutter run -d chrome</code> for development.</p>"
                '<p>API docs: <a href="/api/docs">/api/docs</a></p>'
            )

    return app


def urls() -> list[str]:
    """Where the web app is reachable — loopback plus the machine's LAN IPs."""
    hosts = ["localhost"]
    candidates = []
    try:  # works on macOS; on Linux the hostname often maps to 127.0.1.1 only
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except socket.gaierror:
        pass
    try:  # the interface that routes to the internet (no packet is sent)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            candidates.append(s.getsockname()[0])
    except OSError:
        pass
    for ip in candidates:
        if not ip.startswith("127.") and ip not in hosts:
            hosts.append(ip)
    port = config.WEB_PORT
    return [f"http://{h}:{port}" for h in hosts]


def _warn_if_open() -> None:
    if not config.ADMIN_PASSWORD and config.WEB_HOST not in ("127.0.0.1", "localhost"):
        log.warning(
            "ADMIN_PASSWORD is empty — anyone on your network can control qBittorrent "
            "through the web app. Set ADMIN_PASSWORD (and USER_PASSWORD) in .env."
        )


def make_server(telegram_app=None) -> uvicorn.Server:
    """A uvicorn server for the *current* loop (the Telegram bot's) that leaves
    the process signal handlers alone. Run it with `await server.serve()`; stop
    it with `server.should_exit = True` and await the same coroutine.
    `telegram_app` lets server-side alerts (NAS) reach Telegram too."""
    agents.telegram_app = telegram_app
    _warn_if_open()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(run_jobs=False),
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            log_level="warning",
        )
    )
    # uvicorn wants to own SIGINT/SIGTERM; python-telegram-bot already does
    server.install_signal_handlers = lambda: None  # uvicorn < 0.29
    server.capture_signals = contextlib.nullcontext  # uvicorn >= 0.29
    return server


async def serve_in_loop() -> None:
    """Run the web server on the current loop until cancelled."""
    await make_server().serve()


def main() -> None:
    _warn_if_open()
    uvicorn.run(
        create_app(run_jobs=True),
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info",
    )
