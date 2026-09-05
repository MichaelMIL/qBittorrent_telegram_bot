#!/usr/bin/env python3
"""QNAP monitor agent.

Runs on the machine next to the NAS (the Plex Mac), logs in to the QNAP's web
API with a user + password, reads system health, disk SMART state and volume
usage, and posts one JSON report to the torrent butler's web app every
INTERVAL_SECONDS. The web app stores the latest report, shows it on its NAS
page and alerts (Telegram + Activity) on bad disks, full volumes or silence.

Configure with environment variables or a .env file next to this script:
  QNAP_HOST, QNAP_PORT (8080), QNAP_USER, QNAP_PASSWORD, QNAP_SSL (0/1)
  WEBAPP_URL (e.g. http://192.168.50.20:8765), AGENT_TOKEN (same as the server)
  AGENT_NAME (qnap), INTERVAL_SECONDS (300), CHECKIN_SECONDS (5)
  QNAP_TIMEOUT_SECONDS (20) per QNAP API call, HTTP_TIMEOUT_SECONDS (30) per
  call to the web app

Between reports the agent checks in with the web app every CHECKIN_SECONDS;
when someone presses Refresh on the NAS page it reports immediately.

  python qnap_agent.py            # run forever
  python qnap_agent.py --once     # collect once, print the report, exit
  python qnap_agent.py --once --post   # collect once, post it, exit
  python qnap_agent.py --raw      # dump the QNAP's raw volume/disk answers
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # python-dotenv is optional
    pass

log = logging.getLogger("qnap-agent")

GOOD = {"good", "ok", "normal", "healthy", "ready"}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def collect() -> dict:
    """One report from the QNAP via python-qnapstats (Home Assistant's client)."""
    from qnapstats import QNAPStats  # imported here so --help works without it

    host, port = env("QNAP_HOST"), int(env("QNAP_PORT", "8080") or 8080)
    if not host or not env("QNAP_USER"):
        raise RuntimeError("QNAP_HOST and QNAP_USER (and QNAP_PASSWORD) must be set")
    qnap = QNAPStats(
        host,
        port,
        env("QNAP_USER"),
        env("QNAP_PASSWORD"),
        verify_ssl=env("QNAP_SSL", "0") == "1",
        timeout=int(env("QNAP_TIMEOUT_SECONDS", "20") or 20),
    )
    stats = qnap.get_system_stats() or {}
    health = qnap.get_system_health()
    disks = qnap.get_smart_disk_health() or {}
    volumes = qnap.get_volumes() or {}
    statuses = volume_statuses(qnap)

    system = stats.get("system", {})
    up = stats.get("uptime", {})
    uptime_seconds = (
        up.get("days", 0) * 86400 + up.get("hours", 0) * 3600 + up.get("minutes", 0) * 60 + up.get("seconds", 0)
    )
    report = {
        "kind": "qnap",
        "ok": True,
        "error": None,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": {
            "name": system.get("name"),
            "model": system.get("model"),
            "firmware": (stats.get("firmware") or {}).get("version"),
            "health": health,
            "uptime_seconds": uptime_seconds,
            "temp_c": system.get("temp_c"),
            "cpu_percent": (stats.get("cpu") or {}).get("usage_percent"),
            "cpu_temp_c": (stats.get("cpu") or {}).get("temp_c"),
            "memory_total_mb": (stats.get("memory") or {}).get("total"),
            "memory_free_mb": (stats.get("memory") or {}).get("free"),
        },
        "disks": [],
        "volumes": [],
    }
    for key in sorted(disks, key=lambda k: int(str(k)) if str(k).isdigit() else str(k)):
        d = disks[key]
        report["disks"].append(
            {
                "slot": d.get("drive_number"),
                "model": d.get("model"),
                "serial": d.get("serial"),
                "capacity": d.get("capacity"),
                "type": d.get("type"),
                "health": d.get("health"),
                "temp_c": d.get("temp_c"),
            }
        )
    for label, v in sorted(volumes.items()):
        total, free = v.get("total_size"), v.get("free_size")
        used_percent = None
        if isinstance(total, (int, float)) and total and isinstance(free, (int, float)):
            used_percent = round((total - free) / total * 100, 1)
        report["volumes"].append(
            {
                "label": label,
                "id": v.get("id"),
                "status": statuses.get(str(v.get("id"))) or statuses.get(label) or v.get("status"),
                "total_bytes": total,
                "free_bytes": free,
                "used_percent": used_percent,
                "folders": [
                    {"name": f.get("sharename"), "used_bytes": f.get("used_size")}
                    for f in (v.get("folders") or [])
                ],
            }
        )
    return report


