"""Plex Media Server API: list libraries and trigger scans."""

import xml.etree.ElementTree as ET

import requests

from .config import PLEX_TOKEN, PLEX_URL


class PlexError(Exception):
    pass


def plex_request(path: str) -> requests.Response:
    """GET from the Plex server. A token is optional: without one, Plex must
    allow the bot's IP (Settings → Network → allowed-without-auth list)."""
    headers = {"Accept": "application/xml"}
    if PLEX_TOKEN:
        headers["X-Plex-Token"] = PLEX_TOKEN
    try:
        r = requests.get(f"{PLEX_URL}{path}", headers=headers, timeout=15)
    except requests.RequestException as e:
        raise PlexError(f"Can't reach Plex at {PLEX_URL} ({e.__class__.__name__}).")
    if r.status_code == 401:
        if PLEX_TOKEN:
            raise PlexError("Plex rejected the token (401) — check PLEX_TOKEN in .env.")
        raise PlexError(
            "Plex refused the request (401). Add this machine's IP to Plex "
            "Settings → Network → “List of IP addresses and networks that are "
            "allowed without auth” (e.g. 127.0.0.1), or set PLEX_TOKEN in .env."
        )
    if not r.ok:
        raise PlexError(f"Plex returned HTTP {r.status_code} for {path}.")
    return r


def plex_sections() -> list[dict]:
    """All libraries: [{key, title, type, refreshing}] (type: movie/show/…)."""
    r = plex_request("/library/sections")
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise PlexError("Plex returned an unreadable response — is PLEX_URL right?")
    return [
        {
            "key": d.get("key"),
            "title": d.get("title") or f"Library {d.get('key')}",
            "type": d.get("type") or "",
            "refreshing": d.get("refreshing") == "1",
        }
        for d in root.iter("Directory")
    ]


def plex_refresh(key: str) -> None:
    """Ask Plex to scan a library section for new/changed files."""
    plex_request(f"/library/sections/{key}/refresh")
