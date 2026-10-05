"""Capture the README / case-study screenshots from a finished demo run.

Starts QA Pilot on a free port (or uses --url), opens every major screen at 1440×900 with 2× device scale and saves
PNGs to docs/assets/screenshots/ (dark mode; light mode too for the three key screens). Only demo apps are shown.

    python scripts/capture_screenshots.py                          # latest run of the clinic demo
    python scripts/capture_screenshots.py --project drivenow-rentals --bug BUG-003
    python scripts/capture_screenshots.py --live                   # also the Live Run Viewer (a run must be running)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.browser.driver import BrowserSession  # noqa: E402

OUT = ROOT / "docs" / "assets" / "screenshots"
LIGHT_TOO = {"run-overview", "bug-detail", "quality"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


def wait_for(url: str, seconds: int = 60) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            get(f"{url}/api/health")
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"QA Pilot did not start at {url}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="use an already running QA Pilot instead of starting one")
    ap.add_argument("--project", default="carepoint-clinic")
    ap.add_argument("--run", help="run id (default: latest)")
    ap.add_argument("--bug", help="bug for the detail screenshot (default: first critical)")
    ap.add_argument("--live", action="store_true", help="capture the Live Run Viewer of a running run")
    ap.add_argument("--only", nargs="*", help="names of screenshots to (re)take")
    args = ap.parse_args()

    server = None
    base = args.url
    if not base:
        port = free_port()
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "backend" / "serve.py"), "--port", str(port), "--no-browser"],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"
    base = base.rstrip("/")
    try:
        wait_for(base)
        for p in get(f"{base}/api/projects"):  # computes Quality Scores of runs made before scores existed
            latest = p.get("latest_run") or {}
            if latest.get("id"):
                try:
                    get(f"{base}/api/projects/{p['slug']}/runs/{latest['id']}/quality")
                except OSError:
                    pass
        runs = get(f"{base}/api/projects/{args.project}/runs")
        run = args.run or runs[0]["id"]
        bugs = get(f"{base}/api/projects/{args.project}/runs/{run}/bugs")["bugs"]
        bug = args.bug or next((b["id"] for b in bugs if b["severity"] == "critical"), bugs[0]["id"])
        r = f"/projects/{args.project}/runs/{run}"
        shots = [
            ("projects", "/", None),
            ("new-project", "/projects/new", None),
            ("project", f"/projects/{args.project}", None),
            ("run-overview", r, None),
            ("site-profile", f"{r}/profile", None),
            ("site-model", f"{r}/model", None),
            ("requirements", f"{r}/requirements", None),
            ("test-cases", f"{r}/tests", None),
            ("results", f"{r}/results", None),
            ("results-drawer", f"{r}/results", "tbody tr:nth-child(2)"),
            ("bugs", f"{r}/bugs", None),
            ("bug-detail", f"{r}/bugs/{bug}", None),
            ("permission-matrix", f"{r}/permissions", None),
            ("quality", f"{r}/quality", None),
            ("reports", f"{r}/reports", None),
            ("settings", "/settings", None),
            ("onboarding", "/onboarding", None),
        ]
        if args.live:
            shots.append(("live-run-viewer", r, None))
        OUT.mkdir(parents=True, exist_ok=True)
        with BrowserSession(headless=True, width=1440, height=900) as s:
            s.driver.execute_cdp_cmd(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1440, "height": 900, "deviceScaleFactor": 2, "mobile": False},
            )
            for theme in ("dark", "light"):
                s.navigate(base + "/")
                s.driver.execute_script(f"localStorage.setItem('qap-theme', '{theme}')")
                for name, path, click in shots:
                    if theme == "light" and name not in LIGHT_TOO:
                        continue
                    if args.only and name not in args.only:
                        continue
                    s.navigate(base + path)
                    time.sleep(3.5 if name in ("site-model", "run-overview") else 2.5)
                    if click:
                        s.driver.execute_script(f"document.querySelector('{click}')?.click()")
                        time.sleep(2.5)
                    file = OUT / (f"{name}.png" if theme == "dark" else f"{name}-light.png")
                    file.write_bytes(s.driver.get_screenshot_as_png())
                    print(file.relative_to(ROOT))
            s.navigate(base + "/")
            s.driver.execute_script("localStorage.setItem('qap-theme', 'dark')")
    finally:
        if server:
            server.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
