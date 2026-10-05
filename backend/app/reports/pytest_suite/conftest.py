"""pytest fixtures: Chrome driver, base URL and role login. Settings come from environment variables or .env."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from pages.login import LoginPage
from selenium import webdriver
from site_config import DEFAULT_BASE_URL, LOGIN_PATHS


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def role_key(role: str) -> str:
    return re.sub(r"\W+", "_", role).strip("_").upper()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--site", default=None, help="Base URL of the site under test (overrides QAP_BASE_URL)")


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    return (request.config.getoption("--site") or os.environ.get("QAP_BASE_URL") or DEFAULT_BASE_URL).rstrip(
        "/"
    )


@pytest.fixture
def driver():
    opts = webdriver.ChromeOptions()
    if os.environ.get("QAP_HEADLESS", "1") != "0":
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1440,900")
    opts.set_capability("unhandledPromptBehavior", "dismiss and notify")
    d = webdriver.Chrome(options=opts)
    d.set_page_load_timeout(60)
    # Tests that delete or complete records confirm the browser dialog, as QA Pilot's Full Mode did.
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": "window.confirm = () => true;"})
    yield d
    d.quit()


@pytest.fixture
def viewport(driver):
    """Emulate an exact viewport size, e.g. viewport(390, 844) for a phone."""

    def _set(width: int, height: int) -> None:
        driver.execute_cdp_cmd(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 800},
        )

    return _set


@pytest.fixture
def login(driver, base_url):
    """login("admin") signs in with QAP_ADMIN_USERNAME / QAP_ADMIN_PASSWORD; tests skip when they are not set."""

    def _login(role: str) -> None:
        if not role or role == "public":
            return
        key = role_key(role)
        user, password = os.environ.get(f"QAP_{key}_USERNAME"), os.environ.get(f"QAP_{key}_PASSWORD")
        if not user or not password:
            pytest.skip(f"Set QAP_{key}_USERNAME and QAP_{key}_PASSWORD to run tests as {role}")
        LoginPage(driver, base_url).login(LOGIN_PATHS.get(role, "/"), user, password)

    return _login
