#!/usr/bin/env bash
# Install the QNAP agent on macOS so it runs at login and restarts on failure.
#
#   ./install_mac.sh              install / update (from the agent/ folder of the repo)
#   ./install_mac.sh --daemon     run at boot without a login (needs sudo)
#   ./install_mac.sh --uninstall  stop and remove
#
# Copies the agent to ~/qnap-agent (keeping an existing .env), creates a venv,
# installs requirements, writes the launchd job with the right paths and loads it.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${QNAP_AGENT_DIR:-$HOME/qnap-agent}"
LABEL="com.qbit.qnap-agent"
MODE="agent"
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --daemon) MODE="daemon" ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 1 ;;
  esac
done

if [ "$MODE" = "daemon" ]; then
  PLIST="/Library/LaunchDaemons/$LABEL.plist"; SUDO="sudo"; DOMAIN="system"
else
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"; SUDO=""; DOMAIN="gui/$(id -u)"
fi

stop_job() {
  $SUDO launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
}

if [ "$UNINSTALL" -eq 1 ]; then
  stop_job
  $SUDO rm -f "$PLIST"
  echo "removed $PLIST (the folder $DEST and its .env were left in place)"
  exit 0
fi

echo "==> installing the agent into $DEST"
mkdir -p "$DEST"
cp "$SRC/qnap_agent.py" "$SRC/requirements.txt" "$DEST/"
[ -f "$DEST/.env" ] || cp "$SRC/.env.example" "$DEST/.env"
if [ ! -x "$DEST/.venv/bin/python" ]; then
  python3 -m venv "$DEST/.venv"
fi
"$DEST/.venv/bin/pip" install -q --upgrade -r "$DEST/requirements.txt"

if grep -qE '^(QNAP_PASSWORD|AGENT_TOKEN)=\s*$' "$DEST/.env"; then
  echo
  echo "!! $DEST/.env still has empty values. Fill in QNAP_HOST/USER/PASSWORD,"
  echo "   WEBAPP_URL and AGENT_TOKEN, then run this script again."
  echo "   Test first with:  $DEST/.venv/bin/python $DEST/qnap_agent.py --once"
  exit 1
fi

echo "==> test run (one report)"
if ! "$DEST/.venv/bin/python" "$DEST/qnap_agent.py" --once --post; then
  echo "!! the agent could not collect or post a report — fix .env and retry" >&2
  exit 1
fi

echo "==> writing $PLIST"
stop_job
TMP="$(mktemp)"
cat > "$TMP" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DEST/.venv/bin/python</string>
    <string>$DEST/qnap_agent.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/qnap-agent.log</string>
  <key>StandardErrorPath</key><string>/tmp/qnap-agent.log</string>
</dict>
</plist>
PLIST
$SUDO mkdir -p "$(dirname "$PLIST")"
$SUDO cp "$TMP" "$PLIST"; rm -f "$TMP"
if [ "$MODE" = "daemon" ]; then $SUDO chown root:wheel "$PLIST"; $SUDO chmod 644 "$PLIST"; fi
$SUDO launchctl bootstrap "$DOMAIN" "$PLIST"

sleep 2
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "==> running. Log: tail -f /tmp/qnap-agent.log"
  echo "    stop:    $SUDO launchctl bootout $DOMAIN/$LABEL"
  echo "    restart: $SUDO launchctl kickstart -k $DOMAIN/$LABEL   (after editing .env)"
  echo "    remove:  $0 --uninstall${MODE:+ }$( [ "$MODE" = daemon ] && echo --daemon )"
else
  echo "!! launchd did not start the job; see /tmp/qnap-agent.log" >&2
  exit 1
fi
