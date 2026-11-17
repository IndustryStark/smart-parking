#!/usr/bin/env bash
# Run on your LAPTOP. Copies the project to the Raspberry Pi (and optionally installs it).
#
#   ./deploy/upload.sh pi@raspberrypi.local              # copy only
#   ./deploy/upload.sh pi@raspberrypi.local --install    # copy, then run the installer on the Pi
#   ./deploy/upload.sh pi@raspberrypi.local --install --kiosk   # also start the entrance screen on boot
set -euo pipefail

TARGET="${1:-}"
[ -n "$TARGET" ] || { echo "usage: $0 user@pi-address [--install] [--kiosk]"; exit 1; }
shift
INSTALL=0; KIOSK=""
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    --kiosk) KIOSK="--kiosk" ;;
    *) echo "unknown option: $arg"; exit 1 ;;
  esac
done

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="smartparking"   # relative to the Pi user's home

# data/ (the database) and venv/ are excluded, so re-uploading never wipes your chips and employees.
rsync -az --delete \
  --exclude 'venv/' --exclude 'data/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude '.git/' --exclude '.claude/' --exclude '*.db' \
  "$SRC/" "$TARGET:$DEST/"
echo "Uploaded to $TARGET:~/$DEST"

if [ "$INSTALL" -eq 1 ]; then
  # -t so sudo can ask for the Pi password
  ssh -t "$TARGET" "cd $DEST && sudo bash deploy/install.sh $KIOSK"
else
  echo "Next, on the Pi:  cd $DEST && sudo bash deploy/install.sh [--kiosk]"
fi
