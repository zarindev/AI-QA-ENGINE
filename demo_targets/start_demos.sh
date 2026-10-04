#!/usr/bin/env bash
# Start the three QA Pilot demo apps (clinic :8101, car rental :8102, shop admin :8103). Ctrl+C stops all.
set -e
cd "$(dirname "$0")"
PY="../.venv/bin/python"; [ -x "$PY" ] || PY="python3"
"$PY" clinic_app/app.py "$@" & P1=$!
"$PY" car_rental_app/app.py "$@" & P2=$!
"$PY" shop_admin_app/app.py "$@" & P3=$!
trap 'kill $P1 $P2 $P3 2>/dev/null' INT TERM EXIT
echo ""
echo "  Clinic      http://localhost:8101   admin@carepoint.test / Admin#2026"
echo "  Car rental  http://localhost:8102   admin@drivenow.test  / Admin#2026"
echo "  Shop admin  http://localhost:8103   admin@stockroom.test / Admin#2026"
echo "  (all accounts are listed under 'Demo accounts' on each login page; Ctrl+C to stop)"
wait
