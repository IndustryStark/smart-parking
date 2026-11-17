#!/usr/bin/env bash
# Run ON THE PI, from the project folder:  sudo bash deploy/install.sh [--kiosk]
# Safe to run again after every upload: it only adds what is missing and restarts the service.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo:  sudo bash deploy/install.sh"; exit 1; }

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="${SUDO_USER:-}"
[ -n "$APP_USER" ] && [ "$APP_USER" != "root" ] || { echo "Run it with sudo from your normal user, not as root."; exit 1; }
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
KIOSK=0
for arg in "$@"; do
  case "$arg" in
    --kiosk) KIOSK=1 ;;
    *) echo "unknown option: $arg  (use --kiosk)"; exit 1 ;;
  esac
done
PORT=5000

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y python3-venv python3-pip python3-gpiozero python3-lgpio python3-spidev rsync
# mfrc522 needs the RPi.GPIO API: Pi 5 uses the rpi-lgpio shim, older Pis the classic package.
if ! python3 -c "import RPi.GPIO" 2>/dev/null; then
  apt-get install -y python3-rpi-lgpio || apt-get install -y python3-rpi.gpio
fi

echo "==> Enabling SPI (needed by the RFID reader)"
raspi-config nonint do_spi 0 || echo "   could not enable SPI automatically: run 'sudo raspi-config' > Interface Options > SPI"

echo "==> Giving $APP_USER access to GPIO and SPI"
usermod -aG gpio,spi "$APP_USER"

echo "==> Python environment"
# --system-site-packages: use the apt-provided gpiozero/lgpio/spidev that match this Pi model.
sudo -u "$APP_USER" python3 -m venv --system-site-packages "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements-pi.txt"
# --no-deps: do not let pip replace the system RPi.GPIO / spidev with builds that do not fit this Pi.
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet --no-deps mfrc522
sudo -u "$APP_USER" mkdir -p "$APP_DIR/data"


ENV_FILE=/etc/smartparking.env
if [ ! -f "$ENV_FILE" ]; then
  echo "==> Creating $ENV_FILE with a random admin password"
  ADMIN_PW="$(openssl rand -base64 12 | tr -d '/+=')"
  umask 077
  cat > "$ENV_FILE" <<EOF
PARKING_ADMIN_PASSWORD=$ADMIN_PW
PARKING_SECRET=$(openssl rand -hex 24)
PARKING_RESERVATION_S=180
EOF
  echo "    Admin password: $ADMIN_PW   (stored in $ENV_FILE, change it there and restart the service)"
fi

echo "==> Installing the systemd service"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@APP_USER@|$APP_USER|g" \
  "$APP_DIR/deploy/smartparking.service" > /etc/systemd/system/smartparking.service
systemctl daemon-reload
systemctl enable smartparking.service >/dev/null
systemctl restart smartparking.service

if [ "$KIOSK" -eq 1 ]; then
  echo "==> Setting up the entrance screen (Chromium kiosk) for $APP_USER"
  bash "$APP_DIR/deploy/kiosk.sh" "$APP_USER" "$APP_HOME" "$PORT"
fi

sleep 2
echo
systemctl --no-pager --lines=5 status smartparking.service || true
IP="$(hostname -I | awk '{print $1}')"
echo
echo "Done. From any device on the network:"
echo "  Live map:        http://$IP:$PORT/"
echo "  Entrance screen: http://$IP:$PORT/entrance"
echo "  Admin panel:     http://$IP:$PORT/admin"
echo "Logs:   journalctl -u smartparking -f"
echo "If SPI or the gpio group were just enabled, reboot once:  sudo reboot"
