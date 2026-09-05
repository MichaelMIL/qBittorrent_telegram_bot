"""On-disk poster cache for the web app.

Covers come from uploader-controlled hosts and are large; the app only needs
tile-sized images. Each poster is fetched once (through hebits.fetch_cover, so
the HeBits cookie only goes to hebits.net), re-encoded as a small JPEG, and
stored under data/covers/<sha1(url)>.jpg. The directory is capped at
CACHE_MAX_MB (least-recently-used files go first) and wiped every
CACHE_CLEAR_HOURS. All functions are blocking — call them via asyncio.to_thread.
"""

import asyncio
import hashlib
import io
import logging
import threading
from datetime import datetime, timezone

from qbit_bot import config
from qbit_bot.hebits import fetch_cover

log = logging.getLogger("qbit-web")

_lock = threading.Lock()
_CLEARED_MARK = ".cleared"  # holds the ISO time of the last clear

_IMAGE_TYPES = (
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"RIFF", "image/webp"),
)

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency
    Image = None


def _sniff(data: bytes) -> str:
    return next((t for magic, t in _IMAGE_TYPES if data.startswith(magic)), "image/jpeg")


def compress(data: bytes) -> tuple[bytes, str]:
    """Re-encode a poster as a JPEG no wider than CACHE_MAX_WIDTH. Falls back
    to the original bytes when Pillow is missing, the image can't be decoded,
    or the re-encoded version isn't smaller."""
    if Image is None:
        return data, _sniff(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if getattr(img, "is_animated", False):
                return data, _sniff(data)
            img = img.convert("RGB")
            if img.width > config.CACHE_MAX_WIDTH:
                ratio = config.CACHE_MAX_WIDTH / img.width
                img = img.resize(
                    (config.CACHE_MAX_WIDTH, max(1, round(img.height * ratio))),
                    Image.LANCZOS,
                )
            out = io.BytesIO()
            img.save(out, "JPEG", quality=config.CACHE_JPEG_QUALITY, optimize=True, progressive=True)
    except Exception as e:  # corrupt / unsupported image: keep what we got
        log.debug("cover re-encode failed (%s); storing original", e)
        return data, _sniff(data)
    small = out.getvalue()
    return (small, "image/jpeg") if len(small) < len(data) else (data, _sniff(data))


def _path(url: str):
    return config.COVERS_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".img")


def _files():
    if not config.COVERS_DIR.exists():
        return []
    return [p for p in config.COVERS_DIR.iterdir() if p.suffix == ".img"]


def _enforce_limit() -> int:
    """Evict least-recently-used files until the directory fits CACHE_MAX_MB.
    Returns how many files were removed. Caller holds the lock."""
    limit = int(config.CACHE_MAX_MB * 1024 * 1024)
    if limit <= 0:
        return 0
    files = sorted(_files(), key=lambda p: p.stat().st_mtime)  # oldest first
    total = sum(p.stat().st_size for p in files)
    removed = 0
    while total > limit and files:
        victim = files.pop(0)
        try:
            total -= victim.stat().st_size
            victim.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def get(url: str) -> tuple[bytes, str] | None:
    """The cached (compressed) poster for `url`, fetching and storing it on a
    miss. None when the URL doesn't yield a usable image."""
    path = _path(url)
    with _lock:
        if path.exists():
            data = path.read_bytes()
            path.touch()  # mtime = last use, for LRU eviction
            return data, _sniff(data)
    raw = fetch_cover(url)
    if not raw:
        return None
    data, ctype = compress(raw)
    with _lock:
        config.COVERS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        evicted = _enforce_limit()
    if evicted:
        log.info("poster cache over %s MB — evicted %d oldest", config.CACHE_MAX_MB, evicted)
    return data, ctype


def stats() -> dict:
    with _lock:
        files = _files()
        size = sum(p.stat().st_size for p in files)
        mark = config.COVERS_DIR / _CLEARED_MARK
        cleared_at = mark.read_text().strip() if mark.exists() else None
    return {
        "covers": len(files),
        "bytes": size,
        "max_bytes": int(config.CACHE_MAX_MB * 1024 * 1024),
        "cleared_at": cleared_at,
        "clear_every_hours": config.CACHE_CLEAR_HOURS,
        "location": str(config.COVERS_DIR),
    }


def clear() -> dict:
    """Delete every cached poster. Returns {cleared: {covers, bytes}, cache}."""
    with _lock:
        files = _files()
        size = sum(p.stat().st_size for p in files)
        for p in files:
            try:
                p.unlink()
            except OSError:
                pass
        config.COVERS_DIR.mkdir(parents=True, exist_ok=True)
        (config.COVERS_DIR / _CLEARED_MARK).write_text(
            datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
    log.info("poster cache cleared: %d files, %d bytes", len(files), size)
    return {"cleared": {"covers": len(files), "bytes": size}, "cache": stats()}


async def sweeper() -> None:
    """Background task: wipe the poster cache every CACHE_CLEAR_HOURS. The
    schedule counts from the last clear, so restarts don't reset it."""
    hours = config.CACHE_CLEAR_HOURS
    if hours <= 0:
        return
    while True:
        mark = config.COVERS_DIR / _CLEARED_MARK
        try:
            last = datetime.fromisoformat(mark.read_text().strip())
        except (OSError, ValueError):
            last = None
        if last is None:  # never cleared: start the clock now
            config.COVERS_DIR.mkdir(parents=True, exist_ok=True)
            mark.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"))
            last = datetime.now(timezone.utc)
        due = (last.timestamp() + hours * 3600) - datetime.now(timezone.utc).timestamp()
        await asyncio.sleep(max(60, due))
        await asyncio.to_thread(clear)
