"""External agents: intake of reports posted by agent/qnap_agent.py (which
runs on the Plex Mac next to the QNAP), alerting on bad disks / full volumes /
a silent agent, and the read model the NAS page shows."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from qbit_bot import config
from qbit_bot.jobs import notify
from qbit_bot.storage import load_agents, save_agent_report, set_agent_alerts

log = logging.getLogger("qbit-web")

# set by qbit_web.server when the bot runs the web server (Telegram delivery)
telegram_app = None

GOOD_HEALTH = {"good", "ok", "normal", "healthy", "ready"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_online(entry: dict) -> bool:
    try:
        received = datetime.fromisoformat(entry["received_at"])
    except (KeyError, ValueError):
        return False
    return _now() - received <= timedelta(minutes=config.AGENT_STALE_MINUTES)


def agents_view() -> list[dict]:
    """What the NAS page renders: every agent with its last report and status."""
    out = []
    for name, entry in sorted(load_agents().items()):
        report = entry.get("report") or {}
        out.append(
            {
                "name": name,
                "received_at": entry.get("received_at"),
                "online": is_online(entry),
                "stale_after_minutes": config.AGENT_STALE_MINUTES,
                "alerts": sorted(entry.get("alerts", {})),
                "refresh_pending": bool(entry.get("refresh_requested")),
                "report": report,
            }
        )
    return out


def evaluate(name: str, report: dict) -> dict[str, str]:
    """Alert conditions currently true for a report: key -> human message."""
    active: dict[str, str] = {}
    if not report.get("ok", True):
        active["agent:error"] = f"agent can't read the NAS: {report.get('error') or 'unknown error'}"
        return active
    system = report.get("system") or {}
    health = str(system.get("health") or "").lower()
    if health and health not in GOOD_HEALTH:
        active["system:health"] = f"system health is {system.get('health')}"
    for d in report.get("disks") or []:
        slot = d.get("slot")
        label = f"disk {slot} ({d.get('model') or 'unknown model'})"
        h = str(d.get("health") or "").lower()
        if h and h not in GOOD_HEALTH:
            active[f"disk:{slot}:health"] = f"{label} health is {d.get('health')}"
        temp = d.get("temp_c")
        if isinstance(temp, (int, float)) and temp >= config.NAS_DISK_TEMP_ALERT_C:
            active[f"disk:{slot}:temp"] = f"{label} is at {temp:.0f} °C"
    for v in report.get("volumes") or []:
        used = v.get("used_percent")
        label = f"volume {v.get('label') or '?'}"
        if isinstance(used, (int, float)) and used >= config.NAS_USAGE_ALERT_PERCENT:
            active[f"vol:{v.get('label')}:usage"] = f"{label} is {used:.0f}% full"
        status = str(v.get("status") or "").lower()
        if status and status not in GOOD_HEALTH:
            active[f"vol:{v.get('label')}:status"] = f"{label} status is {v.get('status')}"
    return active


async def ingest(name: str, report: dict) -> dict:
    """Store a report and announce newly raised / cleared alert conditions."""
    entry = save_agent_report(name, report)
    previous = dict(entry.get("alerts") or {})
    active = evaluate(name, report)
    stamp = _now().isoformat(timespec="seconds")

    raised = [active[k] for k in active if k not in previous]
    cleared = [k for k in previous if k not in active and k != "agent:offline"]
    if raised:
        await notify(telegram_app, config.ALLOWED_USER_IDS, {"type": "nas_alert", "agent": name, "messages": raised})
    if cleared:
        msgs = [f"{k.split(':')[0]} {k.split(':')[1]} back to normal" for k in cleared]
        await notify(telegram_app, config.ALLOWED_USER_IDS, {"type": "nas_alert", "agent": name, "messages": msgs, "cleared": True})
    set_agent_alerts(name, {k: previous.get(k, stamp) for k in active})
    return {"stored": True, "alerts": sorted(active)}


async def watchdog() -> None:
    """Background task: announce an agent that stopped reporting (once), and
    that it is back (once)."""
    while True:
        await asyncio.sleep(60)
        try:
            for name, entry in load_agents().items():
                alerts = dict(entry.get("alerts") or {})
                online = is_online(entry)
                if not online and "agent:offline" not in alerts:
                    since = entry.get("received_at", "never")
                    await notify(
                        telegram_app,
                        config.ALLOWED_USER_IDS,
                        {
                            "type": "nas_alert",
                            "agent": name,
                            "messages": [f"no report from the agent since {since}"],
                        },
                    )
                    alerts["agent:offline"] = _now().isoformat(timespec="seconds")
                    set_agent_alerts(name, alerts)
                elif online and "agent:offline" in alerts:
                    alerts.pop("agent:offline")
                    set_agent_alerts(name, alerts)
                    await notify(
                        telegram_app,
                        config.ALLOWED_USER_IDS,
                        {"type": "nas_alert", "agent": name, "messages": ["agent is reporting again"], "cleared": True},
                    )
        except Exception as e:  # never let the loop die
            log.warning("agent watchdog: %s", e)
