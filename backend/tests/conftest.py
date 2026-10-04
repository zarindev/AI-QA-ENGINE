from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Every test gets its own workspace and secret key; the real .env and workspace/ are never touched."""
    ws = tmp_path / "workspace"
    monkeypatch.setenv("QAP_WORKSPACE", str(ws))
    monkeypatch.setenv("QAP_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("app.core.config.ENV_FILE", tmp_path / ".env")
    return ws


@pytest.fixture
def repo(isolated_workspace):
    from app.storage.repository import Repository

    return Repository()


@pytest.fixture
def settings():
    from app.core.config import get_settings

    return get_settings()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture(scope="session")
def fixture_site():
    """Serve tests/fixtures/site on a random localhost port for the offline crawler tests."""
    handler = functools.partial(_QuietHandler, directory=str(FIXTURES / "site"))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _chrome_ok() -> bool:
    from app.browser.driver import chrome_available

    return chrome_available()


requires_chrome = pytest.mark.skipif(not _chrome_ok(), reason="Google Chrome is not installed")
