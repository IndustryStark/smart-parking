#!/usr/bin/env bash
# Called by install.sh --kiosk:  kiosk.sh <user> <home> <port>
# Starts Chromium fullscreen on the entrance page when the desktop starts (Wayland/labwc and X11/LXDE).
set -euo pipefail
APP_USER="$1"; APP_HOME="$2"; PORT="$3"

BROWSER="$(command -v chromium-browser || command -v chromium || true)"
[ -n "$BROWSER" ] || { echo "Chromium not found: sudo apt install chromium-browser"; exit 1; }

CMD="$BROWSER --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 http://localhost:$PORT/entrance"
MARK="# smartparking-kiosk"

add_line() {  # add_line <file> <line>
  local file="$1" line="$2"
  sudo -u "$APP_USER" mkdir -p "$(dirname "$file")"
  [ -f "$file" ] || sudo -u "$APP_USER" touch "$file"
  grep -q "$MARK" "$file" || printf '%s\n%s\n' "$MARK" "$line" | sudo -u "$APP_USER" tee -a "$file" >/dev/null
}

# Wait a few seconds so the service is up before the page loads.
add_line "$APP_HOME/.config/labwc/autostart" "(sleep 8; $CMD) &"
add_line "$APP_HOME/.config/lxsession/LXDE-pi/autostart" "@sh -c 'sleep 8; $CMD'"
echo "Kiosk will start after the next reboot. Boot to desktop with autologin: sudo raspi-config > System Options > Boot / Auto Login."
