#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s backend -v
scripts/build-macos.sh
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
mkdir -p "$test_root/TripSci.app/Contents/MacOS"
cp -R .build/TripSci.app/Contents/Resources "$test_root/TripSci.app/Contents/"
cp .build/TripSci.app/Contents/Info.plist "$test_root/TripSci.app/Contents/"
/usr/bin/swiftc -module-cache-path "$PWD/.build/module-cache" -parse-as-library -D TRIPSCI_SMOKE -target "$(uname -m)-apple-macosx14.0" macos/{TripSci,NativeSmoke}.swift -o "$test_root/TripSci.app/Contents/MacOS/TripSci"
TRIPSCI_STATE="$test_root/state" "$test_root/TripSci.app/Contents/MacOS/TripSci"
codesign --verify --strict .build/TripSci.app
