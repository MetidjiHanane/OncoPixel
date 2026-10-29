#!/usr/bin/env bash
# Check that the checkpoints match their architectures and run on this machine. Extra arguments are passed on:
#   ./scripts/verify-models.sh --image slice.png --device cpu --out verify-report.json
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x backend/.venv/bin/python ] || { echo "Run ./scripts/setup-mac.sh first."; exit 1; }
cd backend
exec .venv/bin/python scripts/verify_checkpoints.py "$@"
