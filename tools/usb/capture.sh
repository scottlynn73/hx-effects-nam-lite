#!/bin/sh
# Run Line 6 Updater with usblog.dylib injected; every libusb call goes to usblog/<time>.txt.
# The Updater behaves exactly as normal. Quit it when done.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
APP=${L6_UPDATER:-"/Applications/Line6/Line 6 Updater.app"}
[ -f "$HERE/usblog.dylib" ] || "$HERE/build_shim.sh"
mkdir -p "$ROOT/usblog"
LOG="$ROOT/usblog/$(date +%Y%m%d-%H%M%S).txt"
if pgrep -xq "HX Edit"; then echo "HX Edit is running: quit it first (it holds the unit)."; exit 1; fi
echo "logging to $LOG"
cd "$ROOT/usblog"   # the Updater looks for its .ini relative to the working folder
USBLOG="$LOG" DYLD_INSERT_LIBRARIES="$HERE/usblog.dylib" "$APP/Contents/MacOS/Line 6 Updater" >"$LOG.stdout" 2>&1
echo "Updater exited; $(wc -l < "$LOG") log lines in $LOG"
