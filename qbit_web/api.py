"""JSON API for the web app — every capability of the Telegram bot, stateless
(the client drives the tag → category flows and posts the final choice)."""

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

import qbittorrentapi
import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from qbit_bot import config
from qbit_bot.config import (
    INTERVAL_CHOICES,
    QBIT_CACHE_PATH,
    STALL_ALERT_CHOICES,
    WATCH_POLL_CHOICES,
)
from qbit_bot.hebits import (
    HEBITS_CATS,
    HebitsError,
    hebits_download,
    hebits_latest,
    hebits_search,
    hebits_whoami,
    save_hebits_cookie,
)
from qbit_bot.jobs import collect_new_episodes
from qbit_bot.plex import PlexError, plex_refresh, plex_sections
from qbit_bot.qbit import decorate_local_status, fetch_qbit_torrents, qb
from qbit_bot.storage import (
    add_watch,
    request_agent_refresh,
    take_agent_refresh,
    load_events,
    load_favorites,
    load_history,
    load_series_defaults,
    load_settings,
    load_watches,
    mark_events_read,
    record_history,
    remove_event,
    remove_favorite,
    save_series_defaults,
    save_setting,
    set_favorite,
    update_favorite,
)
from qbit_bot.utils import (
    episode_key,
    episode_tag,
    magnet_info_hash,
    normalize_resolution,
    season_of,
    torrent_info_hash,
)
from qbit_bot.views import RES_CHOICES, default_label

from . import agents, covers

log = logging.getLogger("qbit-web")

# ------------------------------------------------------------------ auth

ADMIN, USER = "admin", "user"


def _token_for(secret: str) -> str:
    return hashlib.sha256(f"qbit-web:{secret}".encode()).hexdigest()


def auth_required() -> bool:
    return bool(config.ADMIN_PASSWORD)


def _role_tokens() -> dict[str, str]:
    """token -> role for every configured login."""
    tokens = {}
    if config.ADMIN_PASSWORD:
        tokens[_token_for(f"admin:{config.ADMIN_PASSWORD}")] = ADMIN
        if config.USER_PASSWORD:
            tokens[_token_for(f"user:{config.USER_PASSWORD}")] = USER
    return tokens


def role_of(token: str | None) -> str | None:
    if not token:
        return None
    for known, role in _role_tokens().items():
        if hmac.compare_digest(token, known):
            return role
    return None


def user_pages() -> dict:
    """Pages a user login may open (admin-editable in Settings)."""
    stored = load_settings().get("user_pages") or {}
    return {k: bool(stored.get(k, config.DEFAULT_SETTINGS["user_pages"][k])) for k in config.USER_PAGE_KEYS}


# which endpoint prefixes a page unlocks for a user login; anything not listed
# here (settings, cookie, cache) is admin-only
_PAGE_PATHS = {
    "nas": ("/api/nas",),
    "browse": ("/api/browse",),
    "search": ("/api/search", "/api/group"),
    "add": ("/api/add", "/api/tags", "/api/categories", "/api/defaults"),
    "library": ("/api/torrents", "/api/tags", "/api/categories", "/api/refresh", "/api/history"),
    "favorites": ("/api/favorites", "/api/defaults", "/api/group"),
    "activity": ("/api/events", "/api/group"),
    "plex": ("/api/plex",),
}
_ALWAYS = ("/api/status", "/api/cover")


def _user_may(path: str, pages: dict) -> bool:
    if path.startswith(_ALWAYS):
        return True
    return any(
        pages.get(page) and path.startswith(prefixes)
        for page, prefixes in _PAGE_PATHS.items()
    )


