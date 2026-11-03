#!/bin/sh
# Build tools/usb/usblog.dylib (x86_64) against the Updater's own libusb.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
APP=${L6_UPDATER:-"/Applications/Line6/Line 6 Updater.app"}
clang -arch x86_64 -dynamiclib -O1 -Wall -o "$HERE/usblog.dylib" "$HERE/usblog.c" \
    "$APP/Contents/MacOS/libusb-1.0.0.dylib"
codesign -f -s - "$HERE/usblog.dylib" >/dev/null 2>&1 || true
echo "built $HERE/usblog.dylib"
