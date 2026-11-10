#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
node --check apps/web/workspace.js
PYTHONPATH="$PWD/tripsci" PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python3}" -m unittest discover -s tests/backend -v
