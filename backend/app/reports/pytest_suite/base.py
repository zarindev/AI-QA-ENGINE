"""Base page object: multi-strategy locators, actions and checks shared by every page.

Each locator stores several independent ways to find the same element (test id, id, name, aria-label, label,
placeholder, visible text, CSS, XPath). The first strategy that matches exactly one visible element wins, so a
test survives most markup changes.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select, WebDriverWait

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

ERROR_PAGE = re.compile(
    r"Internal Server Error|Traceback \(most recent call last\)|\b(Fatal error|Parse error):|SQLSTATE\[|"
    r"Uncaught \w*Exception|\b(404|Page) Not Found\b|Something went wrong|\[object Object\]|\bNaN\b",
    re.I,
)
DENIED = re.compile(
    r"\b(403|forbidden|not authori[sz]ed|unauthori[sz]ed|access denied|permission|not allowed|no access|"
    r"sign in|log in)\b",
    re.I,
)


def _literal(text: str) -> str:
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in text.split("'")) + ")"


@dataclass(frozen=True)
class Loc:
    """One element, several ways to find it."""

    id: str = ""
    name: str = ""
    test_id: str = ""
    aria_label: str = ""
    label: str = ""
    placeholder: str = ""
    text: str = ""
    css: str = ""
    xpath: str = ""
    tag: str = ""

    def strategies(self) -> list[tuple[str, str]]:
        tag = self.tag or "*"
        out: list[tuple[str, str]] = []
        if self.test_id:
            t = self.test_id
            out.append(
                (By.CSS_SELECTOR, f'[data-testid="{t}"], [data-test="{t}"], [data-qa="{t}"], [data-cy="{t}"]')
            )
        if self.id:
            out.append((By.ID, self.id))
        if self.name:
            out.append((By.CSS_SELECTOR, f'{tag}[name="{self.name}"]'))
        if self.aria_label:
            out.append((By.CSS_SELECTOR, f'{tag}[aria-label="{self.aria_label}"]'))
        if self.label:
            lit = _literal(self.label)
            out.append(
                (
                    By.XPATH,
                    f"//label[normalize-space()={lit}]/following::*[self::input or self::select or self::textarea][1]"
                    f" | //*[@id=//label[normalize-space()={lit}]/@for]",
                )
            )
        if self.placeholder:
            out.append((By.CSS_SELECTOR, f'[placeholder="{self.placeholder}"]'))
        if self.text:
            out.append((By.XPATH, f"//{tag}[normalize-space()={_literal(self.text)}]"))
        if self.css:
            out.append((By.CSS_SELECTOR, self.css))
        if self.xpath:
            out.append((By.XPATH, self.xpath))
        return out

    def __str__(self) -> str:
        parts = [f"{k}={v!r}" for k, v in self.__dict__.items() if v and k not in ("css", "xpath")]
        return "Loc(" + ", ".join(parts) + ")"


class BasePage:
    def __init__(self, driver: WebDriver, base_url: str) -> None:
        self.driver = driver
        self.base_url = base_url.rstrip("/") + "/"

    # ------------------------------------------------------------ navigation

    def open(self, path: str) -> None:
        self.driver.get(urljoin(self.base_url, path.lstrip("/")))
        self.wait_ready()

    def path(self) -> str:
        return urlparse(self.driver.current_url).path or "/"

    def wait_ready(self, timeout: float = 15) -> None:
        WebDriverWait(self.driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
        )
        time.sleep(0.3)  # let client-side scripts settle

    # ------------------------------------------------------------ elements

    def find(self, loc: Loc, timeout: float = 10) -> WebElement:
        deadline = time.monotonic() + timeout
        while True:
            for by, value in loc.strategies():
                try:
                    found = [
                        e
                        for e in self.driver.find_elements(by, value)
                        if e.is_displayed() or e.tag_name == "input"
                    ]
                except (WebDriverException, StaleElementReferenceException):
                    continue
                if len(found) == 1:
                    return found[0]
            if time.monotonic() > deadline:
                raise NoSuchElementException(f"No single element matches {loc} on {self.driver.current_url}")
            time.sleep(0.4)

    def click(self, loc: Loc) -> None:
        el = self.find(loc)
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", el)
        try:
            el.click()
        except ElementClickInterceptedException:
            self.driver.execute_script("arguments[0].click()", el)
        self.wait_ready()

    def type(self, loc: Loc, text: str) -> None:
        el = self.find(loc)
        if el.get_attribute("type") in ("date", "time", "datetime-local"):
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
                "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                el,
                text,
            )
            return
        el.clear()
        el.send_keys(text)

    def select(self, loc: Loc, option: str) -> None:
        sel = Select(self.find(loc))
        try:
            sel.select_by_visible_text(option)
        except NoSuchElementException:
            match = next((o for o in sel.options if option.lower() in o.text.lower()), None)
            if match is None:
                sel.select_by_value(option)
            else:
                match.click()

    def check(self, loc: Loc) -> None:
        el = self.find(loc)
        if not el.is_selected():
            self.driver.execute_script("arguments[0].click()", el)

    def upload(self, loc: Loc, filename: str = "qap-test-upload.txt") -> None:
        self.find(loc).send_keys(str(FIXTURES / filename))

    def scroll(self, direction: str = "down") -> None:
        self.driver.execute_script(
            f"window.scrollBy(0, {'-' if direction == 'up' else ''}window.innerHeight * 0.8)"
        )

    # ------------------------------------------------------------ checks

    def text(self) -> str:
        return self.driver.execute_script("return document.body ? document.body.innerText : ''") or ""

    def assert_contains(self, *expected: str) -> None:
        body = self.text()
        missing = [e for e in expected if e not in body]
        assert not missing, f"Expected to see {missing} on {self.driver.current_url}"

    def assert_no_error_page(self) -> None:
        m = ERROR_PAGE.search(f"{self.driver.title}\n{self.text()}")
        assert m is None, f"Error text “{m.group(0)}” on {self.driver.current_url}" if m else ""

    def has_login_form(self) -> bool:
        return bool(self.driver.find_elements(By.CSS_SELECTOR, "input[type=password]"))

    def access_refused(self, target_path: str) -> tuple[bool, str]:
        """True when the app refused the page: login wall, redirect away, or an access-denied message."""
        if self.has_login_form():
            return True, "login page shown"
        if self.path().rstrip("/") != target_path.rstrip("/"):
            return True, f"redirected to {self.path()}"
        headings = " ".join(h.text for h in self.driver.find_elements(By.CSS_SELECTOR, "h1, h2"))
        if DENIED.search(f"{self.driver.title} {headings}"):
            return True, "access-denied message"
        return False, f"opened “{self.driver.title}”"

    def overflow_x(self) -> int:
        return int(
            self.driver.execute_script(
                "return Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - document.documentElement.clientWidth"
            )
            or 0
        )
