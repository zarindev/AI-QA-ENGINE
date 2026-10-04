"""Chrome session wrapper: Selenium 4 (Selenium Manager fetches the driver) + CDP logs.

`BrowserSession` owns one Chrome instance and exposes what the engine needs:
navigation with load timing and document status code, console + network capture, screenshots,
and session export/import (cookies + local/session storage) for saved logins.
"""

from __future__ import annotations

import base64
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options

from app.core.logging import get_logger
from app.storage.schemas import ConsoleEntry, NetworkEvent

log = get_logger("browser")

# Requests that fail for reasons that are not bugs in the site (navigation cancelled, ad blockers, etc.).
_IGNORED_NET_ERRORS = ("net::ERR_ABORTED", "net::ERR_BLOCKED_BY_CLIENT", "net::ERR_CACHE_MISS")


def chrome_available() -> bool:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    if any(Path(c).exists() for c in candidates):
        return True
    return any(
        shutil.which(n)
        for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
    )


@dataclass
class NavigationResult:
    url: str
    status_code: int | None
    load_time_ms: int
    timed_out: bool = False
    error: str = ""


@dataclass
class _NetState:
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)


class BrowserSession:
    def __init__(
        self,
        headless: bool = True,
        width: int = 1440,
        height: int = 900,
        page_load_timeout_s: int = 30,
        user_agent_suffix: str = "QA-Pilot",
    ) -> None:
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={width},{height}")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-search-engine-choice-screen")
        # The password manager's "change your password" / leak warnings block the page after test logins.
        options.add_argument(
            "--disable-features=PasswordLeakDetection,PasswordCheck,AutofillServerCommunication"
        )
        options.add_experimental_option(
            "prefs",
            {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.password_manager_leak_detection": False,
            },
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.set_capability("goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"})
        # A stray alert()/confirm() must never freeze the crawl; confirm() is dismissed (= Cancel), the safe answer.
        options.unhandled_prompt_behavior = "dismiss and notify"
        # "eager" returns at DOMContentLoaded; wait_ready() then waits (bounded) for the load event.
        # With "normal", one slow third-party image can stall the renderer and every command after it.
        options.page_load_strategy = "eager"
        try:
            self.driver = webdriver.Chrome(options=options)
        except WebDriverException as exc:
            raise RuntimeError(
                "Could not start Google Chrome. Install Chrome from https://www.google.com/chrome/ — "
                f"Selenium Manager downloads the matching driver automatically. ({exc.msg})"
            ) from exc
        self.headless = headless
        self.driver.set_page_load_timeout(page_load_timeout_s)
        self.driver.set_script_timeout(20)
        ua = self.driver.execute_script("return navigator.userAgent")
        self.driver.execute_cdp_cmd("Network.enable", {})
        if user_agent_suffix:
            self.driver.execute_cdp_cmd(
                "Network.setUserAgentOverride", {"userAgent": f"{ua} {user_agent_suffix}"}
            )
        self.viewport = (width, height)
        self._net = _NetState()
        self._console: list[ConsoleEntry] = []
        self._network: list[NetworkEvent] = []
        self._documents: list[tuple[str, int]] = []

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        try:
            self.driver.quit()
        except WebDriverException:
            pass

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def browser_version(self) -> str:
        caps = self.driver.capabilities
        return f"{caps.get('browserName', 'chrome').title()} {caps.get('browserVersion', '')}".strip()

    @property
    def current_url(self) -> str:
        return self.driver.current_url

    def set_viewport(self, width: int, height: int) -> None:
        self.driver.set_window_size(width, height)
        self.viewport = (width, height)

    # ------------------------------------------------------------------ logs

    def _pump_logs(self) -> None:
        """Move pending Chrome log entries into our buffers. Chrome clears its buffer on every read."""
        try:
            for entry in self.driver.get_log("browser"):
                level = entry.get("level", "INFO")
                if level in ("SEVERE", "WARNING"):
                    message = entry.get("message", "")
                    self._console.append(
                        ConsoleEntry(
                            level="error" if level == "SEVERE" else "warning",
                            message=message[:2000],
                            source=entry.get("source", ""),
                        )
                    )
            perf = self.driver.get_log("performance")
        except WebDriverException:
            return
        for entry in perf:
            try:
                msg = json.loads(entry["message"])["message"]
            except (KeyError, ValueError):
                continue
            method, params = msg.get("method", ""), msg.get("params", {})
            rid = params.get("requestId", "")
            if method == "Network.requestWillBeSent":
                req = params.get("request", {})
                self._net.requests[rid] = {
                    "url": req.get("url", ""),
                    "method": req.get("method", "GET"),
                    "type": params.get("type", ""),
                }
            elif method == "Network.responseReceived":
                resp = params.get("response", {})
                info = self._net.requests.setdefault(rid, {"url": resp.get("url", ""), "method": "GET"})
                info["status"] = resp.get("status")
                info["type"] = params.get("type", info.get("type", ""))
                status = int(resp.get("status") or 0)
                if info["type"] == "Document":
                    self._documents.append((resp.get("url", ""), status))
                if status >= 400:
                    self._network.append(
                        NetworkEvent(
                            url=resp.get("url", ""),
                            method=info.get("method", "GET"),
                            status=status,
                            resource_type=info.get("type", ""),
                        )
                    )
            elif method == "Network.loadingFailed":
                error = params.get("errorText", "")
                if params.get("canceled") or any(e in error for e in _IGNORED_NET_ERRORS):
                    continue
                info = self._net.requests.get(rid, {})
                self._network.append(
                    NetworkEvent(
                        url=info.get("url", ""),
                        method=info.get("method", "GET"),
                        resource_type=params.get("type", info.get("type", "")),
                        error=error,
                    )
                )
        if len(self._net.requests) > 5000:
            self._net.requests.clear()

    def drain(self) -> tuple[list[ConsoleEntry], list[NetworkEvent]]:
        """Return and clear console errors/warnings and failed requests captured since the last drain."""
        self._pump_logs()
        console, network = self._console, self._network
        self._console, self._network = [], []
        return console, network

    # ------------------------------------------------------------------ navigation

    _READY_PROBE = (
        "const b = document.body;"
        "return [document.readyState,"
        " b ? b.getElementsByTagName('*').length : 0,"
        " performance.getEntriesByType('resource').length,"
        " b ? b.innerText.trim().length : 0];"
    )

    def wait_ready(self, timeout_s: float = 12.0, settle_ms: int = 600) -> None:
        """Wait (bounded) until the page looks finished: load event fired, DOM size and network activity both
        unchanged for `settle_ms`, and the body shows some text.

        Client-rendered apps (React/Vue/Angular) show a spinner while bundles and API calls load; a spinner's DOM
        is stable, so DOM stability alone is not enough — the resource count must also be quiet and the page must
        contain text. Gives up silently at the timeout (a slow page is reported by the checks, not by crashing).
        """
        deadline = time.monotonic() + timeout_s
        last: tuple[int, int] | None = None
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            try:
                state, elements, resources, text_len = self.driver.execute_script(self._READY_PROBE)
            except WebDriverException:
                time.sleep(0.2)
                continue
            now = time.monotonic()
            sig = (elements, resources)
            if sig != last:
                last, stable_since = sig, now
            elif state == "complete" and text_len > 0 and (now - stable_since) * 1000 >= settle_ms:
                return
            time.sleep(0.15)

    def wait_for(self, js_condition: str, timeout_s: float = 10.0) -> bool:
        """Poll a JS boolean expression until true or timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self.driver.execute_script(f"return !!({js_condition});"):
                    return True
            except WebDriverException:
                pass
            time.sleep(0.25)
        return False

    def navigate(self, url: str) -> NavigationResult:
        self._pump_logs()
        self._documents.clear()
        started = time.monotonic()
        timed_out, error = False, ""
        try:
            self.driver.get(url)
        except TimeoutException:
            timed_out = True
            error = "Page load timed out"
            try:
                self.driver.execute_script("window.stop();")
            except WebDriverException:
                pass
        except WebDriverException as exc:
            error = exc.msg or str(exc)
        self.wait_ready()
        elapsed = int((time.monotonic() - started) * 1000)
        try:
            nav_ms = self.driver.execute_script(
                "const n = performance.getEntriesByType('navigation')[0];"
                "return n ? Math.round(n.loadEventEnd || n.domContentLoadedEventEnd || n.duration) : null;"
            )
        except WebDriverException:
            nav_ms = None
        self._pump_logs()
        status = self._documents[-1][1] if self._documents else None
        return NavigationResult(
            url=self.current_url,
            status_code=status,
            load_time_ms=int(nav_ms) if nav_ms else elapsed,
            timed_out=timed_out,
            error=error,
        )

    def screenshot_png(self, full_page: bool = False) -> bytes:
        """PNG bytes of the viewport (or the full page, capped at 8000px). Callers persist via the repository."""
        if not full_page:
            return self.driver.get_screenshot_as_png()
        metrics = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
        size = metrics.get("cssContentSize") or metrics.get("contentSize")
        height = min(int(size["height"]), 8000)
        data = self.driver.execute_cdp_cmd(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": self.viewport[0], "height": height, "scale": 1},
            },
        )["data"]
        return base64.b64decode(data)

    # ------------------------------------------------------------------ saved sessions

    def export_session(self) -> dict[str, Any]:
        """Cookies + web storage for the current origin (stored encrypted in secrets.enc)."""
        storage = self.driver.execute_script(
            "const dump = s => { const o = {}; for (let i = 0; i < s.length; i++) { const k = s.key(i); o[k] = s.getItem(k); } return o; };"
            "return {local: dump(window.localStorage), session: dump(window.sessionStorage)};"
        )
        parsed = urlparse(self.current_url)
        return {
            "origin": f"{parsed.scheme}://{parsed.netloc}",
            "url": self.current_url,
            "cookies": self.driver.get_cookies(),
            "local_storage": storage.get("local", {}),
            "session_storage": storage.get("session", {}),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def import_session(self, saved: dict[str, Any]) -> None:
        self.navigate(saved["origin"] + "/")
        for cookie in saved.get("cookies", []):
            cookie = {
                k: v
                for k, v in cookie.items()
                if k in ("name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite")
            }
            try:
                self.driver.add_cookie(cookie)
            except WebDriverException:
                cookie.pop("domain", None)
                try:
                    self.driver.add_cookie(cookie)
                except WebDriverException as exc:
                    log.warning("Could not restore cookie %s: %s", cookie.get("name"), exc.msg)
        self.driver.execute_script(
            "const [l, s] = arguments; for (const k in l) localStorage.setItem(k, l[k]); for (const k in s) sessionStorage.setItem(k, s[k]);",
            saved.get("local_storage", {}),
            saved.get("session_storage", {}),
        )
