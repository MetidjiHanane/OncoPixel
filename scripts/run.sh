#!/usr/bin/env bash
# Start OncoPixel (desktop window). Use --browser to serve the interface at http://127.0.0.1:8765 instead.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x backend/.venv/bin/python ] || { echo "Run ./scripts/setup-mac.sh first."; exit 1; }
[ -d desktop/dist ] || (cd desktop && npm run build)
if [ "${1:-}" = "--browser" ]; then
  cd backend
  echo "Open http://127.0.0.1:8765 (no Electron, no per-launch token: development use only)"
  exec .venv/bin/python -m oncopixel.server --port 8765
fi
cd desktop
[ -d node_modules ] || npm install --no-audit --no-fund
export ONCOPIXEL_PYTHON="$(cd .. && pwd)/backend/.venv/bin/python"
exec npx electron .
