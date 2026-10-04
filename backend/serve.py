"""Start QA Pilot: pick a free port (8000 by default), start the server and open the browser.

python backend/serve.py                 # http://localhost:8000 (or the next free port)
python backend/serve.py --port 8010 --no-browser
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred: int, attempts: int = 20) -> int:
    for port in range(preferred, preferred + attempts):
        if port_free(port):
            return port
    raise SystemExit(
        f"No free port between {preferred} and {preferred + attempts - 1}. Use --port to choose one."
    )


def main() -> None:
    import uvicorn

    from app.core.config import get_settings

    settings = get_settings()["server"]
    parser = argparse.ArgumentParser(description="Start the QA Pilot server")
    parser.add_argument("--port", type=int, default=int(settings.get("port", 8000)))
    parser.add_argument("--host", default=settings.get("host", "127.0.0.1"))
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args()

    port = pick_port(args.port)
    if port != args.port:
        print(f"Port {args.port} is busy (another app is using it) - using {port} instead.", flush=True)
    url = f"http://localhost:{port}"
    print(f"\n  QA Pilot is starting at {url}\n  Press Ctrl+C to stop.\n", flush=True)
    if not args.no_browser:

        def open_browser() -> None:
            time.sleep(1.5)
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("app.main:app", host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
