#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
state="${TRIPSCI_STATE:-$PWD/.state/web}"
python3 backend/app.py --state "$state" --port "${TRIPSCI_API_PORT:-8765}" &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
python3 frontend/serve.py --port "${TRIPSCI_WEB_PORT:-8766}" --backend-port "${TRIPSCI_API_PORT:-8765}"
