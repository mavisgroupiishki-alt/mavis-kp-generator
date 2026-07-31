#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  echo "Не найдено виртуальное окружение $ROOT/.venv" >&2
  echo "Сначала выполните команды из README: python3 -m venv .venv и pip install -r scripts/requirements.txt" >&2
  exit 1
fi
PLIST="$HOME/Library/LaunchAgents/by.mavis.registry-weekly.plist"
LOG_DIR="$ROOT/logs"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>by.mavis.registry-weekly</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$ROOT/scripts/run_weekly.py</string>
    <string>--publish</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>2</integer>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd-weekly.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd-weekly-error.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID/by.mavis.registry-weekly" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/by.mavis.registry-weekly"

echo "Installed: $PLIST"
echo "Schedule: every Monday at 06:00 local time"
echo "Test now: launchctl kickstart -k gui/$UID/by.mavis.registry-weekly"