VOLUME_QUERY = "management/chartReq.cgi?chart_func=disk_usage&disk_select=all&include=all"
STATUS_KEYS = ("volumeStatus", "volume_status", "status", "volumeState", "state")


def volume_statuses(qnap) -> dict:
    """volume id / label -> status text, read from the same chartReq answer
    qnapstats uses for sizes (it doesn't expose the status itself). Empty
    when the firmware doesn't include one."""
    try:
        raw = qnap._get_url(VOLUME_QUERY, force_list=("volume", "volumeUse", "folder_element"))
    except Exception as e:  # noqa: BLE001 - never fail the report over this
        log.debug("volume status lookup failed: %s", e)
        return {}
    out = {}
    if not raw or not raw.get("volumeList"):
        return out
    for vol in raw["volumeList"].get("volume") or []:
        if not isinstance(vol, dict):
            continue
        status = next((str(vol[k]) for k in STATUS_KEYS if vol.get(k) not in (None, "")), None)
        if status is None:
            continue
        for key in (vol.get("volumeValue"), vol.get("volumeLabel")):
            if key not in (None, ""):
                out[str(key)] = status
    return out


def dump_raw() -> None:
    """Print the QNAP's raw volume and disk answers (field names differ a bit
    between firmware versions; this is what to send when something reads
    'unknown')."""
    from qnapstats import QNAPStats

    qnap = QNAPStats(
        env("QNAP_HOST"),
        int(env("QNAP_PORT", "8080") or 8080),
        env("QNAP_USER"),
        env("QNAP_PASSWORD"),
        verify_ssl=env("QNAP_SSL", "0") == "1",
        timeout=int(env("QNAP_TIMEOUT_SECONDS", "20") or 20),
    )
    raw = qnap._get_url(VOLUME_QUERY, force_list=("volume", "volumeUse", "folder_element")) or {}
    # sizes only — drop the per-folder lists, they are long and not in question
    for vol in (raw.get("volumeUseList") or {}).get("volumeUse") or []:
        vol.pop("folder_element", None)
    print(json.dumps({"volumes": raw}, indent=1, default=str, ensure_ascii=False))
    disks = qnap._get_url("disk/qsmart.cgi?func=all_hd_data", force_list=("entry",)) or {}
    print(json.dumps({"disks": disks}, indent=1, default=str, ensure_ascii=False))


def _server() -> tuple[str, dict]:
    url = env("WEBAPP_URL").rstrip("/")
    token = env("AGENT_TOKEN")
    if not url or not token:
        raise RuntimeError("WEBAPP_URL and AGENT_TOKEN must be set")
    return f"{url}/api/agents/{env('AGENT_NAME', 'qnap')}", {"X-Agent-Token": token}


def _http_timeout() -> int:
    return int(env("HTTP_TIMEOUT_SECONDS", "30") or 30)


def post(report: dict) -> None:
    base, headers = _server()
    r = requests.post(
        f"{base}/report", json={"report": report}, headers=headers, timeout=_http_timeout()
    )
    r.raise_for_status()
    log.info("reported: %s", r.json())


def refresh_requested() -> bool:
    """Ask the web app whether someone pressed Refresh since the last report."""
    base, headers = _server()
    r = requests.get(f"{base}/poll", headers=headers, timeout=_http_timeout())
    r.raise_for_status()
    return bool(r.json().get("refresh"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="collect once and exit")
    ap.add_argument("--post", action="store_true", help="with --once: also post the report")
    ap.add_argument("--raw", action="store_true", help="dump the QNAP's raw volume/disk answers and exit")
    args = ap.parse_args()
    if args.raw:
        dump_raw()
        return
    logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
    interval = int(env("INTERVAL_SECONDS", "300") or 300)
    checkin = max(2, int(env("CHECKIN_SECONDS", "5") or 5))

    while True:
        try:
            report = collect()
        except Exception as e:
            log.error("collect failed: %s", e)
            report = {
                "kind": "qnap",
                "ok": False,
                "error": f"{e.__class__.__name__}: {e}",
                "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        if args.once and not args.post:
            json.dump(report, sys.stdout, indent=1)
            print()
            return
        try:
            post(report)
        except Exception as e:
            log.error("post failed: %s", e)
        if args.once:
            return
        # sleep until the next report, waking early if a refresh is requested
        deadline = time.monotonic() + interval
        while time.monotonic() < deadline:
            time.sleep(min(checkin, max(0, deadline - time.monotonic())))
            try:
                if refresh_requested():
                    log.info("refresh requested from the app")
                    break
            except Exception as e:
                log.warning("check-in failed: %s", e)


if __name__ == "__main__":
    main()
