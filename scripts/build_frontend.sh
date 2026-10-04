#!/usr/bin/env bash
# Rebuild the React UI into backend/app/static (only needed if you change the UI; requires Node.js 20+).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm install --no-audit --no-fund
npm run build
echo "UI built into backend/app/static - commit it so users don't need Node.js."
