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
  AGENT_NAME (qnap), INTERVAL_SECONDS (300)

  python qnap_agent.py            # run forever
  python qnap_agent.py --once     # collect once, print the report, exit
  python qnap_agent.py --once --post   # collect once, post it, exit
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
        timeout=20,
    )
    stats = qnap.get_system_stats() or {}
    health = qnap.get_system_health()
    disks = qnap.get_smart_disk_health() or {}
    volumes = qnap.get_volumes() or {}

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
                "status": v.get("status"),
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


def post(report: dict) -> None:
    url = env("WEBAPP_URL").rstrip("/")
    token = env("AGENT_TOKEN")
    if not url or not token:
        raise RuntimeError("WEBAPP_URL and AGENT_TOKEN must be set")
    r = requests.post(
        f"{url}/api/agents/{env('AGENT_NAME', 'qnap')}/report",
        json={"report": report},
        headers={"X-Agent-Token": token},
        timeout=30,
    )
    r.raise_for_status()
    log.info("reported: %s", r.json())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="collect once and exit")
    ap.add_argument("--post", action="store_true", help="with --once: also post the report")
    args = ap.parse_args()
    logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
    interval = int(env("INTERVAL_SECONDS", "300") or 300)

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
        time.sleep(interval)


if __name__ == "__main__":
    main()
