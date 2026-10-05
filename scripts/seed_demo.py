"""Reset the three demo apps to their seed data.

A running demo app is reset through its own POST /reset-demo-data route (so it reloads immediately); for an app
that is not running, the working copy is deleted and recreated from the seed on the next start.

    python scripts/seed_demo.py            # all three
    python scripts/seed_demo.py clinic     # one of: clinic, rental, shop
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = {"clinic": ("clinic_app", 8101), "rental": ("car_rental_app", 8102), "shop": ("shop_admin_app", 8103)}


def reset(name: str) -> str:
    folder, port = APPS[name]
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/reset-demo-data", method="POST")
        with urllib.request.urlopen(req, timeout=5):
            return f"{name}: reset (running on :{port})"
    except (urllib.error.URLError, OSError):
        pass
    live_root = os.environ.get("QAP_DEMO_LIVE_DIR", "")
    live = (
        Path(live_root) / folder if live_root else ROOT / "demo_targets" / folder / "data"
    ) / "live_data.json"
    if live.exists():
        live.unlink()
    return f"{name}: not running — seed data will be used on the next start"


def main(argv: list[str]) -> int:
    names = argv or list(APPS)
    unknown = [n for n in names if n not in APPS]
    if unknown:
        print(f"Unknown app(s): {', '.join(unknown)}. Choose from {', '.join(APPS)}.")
        return 2
    for n in names:
        print(reset(n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
