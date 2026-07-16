"""HeBits (Gazelle) API: search, download, covers, session cookie."""

import os
import requests
from urllib.parse import urlparse

from . import config
from .config import HEBITS_URL
from .utils import episode_key

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
    config.HEBITS_COOKIE = cookie
    env_path = config.BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        with open(env_path) as f:
            lines = [l.rstrip("\n") for l in f if not l.startswith("HEBITS_COOKIE=")]
    lines.append(f"HEBITS_COOKIE={cookie}")
    with open(env_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def hebits_request(path: str, params: dict) -> requests.Response:
    if not config.HEBITS_COOKIE:
        raise HebitsError(
            "HeBits search isn't configured. Run hebits_cookie.py, or send:\n"
            "/cookie <your hebits.net Cookie header>"
        )
    r = requests.get(
        f"{HEBITS_URL}/{path}",
        params=params,
        headers={"Cookie": config.HEBITS_COOKIE, "User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    return r


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
        headers["Cookie"] = config.HEBITS_COOKIE
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
