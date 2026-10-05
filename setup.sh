#!/usr/bin/env bash
# QA Pilot setup (macOS / Linux): virtual environment, dependencies, .env, Chrome check.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for cand in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and run ./setup.sh again."
  exit 1
fi
echo "Using $($PY --version)"

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
echo "Dependencies installed."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env (add your ANTHROPIC_API_KEY there, or paste it in the app)."
fi
mkdir -p workspace
if [ -d .git ]; then git config core.hooksPath .githooks && echo "Secret check enabled for git commits."; fi

.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "backend")
from app.browser.driver import chrome_available
print("Google Chrome: found" if chrome_available() else "Google Chrome: NOT FOUND - install it from https://www.google.com/chrome/")
PY

if [ ! -f backend/app/static/index.html ]; then
  echo "Note: the UI build is missing. Run scripts/build_frontend.sh (needs Node.js) or use a release that includes it."
fi
echo ""
echo "Setup complete. Start QA Pilot with:  ./start.sh"
