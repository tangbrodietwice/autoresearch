#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
node --check frontend/workspace.js
PYTHONDONTWRITEBYTECODE=1 "${PYTHON:-python3}" -m unittest discover -s backend -v
