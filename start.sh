#!/usr/bin/env bash
# Start QA Pilot at http://localhost:8000 (or the next free port) and open the browser.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Run ./setup.sh first."; exit 1
fi
exec .venv/bin/python backend/serve.py "$@"
