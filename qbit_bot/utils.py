"""Formatting helpers, episode parsing, and torrent utilities."""

import hashlib
import re

STATE_EMOJI = {
    "downloading": "⬇️",
    "forcedDL": "⬇️",
    "metaDL": "🔍",
    "allocating": "⏳",
    "uploading": "🌱",
    "forcedUP": "🌱",
    "stalledUP": "✅",
    "stalledDL": "🐌",
    "pausedDL": "⏸",
    "stoppedDL": "⏸",
    "pausedUP": "☑️",
    "stoppedUP": "☑️",
    "queuedDL": "🕐",
    "queuedUP": "🕐",
    "checkingDL": "🔬",
    "checkingUP": "🔬",
    "checkingResumeData": "🔬",
    "error": "❌",
    "missingFiles": "❌",
    "moving": "📦",
}


def fmt_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


def fmt_eta(seconds: int) -> str:
    if seconds >= 8640000:  # qBittorrent's "infinity"
        return "∞"
    h, m = divmod(seconds // 60, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def progress_bar(fraction: float, width: int = 10) -> str:
    filled = round(fraction * width)
    return "▓" * filled + "░" * (width - filled)


# ---------------------------------------------------------- download history

def torrent_info_hash(data: bytes) -> str:
    """v1 info-hash (sha1 hex, as qBittorrent reports it) of a .torrent file.

    Minimal bencode walk that finds the raw byte span of the top-level "info"
    dict — no external dependency needed.
    """

    def skip(i: int) -> int:
        c = data[i : i + 1]
        if c == b"i":
            return data.index(b"e", i) + 1
        if c in (b"l", b"d"):
            i += 1
            while data[i : i + 1] != b"e":
                i = skip(i)
            return i + 1
        colon = data.index(b":", i)
        return colon + 1 + int(data[i:colon])

    if data[:1] != b"d":
        raise ValueError("not a bencoded dict")
    i = 1
    while data[i : i + 1] != b"e":
        colon = data.index(b":", i)
        key_len = int(data[i:colon])
        key = data[colon + 1 : colon + 1 + key_len]
        i = colon + 1 + key_len
        j = skip(i)
        if key == b"info":
            return hashlib.sha1(data[i:j]).hexdigest()
        i = j
    raise ValueError("no info dict in torrent")


EPISODE_RE = re.compile(r"[Ss](\d{1,2})[\s._-]?[Ee](\d{1,3})")
SEASON_RE = re.compile(r"[Ss](\d{1,2})(?![0-9Ee])")


def episode_key(title: str) -> tuple[int, int] | None:
    """(season, episode) parsed from a release name. Season packs (no episode
    number) get a high episode value so they rank first in newest-first order."""
    m = EPISODE_RE.search(title)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = SEASON_RE.search(title)
    if m:
        return int(m.group(1)), 999
    return None


def episode_tag(title: str) -> str:
    """Short 'S01E02' / 'S01' tag for display, or '' if none found."""
    m = EPISODE_RE.search(title)
    if m:
        return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    m = SEASON_RE.search(title)
    if m:
        return f"S{int(m.group(1)):02d}"
    return ""


def normalize_name(name: str) -> str:
    """Normalize a release name for matching (dots/spaces/case don't matter).

    HeBits rewrites the internal torrent name of its releases — inserting a
    "HeBits" token and reshuffling separators (e.g. "…H.264-NTb" becomes
    "…H.264.HeBits-NTb") — so that token is stripped too, as are video file
    extensions that qBittorrent shows for single-file torrents.
    """
    name = re.sub(r"\.(mkv|mp4|avi|m2ts|ts|wmv)$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[\W_]+", "", name.lower()).replace("hebits", "")


def local_mark(t: dict) -> str:
    """Short status marker for a release the bot has downloaded before."""
    st = t.get("local")
    if not st:
        return ""
    if st[0] == "done":
        return "✅"
    if st[0] == "dl":
        return f"⏬{st[1]:.0%}"
    return "📥"  # added before: now gone from qBittorrent, or client unreachable


def season_of(title: str) -> int:
    """Season number for bucketing; -1 for releases without an episode tag."""
    k = episode_key(title)
    return k[0] if k else -1


def season_label(season: int) -> str:
    return f"S{season:02d}" if season >= 0 else "Other"
