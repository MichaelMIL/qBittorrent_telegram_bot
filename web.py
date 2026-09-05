#!/usr/bin/env python3
"""Entry point for the web app WITHOUT Telegram: serves the API + the built
Flutter app and runs the background jobs (snapshot refresh, episode checks,
completion watches). Use bot.py instead to run both Telegram and the web app."""

from qbit_web.server import main

if __name__ == "__main__":
    main()
