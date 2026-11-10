#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
app="${1:-$PWD/.build/TripSci.app}"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/backend"
mkdir -p .build/module-cache
/usr/bin/swiftc -module-cache-path "$PWD/.build/module-cache" -O -parse-as-library -target "$(uname -m)-apple-macosx14.0" macos/TripSci.swift -o "$app/Contents/MacOS/TripSci"
cp backend/{app,server,scheduler,worker,mock_training,native_api,iris,beans,name_llm,runtime,run_workspace,storage,main_chat,codex_environment}.py "$app/Contents/Resources/backend/"
cp -R backend/actions backend/execution backend/agents backend/research backend/skills backend/datasets "$app/Contents/Resources/backend/"
cp macos/TripSci-icon.png "$app/Contents/Resources/"
iconset="$(mktemp -d)"
trap 'rm -rf "$iconset"' EXIT
for size in 16 32 64 128 256 512 1024; do
  sips -z "$size" "$size" macos/TripSci-icon.png --out "$iconset/$size.png" >/dev/null
done
python3 - "$iconset" "$app/Contents/Resources/TripSci.icns" <<'PYICON'
from pathlib import Path
import struct
import sys
root, output = map(Path, sys.argv[1:])
chunks = []
for size, tag in [(16,b"icp4"),(32,b"icp5"),(64,b"icp6"),(128,b"ic07"),(256,b"ic08"),(512,b"ic09"),(1024,b"ic10")]:
    png = (root / f"{size}.png").read_bytes()
    chunks.append(tag + struct.pack(">I",len(png)+8) + png)
body = b"".join(chunks)
output.write_bytes(b"icns" + struct.pack(">I",len(body)+8) + body)
PYICON
cp macos/Info.plist "$app/Contents/Info.plist"
codesign --force --sign - "$app"
printf '%s\n' "$app"
