#!/usr/bin/env bash
# One-time setup: Python virtual environment, backend dependencies, frontend dependencies and build.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "Python 3.10 to 3.13 is required (https://www.python.org/downloads/macos/)."; exit 1; }
"$PY" - <<'PYCHK'
import sys
if not ((3, 10) <= sys.version_info[:2] <= (3, 13)):
    sys.exit(f"Python {sys.version.split()[0]} found; 3.10 to 3.13 is required.")
PYCHK
command -v node >/dev/null 2>&1 || { echo "Node.js 18 or newer is required (https://nodejs.org)."; exit 1; }

echo "==> Python environment (backend/.venv) with $("$PY" --version)"
"$PY" -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip wheel >/dev/null
backend/.venv/bin/python -m pip install -r backend/requirements.txt
[ "${DEV:-0}" = "1" ] && backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt

echo "==> Frontend dependencies and build"
(cd desktop && npm install --no-audit --no-fund && npm run build)

mkdir -p models/classification models/segmentation
echo
echo "Done. Next:"
echo "  1. Copy your checkpoints to models/classification/best.pt and models/segmentation/tumor_seg_model.pt"
echo "  2. ./scripts/verify-models.sh"
echo "  3. ./scripts/run.sh"
