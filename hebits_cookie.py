#!/usr/bin/env python3
"""Capture your hebits.net session cookie and store it in .env.

Tries to pull the cookie automatically from your browsers' cookie stores
(close the browser first if extraction fails — some browsers lock the DB).
Falls back to letting you paste the Cookie header manually.

Usage:
    python hebits_cookie.py            # auto-detect from browsers
    python hebits_cookie.py --paste    # skip detection, paste manually
"""

import sys
from pathlib import Path

import requests

HEBITS_URL = "https://hebits.net"
ENV_PATH = Path(__file__).resolve().parent / ".env"
BROWSERS = ("firefox", "chrome", "chromium", "brave", "edge", "opera", "safari")


def validate(cookie: str) -> str | None:
    """Return the logged-in username if the cookie works, else None."""
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


def candidates_from_browsers():
    try:
        import browser_cookie3
    except ImportError:
        print("ℹ browser_cookie3 not installed — can't auto-detect.")
        print("  Install it with:  pip install browser_cookie3")
        return
    for name in BROWSERS:
        loader = getattr(browser_cookie3, name, None)
        if loader is None:
            continue
        try:
            jar = loader(domain_name="hebits.net")
        except Exception as e:
            print(f"  {name}: {e.__class__.__name__} (skipped)")
            continue
        cookies = {c.name: c.value for c in jar}
        if cookies:
            yield name, "; ".join(f"{k}={v}" for k, v in cookies.items())
        else:
            print(f"  {name}: no hebits.net cookies")


def save_to_env(cookie: str) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    lines = [l for l in lines if not l.startswith("HEBITS_COOKIE=")]
    lines.append(f"HEBITS_COOKIE={cookie}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print(f"✔ Saved to {ENV_PATH}")


def main() -> int:
    if "--paste" not in sys.argv:
        print("Looking for hebits.net cookies in your browsers…")
        for browser, cookie in candidates_from_browsers():
            user = validate(cookie)
            if user:
                print(f"✔ Valid session found in {browser} — logged in as “{user}”")
                save_to_env(cookie)
                print("Restart the bot (or use /cookie in Telegram) and you're set.")
                return 0
            print(f"  {browser}: found cookies but the session is not valid")
        print("\nNo valid session found automatically.")
        print("Log in at https://hebits.net (tick “keep me logged in”), then either")
        print("rerun this script, or paste the Cookie header manually below.\n")

    print("Paste the Cookie header value (from DevTools → Network → any hebits.net")
    print("request → Request Headers → Cookie):")
    cookie = input("> ").strip()
    if not cookie:
        print("Nothing pasted, aborting.")
        return 1
    user = validate(cookie)
    if not user:
        print("✘ That cookie didn't work (HeBits doesn't recognize the session).")
        return 1
    print(f"✔ Valid — logged in as “{user}”")
    save_to_env(cookie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
