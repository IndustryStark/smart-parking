#!/usr/bin/env bash
# One-step setup for a Raspberry Pi (Raspberry Pi OS). Download the ZIP from GitHub, unzip it, open a terminal
# in the unzipped folder and run:
#
#   sudo bash setup.sh             # install everything; Smart Parking then starts on every boot
#   sudo bash setup.sh --kiosk     # ... and open the entrance screen fullscreen after login
#
# Safe to run again (for example after downloading a newer ZIP into the same folder).
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$SCRIPT")"

FORCE=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;          # install even though this is not a Raspberry Pi (GPIO will not work)
    -h|--help) sed -n '2,8p' "$SCRIPT" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) ARGS+=("$arg") ;;
  esac
done

if [ "$(uname -s)" != "Linux" ]; then
  echo "setup.sh is for Raspberry Pi OS (Linux)."
  echo "To try the project on this computer instead, run:  python3 run.py --mock"
  exit 1
fi
command -v apt-get >/dev/null || { echo "This script needs a Debian-based system such as Raspberry Pi OS (apt-get not found)."; exit 1; }
[ -f deploy/install.sh ] || { echo "deploy/install.sh not found. Run setup.sh from inside the unzipped project folder."; exit 1; }

if ! grep -qs "Raspberry Pi" /proc/device-tree/model; then
  if [ "$FORCE" -ne 1 ]; then
    echo "This does not look like a Raspberry Pi, so the RFID reader, sensors, LED and buttons cannot work here."
    echo "Run it on the Pi, or add --force to install anyway."
    exit 1
  fi
  echo "Warning: not a Raspberry Pi, installing anyway (--force)."
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "Administrator rights are needed to install packages and the service. Asking for sudo..."
  exec sudo bash "$SCRIPT" "$@"
fi

exec bash deploy/install.sh ${ARGS[@]+"${ARGS[@]}"}