async def require_auth(request: Request, token: str | None = Query(default=None)) -> str:
    """Bearer token (or ?token= for <img> URLs). Returns the role; for user
    logins also enforces the admin's page permissions. Without
    ADMIN_PASSWORD everyone is admin."""
    if not auth_required():
        return ADMIN
    header = request.headers.get("authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else token
    role = role_of(supplied)
    if role is None:
        raise HTTPException(401, "Not authorized")
    if role == USER and not _user_may(request.url.path, user_pages()):
        raise HTTPException(403, "This page isn't enabled for the user login")
    return role


async def require_admin(role: str = Depends(require_auth)) -> str:
    if role != ADMIN:
        raise HTTPException(403, "Admins only")
    return role


def settings_locked() -> bool:
    return bool(config.SETTINGS_PASSWORD)


def _settings_token() -> str:
    return _token_for(f"settings:{config.SETTINGS_PASSWORD}")


async def require_settings(request: Request, role: str = Depends(require_admin)):
    """Settings changes: admin role, plus the optional SETTINGS_PASSWORD second
    factor (an X-Settings-Token header from POST /api/settings/unlock)."""
    if not settings_locked():
        return
    supplied = request.headers.get("x-settings-token", "")
    if not supplied or not hmac.compare_digest(supplied, _settings_token()):
        raise HTTPException(403, "Settings are locked — enter the settings password")


public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@public.get("/auth")
async def auth_info():
    return {
        "required": auth_required(),
        "user_login": bool(config.ADMIN_PASSWORD and config.USER_PASSWORD),
        "settings_locked": settings_locked(),
        "version": 2,
    }


class LoginBody(BaseModel):
    password: str


@public.post("/login")
async def login(body: LoginBody):
    """One password field, two roles: the admin password or the user password."""
    if not auth_required():
        return {"token": "", "role": ADMIN}
    if hmac.compare_digest(body.password, config.ADMIN_PASSWORD):
        return {"token": _token_for(f"admin:{config.ADMIN_PASSWORD}"), "role": ADMIN}
    if config.USER_PASSWORD and hmac.compare_digest(body.password, config.USER_PASSWORD):
        return {"token": _token_for(f"user:{config.USER_PASSWORD}"), "role": USER}
    await asyncio.sleep(0.5)  # slow down guessing
    raise HTTPException(401, "Wrong password")


@router.post("/settings/unlock", dependencies=[Depends(require_admin)])
async def settings_unlock(body: LoginBody):
    if not settings_locked():
        return {"token": ""}
    if not hmac.compare_digest(body.password, config.SETTINGS_PASSWORD):
        await asyncio.sleep(0.5)
        raise HTTPException(401, "Wrong settings password")
    return {"token": _settings_token()}


# ------------------------------------------------------------------ helpers

async def run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def local_json(t: dict) -> dict | None:
    st = t.get("local")
    if not st:
        return None
    out = {"status": st[0]}
    if st[0] == "dl":
        out["progress"] = st[1]
    return out


def group_json(g: dict, favorites: dict, defaults: dict) -> dict:
    gid = str(g.get("gid") or "")
    torrents = []
    for t in g["torrents"]:
        torrents.append({**t, "local": local_json(t), "episode": episode_tag(t["title"]),
                         "season": season_of(t["title"])})
    return {
        "gid": gid,
        "name_en": g["name_en"],
        "name_he": g["name_he"],
        "year": g["year"],
        "cover": g["cover"],
        "imdb": g["imdb"],
        "cat": g["cat"],
        "tags": g.get("tags", []),
        "torrents": torrents,
        "favorite": gid in favorites,
        "auto": bool(favorites.get(gid, {}).get("auto")),
        "default": defaults.get(gid),
    }


def torrent_json(t) -> dict:
    tags = [x.strip() for x in (t.tags or "").split(",") if x.strip()]
    return {
        "hash": t.hash,
        "name": t.name,
        "state": t.state,
        "progress": float(t.progress),
        "size": int(t.size),
        "total_size": int(getattr(t, "total_size", t.size) or 0),
        "downloaded": int(getattr(t, "downloaded", 0) or 0),
        "uploaded": int(getattr(t, "uploaded", 0) or 0),
        "dlspeed": int(t.dlspeed),
        "upspeed": int(t.upspeed),
        "ratio": float(t.ratio),
        "eta": int(t.eta),
        "num_seeds": int(getattr(t, "num_seeds", 0) or 0),
        "num_leechs": int(getattr(t, "num_leechs", 0) or 0),
        "tags": tags,
        "category": t.category or "",
        "added_on": int(t.added_on),
        "completion_on": int(getattr(t, "completion_on", 0) or 0),
        "save_path": getattr(t, "save_path", "") or "",
    }


def _create_category(name: str) -> None:
    try:
        qb().torrents_create_category(name=name)
    except qbittorrentapi.exceptions.Conflict409Error:
        pass  # already exists


# ------------------------------------------------------------------ status

@router.get("/status")
async def status(role: str = Depends(require_auth)):
    settings = load_settings()
    try:
        import json

        with open(QBIT_CACHE_PATH) as f:
            cache = json.load(f)
        snapshot = {
            "torrents": len(cache["torrents"]),
            "updated": cache["updated"],
        }
    except (OSError, ValueError, KeyError):
        snapshot = None
    return {
        "snapshot": snapshot,
        "favorites": len(load_favorites()),
        "history": len(load_history()),
        "watches": len(load_watches()),
        "defaults": len(load_series_defaults()),
        "cookie_configured": bool(config.HEBITS_COOKIE),
        "plex_url": config.PLEX_URL,
        "plex_auth": "token" if config.PLEX_TOKEN else "lan",
        "qbit": f"{config.QBIT['host']}:{config.QBIT['port']}",
        "telegram": bool(config.BOT_TOKEN),
        "settings": settings,
        "unread_events": sum(1 for e in load_events() if not e.get("read")),
        "cache": covers.stats(),
        "settings_locked": settings_locked(),
        "role": role,
        "user_pages": user_pages(),
        "user_login": bool(config.ADMIN_PASSWORD and config.USER_PASSWORD),
    }


# ------------------------------------------------------------------ search

@router.get("/search")
async def search(q: str, cat: str = "a", page: int = 1):
    q = q.strip()
    if not q:
        raise HTTPException(400, "Empty query")
    groups, pages = await run(hebits_search, q, cat, page)
    await run(decorate_local_status, groups)
    favorites, defaults = load_favorites(), load_series_defaults()
    return {
        "query": q,
        "cat": cat,
        "page": page,
        "pages": pages,
        "groups": [group_json(g, favorites, defaults) for g in groups],
    }


BROWSE_CATS = {"movies": "1", "series": "2"}

# HeBits genre tags (Hebrew, as the site stores them) with English labels, in
# display order. Filtering is server-side via the Gazelle `taglist` parameter.
BROWSE_GENRES = [
    ("דרמה", "Drama"),
    ("קומדיה", "Comedy"),
    ("מותחן", "Thriller"),
    ("פעולה", "Action"),
    ("הרפתקאות", "Adventure"),
    ("פשע", "Crime"),
    ("מסתורין", "Mystery"),
    ("אימה", "Horror"),
    ("פנטזיה", "Fantasy"),
    ("מדע.בדיוני", "Sci-Fi"),
    ("רומנטי", "Romance"),
    ("משפחה", "Family"),
    ("ילדים", "Kids"),
    ("אנימציה", "Animation"),
    ("דוקומנטרי", "Documentary"),
    ("ביוגרפיה", "Biography"),
    ("היסטוריה", "History"),
    ("מלחמה", "War"),
    ("מערבון", "Western"),
    ("מוזיקלי", "Musical"),
    ("ספורט", "Sport"),
    ("ריאליטי", "Reality"),
    ("תוכנית.אירוח", "Talk show"),
    ("שעשועון", "Game show"),
    ("סאטירה", "Satire"),
    ("ישראלי", "Israeli"),
]


@router.get("/browse")
async def browse(cat: str, page: int = 1, genre: str | None = None):
    """Newest HeBits content in a category (the site's movies.php / series.php
    pages), same shape as /api/search so the app can reuse its tiles.
    cat: 'movies' | 'series' (or a raw HeBits category id);
    genre: a HeBits tag (see BROWSE_GENRES) to show only that genre."""
    cat_id = BROWSE_CATS.get(cat, cat)
    if not cat_id.isdigit():
        raise HTTPException(400, f"cat must be one of {', '.join(BROWSE_CATS)}")
    if page < 1:
        raise HTTPException(400, "page starts at 1")
    genre = (genre or "").strip() or None
    groups, pages = await run(hebits_latest, cat_id, page, genre)
    await run(decorate_local_status, groups)
    favorites, defaults = load_favorites(), load_series_defaults()
    return {
        "cat": cat,
        "page": page,
        "pages": pages,
        "genre": genre,
        "genres": [{"tag": t, "label": label} for t, label in BROWSE_GENRES],
        "groups": [group_json(g, favorites, defaults) for g in groups],
    }


@router.get("/group")
async def group(gid: str, q: str | None = None):
    """One HeBits group, fresh: used to (re)open a favorite or a notification."""
    if not q:
        entry = load_favorites().get(gid) or load_series_defaults().get(gid)
        q = (entry or {}).get("query") or (entry or {}).get("name")
    if not q:
        raise HTTPException(400, "Need a search query for this group")
    groups, _ = await run(hebits_search, q)
    hit = next((g for g in groups if str(g.get("gid")) == str(gid)), None)
    if hit is None:
        raise HTTPException(404, f"“{q}” isn't on HeBits anymore")
    await run(decorate_local_status, [hit])
    return group_json(hit, load_favorites(), load_series_defaults())


@router.post("/cache/clear", dependencies=[Depends(require_settings)])
async def cache_clear():
    return await run(covers.clear)


@router.get("/cover")
async def cover(url: str):
    """Poster proxy backed by the on-disk cache (see qbit_web.covers): fetched
    from this machine, re-encoded small, served with a long browser TTL."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Bad URL")
    hit = await run(covers.get, url)
    if hit is None:
        raise HTTPException(404, "No image")
    data, ctype = hit
    return Response(data, media_type=ctype, headers={"Cache-Control": "public, max-age=604800"})


# ------------------------------------------------------------------ adding

class HebitsAdd(BaseModel):
    tid: int
    title: str | None = None
    gid: str | None = None
    series: str | None = None
    tag: str | None = None
    category: str | None = None


class MagnetAdd(BaseModel):
    magnet: str
    tag: str | None = None
    category: str | None = None


def _perform_add(
    *,
    torrent_file: bytes | None,
    magnet: str | None,
    name: str,
    tag: str | None,
    category: str | None,
    hebits_id: int | None = None,
    gid: str | None = None,
    series: str | None = None,
) -> dict:
    """Add to qBittorrent with the bot's bookkeeping: history, completion
    watch, and an offer to remember the choice as the series default."""
    kwargs: dict[str, Any] = {}
    if tag:
        kwargs["tags"] = tag
    if category:
        _create_category(category)
        kwargs["category"] = category
    client = qb()
    if magnet:
        result = client.torrents_add(urls=magnet, **kwargs)
    else:
        result = client.torrents_add(torrent_files=torrent_file, **kwargs)
    if result != "Ok.":
        raise HTTPException(409, f"qBittorrent rejected it ({result}). Duplicate torrent?")

    info_hash = None
    try:
        info_hash = magnet_info_hash(magnet) if magnet else torrent_info_hash(torrent_file)
    except (ValueError, OSError) as e:
        log.warning("could not compute info-hash: %s", e)
    if hebits_id and torrent_file and info_hash:
        try:
            record_history(hebits_id, info_hash, name)
        except OSError as e:
            log.warning("could not record download history: %s", e)
    watched = False
    if info_hash:
        try:
            add_watch(info_hash, name, list(config.ALLOWED_USER_IDS))
            watched = True
        except OSError as e:
            log.warning("could not register completion watch: %s", e)

    offer_default = False
    if gid and category and episode_key(name):
        existing = load_series_defaults().get(gid)
        offer_default = not existing or (
            (existing.get("category"), existing.get("tag")) != (category, tag)
        )
    return {
        "ok": True,
        "name": name,
        "hash": info_hash,
        "tag": tag,
        "category": category,
        "watched": watched,
        "offer_default": offer_default,
        "gid": gid,
        "series": series or name,
    }


@router.post("/add/hebits")
async def add_hebits(body: HebitsAdd):
    data = await run(hebits_download, body.tid)
    name = body.title or f"HeBits torrent #{body.tid}"
    return await run(
        _perform_add,
        torrent_file=data,
        magnet=None,
        name=name,
        tag=body.tag or None,
        category=body.category or None,
        hebits_id=body.tid,
        gid=body.gid or None,
        series=body.series,
    )


@router.post("/add/magnet")
async def add_magnet(body: MagnetAdd):
    magnet = body.magnet.strip()
    if not magnet.startswith("magnet:"):
        raise HTTPException(400, "That isn't a magnet link")
    return await run(
        _perform_add,
        torrent_file=None,
        magnet=magnet,
        name="magnet",
        tag=body.tag or None,
        category=body.category or None,
    )


@router.post("/add/file")
async def add_file(
    file: UploadFile = File(...),
    tag: str | None = Form(default=None),
    category: str | None = Form(default=None),
):
    data = await file.read()
    if not data.startswith(b"d"):
        raise HTTPException(400, "That doesn't look like a .torrent file")
    return await run(
        _perform_add,
        torrent_file=data,
        magnet=None,
        name=file.filename or ".torrent file",
        tag=tag or None,
        category=category or None,
    )


# ------------------------------------------------------------------ torrents

@router.get("/torrents")
async def torrents(tag: str | None = None, category: str | None = None):
    def _list():
        client = qb()
        kwargs = {}
        if tag:
            kwargs["tag"] = tag
        if category:
            kwargs["category"] = category
        items = client.torrents_info(**kwargs)
        return sorted(items, key=lambda t: t.added_on, reverse=True)

    return {"torrents": [torrent_json(t) for t in await run(_list)]}


@router.get("/torrents/{torrent_hash}")
async def torrent_detail(torrent_hash: str):
    items = await run(lambda: qb().torrents_info(torrent_hashes=torrent_hash))
    if not items:
        raise HTTPException(404, "Torrent not found (already removed?)")
    return torrent_json(items[0])


@router.post("/torrents/{torrent_hash}/pause")
async def torrent_pause(torrent_hash: str):
    await run(lambda: qb().torrents_pause(torrent_hashes=torrent_hash))
    return {"ok": True}


@router.post("/torrents/{torrent_hash}/resume")
async def torrent_resume(torrent_hash: str):
    await run(lambda: qb().torrents_resume(torrent_hashes=torrent_hash))
    return {"ok": True}


class TagsChange(BaseModel):
    add: list[str] = []
    remove: list[str] = []


@router.post("/torrents/{torrent_hash}/tags")
async def torrent_tags(torrent_hash: str, body: TagsChange):
    def _apply():
        client = qb()
        if body.add:
            client.torrents_add_tags(tags=",".join(body.add), torrent_hashes=torrent_hash)
        if body.remove:
            client.torrents_remove_tags(tags=",".join(body.remove), torrent_hashes=torrent_hash)
        items = client.torrents_info(torrent_hashes=torrent_hash)
        return torrent_json(items[0]) if items else None

    result = await run(_apply)
    if result is None:
        raise HTTPException(404, "Torrent not found")
    return result


class CategoryChange(BaseModel):
    category: str | None = None


@router.post("/torrents/{torrent_hash}/category")
async def torrent_category(torrent_hash: str, body: CategoryChange):
    def _apply():
        if body.category:
            _create_category(body.category)
        qb().torrents_set_category(category=body.category or "", torrent_hashes=torrent_hash)

    await run(_apply)
    return {"ok": True}


@router.delete("/torrents/{torrent_hash}")
async def torrent_delete(torrent_hash: str, files: bool = False):
    def _delete():
        client = qb()
        items = client.torrents_info(torrent_hashes=torrent_hash)
        client.torrents_delete(delete_files=files, torrent_hashes=torrent_hash)
        return items[0].name if items else "torrent"

    return {"ok": True, "name": await run(_delete), "files_deleted": files}


@router.get("/tags")
async def tags():
    return {"tags": await run(lambda: sorted(qb().torrents_tags()))}


class NameBody(BaseModel):
    name: str


@router.post("/tags")
async def create_tag(body: NameBody):
    name = body.name.replace(",", " ").strip()
    if not name:
        raise HTTPException(400, "Empty name")
    await run(lambda: qb().torrents_create_tags(tags=name))
    return {"ok": True, "name": name}


@router.get("/categories")
async def categories():
    return {"categories": await run(lambda: sorted(qb().torrents_categories()))}


@router.post("/categories")
async def create_category(body: NameBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Empty name")
    await run(_create_category, name)
    return {"ok": True, "name": name}


@router.post("/refresh")
async def refresh():
    items = await run(fetch_qbit_torrents)
    return {"torrents": len(items), "completed": sum(1 for t in items if t.progress >= 1)}


@router.get("/history")
async def history():
    items = [{"tid": tid, **entry} for tid, entry in load_history().items()]
    items.sort(key=lambda e: e.get("added", ""), reverse=True)
    return {"history": items[:200]}


# ------------------------------------------------------------------ favorites

def favorite_json(gid: str, entry: dict, defaults: dict) -> dict:
    default = defaults.get(gid)
    return {
        "gid": gid,
        "name": entry["name"],
        "query": entry.get("query", ""),
        "added": entry.get("added"),
        "last_ep": entry.get("last_ep"),
        "auto": bool(entry.get("auto")),
        "default": default,
        "default_label": default_label(default) if default else None,
    }


@router.get("/favorites")
async def favorites():
    defaults = load_series_defaults()
    items = [favorite_json(g, e, defaults) for g, e in load_favorites().items()]
    items.sort(key=lambda f: f["name"].lower())
    return {"favorites": items}


class FavoriteBody(BaseModel):
    gid: str
    name: str
    query: str


@router.post("/favorites")
async def add_favorite(body: FavoriteBody):
    set_favorite(
        body.gid,
        {
            "name": body.name,
            "query": body.query,
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    return favorite_json(body.gid, load_favorites()[body.gid], load_series_defaults())


@router.delete("/favorites/{gid}")
async def delete_favorite(gid: str):
    return {"ok": remove_favorite(gid)}


class FavoritePatch(BaseModel):
    auto: bool | None = None


@router.patch("/favorites/{gid}")
async def patch_favorite(gid: str, body: FavoritePatch):
    favs = load_favorites()
    if gid not in favs:
        raise HTTPException(404, "Not in favorites anymore")
    if body.auto is not None:
        if body.auto:
            default = load_series_defaults().get(gid)
            if not default or not default.get("category"):
                raise HTTPException(
                    409, "Set a default (tag, category, resolution) before enabling auto-add"
                )
        update_favorite(gid, auto=body.auto)
    return favorite_json(gid, load_favorites()[gid], load_series_defaults())


@router.post("/favorites/check")
async def check_favorites():
    notes = await run(collect_new_episodes)
    return {"notifications": notes}


# ------------------------------------------------------------------ defaults

class DefaultBody(BaseModel):
    name: str
    tag: str | None = None
    category: str
    resolution: str | None = None


@router.get("/defaults")
async def defaults():
    return {"defaults": load_series_defaults()}


@router.put("/defaults/{gid}")
async def put_default(gid: str, body: DefaultBody):
    resolution = normalize_resolution(body.resolution or "") or None
    if resolution and resolution not in RES_CHOICES:
        raise HTTPException(400, f"Resolution must be one of {', '.join(RES_CHOICES)} or empty")
    if body.category:
        await run(_create_category, body.category)
    d = load_series_defaults()
    d[gid] = {
        "name": body.name,
        "tag": body.tag or None,
        "category": body.category,
        "resolution": resolution,
    }
    save_series_defaults(d)
    return {"gid": gid, "default": d[gid], "label": default_label(d[gid])}


@router.delete("/defaults/{gid}")
async def delete_default(gid: str):
    d = load_series_defaults()
    removed = d.pop(gid, None) is not None
    if removed:
        save_series_defaults(d)
        if load_favorites().get(gid, {}).get("auto"):
            update_favorite(gid, auto=False)  # nothing to auto-add with anymore
    return {"ok": removed}


# ------------------------------------------------------------------ events

@router.get("/events")
async def events():
    items = list(reversed(load_events()))
    return {"events": items, "unread": sum(1 for e in items if not e.get("read"))}


class ReadBody(BaseModel):
    ids: list[int] | None = None


@router.post("/events/read")
async def events_read(body: ReadBody):
    mark_events_read(body.ids)
    return {"ok": True}


@router.delete("/events/{event_id}")
async def event_delete(event_id: int):
    return {"ok": remove_event(event_id)}


# ------------------------------------------------------------------ plex

@router.get("/plex/sections")
async def plex_list():
    return {"sections": await run(plex_sections)}


class ScanBody(BaseModel):
    keys: list[str] = []
    all: bool = False


@router.post("/plex/scan")
async def plex_scan(body: ScanBody):
    sections = await run(plex_sections)
    targets = sections if body.all else [s for s in sections if s["key"] in set(body.keys)]
    if not targets:
        raise HTTPException(404, "Library not found")
    for s in targets:
        await run(plex_refresh, s["key"])
    return {"scanning": targets}


# ------------------------------------------------------------------ settings

SETTING_CHOICES = {
    "qbit_refresh_hours": INTERVAL_CHOICES,
    "fav_check_hours": INTERVAL_CHOICES,
    "watch_poll_seconds": WATCH_POLL_CHOICES,
    "stall_alert_hours": STALL_ALERT_CHOICES,
}


@router.get("/settings", dependencies=[Depends(require_admin)])
async def get_settings():
    return {
        "settings": load_settings(),
        "choices": {k: list(v) for k, v in SETTING_CHOICES.items()},
        "resolutions": list(RES_CHOICES),
        "hebits_cats": HEBITS_CATS,
        "user_page_keys": list(config.USER_PAGE_KEYS),
    }


class SettingPatch(BaseModel):
    key: str
    value: Any


@router.patch("/settings", dependencies=[Depends(require_settings)])
async def patch_setting(body: SettingPatch):
    if body.key in SETTING_CHOICES:
        try:
            value = int(body.value)
        except (TypeError, ValueError):
            raise HTTPException(400, "Value must be a number")
        if value not in SETTING_CHOICES[body.key]:
            raise HTTPException(400, f"Allowed values: {SETTING_CHOICES[body.key]}")
    elif body.key == "auto_plex_scan":
        value = bool(body.value)
    elif body.key == "user_pages":
        if not isinstance(body.value, dict):
            raise HTTPException(400, "user_pages must be an object {page: bool}")
        value = user_pages()
        for page, on in body.value.items():
            if page not in config.USER_PAGE_KEYS:
                raise HTTPException(400, f"Unknown page {page!r}")
            value[page] = bool(on)
    elif body.key == "plex_map":
        if not isinstance(body.value, dict):
            raise HTTPException(400, "plex_map must be an object {category: libraryKey}")
        # merge: null / "" / "all" clears a category's mapping
        value = dict(load_settings()["plex_map"])
        for cat, key in body.value.items():
            if key in (None, "", "all"):
                value.pop(cat, None)
            else:
                value[cat] = str(key)
    else:
        raise HTTPException(400, f"Unknown setting {body.key!r}")
    save_setting(body.key, value)
    return {"settings": load_settings()}


# ------------------------------------------------------------------ cookie

@router.get("/cookie", dependencies=[Depends(require_admin)])
async def cookie_status():
    if not config.HEBITS_COOKIE:
        return {"configured": False, "valid": False, "user": None}
    user = await run(hebits_whoami, config.HEBITS_COOKIE)
    return {"configured": True, "valid": user is not None, "user": user}


class CookieBody(BaseModel):
    cookie: str


@router.put("/cookie", dependencies=[Depends(require_settings)])
async def cookie_update(body: CookieBody):
    cookie = body.cookie.strip()
    if not cookie:
        raise HTTPException(400, "Empty cookie")
    user = await run(hebits_whoami, cookie)
    if not user:
        raise HTTPException(400, "HeBits doesn't recognize that session — copy the whole Cookie header while logged in")
    save_hebits_cookie(cookie)
    return {"configured": True, "valid": True, "user": user}


# ------------------------------------------------------------------ agents

class AgentReport(BaseModel):
    report: dict


@public.post("/agents/{name}/report")
async def agent_report(name: str, body: AgentReport, request: Request):
    """Intake for external agents (agent/qnap_agent.py). Authenticated by the
    shared AGENT_TOKEN header, not by a web login."""
    _check_agent_token(request)
    name = name.strip().lower()
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "Agent name must be alphanumeric")
    return await agents.ingest(name, body.report)


def _check_agent_token(request: Request) -> None:
    if not config.AGENT_TOKEN:
        raise HTTPException(503, "Agents are disabled — set AGENT_TOKEN in .env")
    supplied = request.headers.get("x-agent-token", "")
    if not supplied or not hmac.compare_digest(supplied, config.AGENT_TOKEN):
        raise HTTPException(401, "Bad agent token")


@public.get("/agents/{name}/poll")
async def agent_poll(name: str, request: Request):
    """Agents call this between reports; `refresh: true` means someone
    pressed Refresh in the app and a report should be sent right away."""
    _check_agent_token(request)
    return {"refresh": take_agent_refresh(name.strip().lower())}


@router.post("/nas/refresh")
async def nas_refresh():
    """Ask every agent for a fresh report now (answered within its check-in
    interval, a few seconds, if the agent is running)."""
    names = request_agent_refresh()
    if not names:
        raise HTTPException(404, "No agent has reported yet")
    return {"requested": names}


@router.get("/nas")
async def nas():
    return {
        "agents": agents.agents_view(),
        "configured": bool(config.AGENT_TOKEN),
        "thresholds": {
            "usage_percent": config.NAS_USAGE_ALERT_PERCENT,
            "disk_temp_c": config.NAS_DISK_TEMP_ALERT_C,
        },
    }


# ------------------------------------------------------------------ errors

def install_error_handlers(app) -> None:
    @app.exception_handler(HebitsError)
    async def _hebits(_, exc):
        return _err(502, str(exc))

    @app.exception_handler(PlexError)
    async def _plex(_, exc):
        return _err(502, str(exc))

    @app.exception_handler(requests.RequestException)
    async def _requests(_, exc):
        return _err(502, f"HeBits request failed: {exc.__class__.__name__}")

    @app.exception_handler(qbittorrentapi.exceptions.APIConnectionError)
    async def _qbit_conn(_, exc):
        return _err(503, "Can't reach qBittorrent. Is the Web UI enabled and the host reachable?")

    @app.exception_handler(qbittorrentapi.exceptions.LoginFailed)
    async def _qbit_login(_, exc):
        return _err(503, "qBittorrent login failed — check QBIT_USERNAME / QBIT_PASSWORD.")

    @app.exception_handler(qbittorrentapi.exceptions.APIError)
    async def _qbit_api(_, exc):
        return _err(502, f"qBittorrent error: {exc}")


def _err(status: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": detail}, status_code=status)
