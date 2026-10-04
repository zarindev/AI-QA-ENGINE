"""Multi-strategy element lookup. A recorded step keeps a LocatorSet; replay tries each strategy in order of
stability and reports which one worked, so a renamed CSS class does not break a test (self-healing)."""

from __future__ import annotations

from collections.abc import Callable

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from app.storage.schemas import LocatorSet


def _xpath_literal(text: str) -> str:
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in parts) + ")"


def strategies(loc: LocatorSet) -> list[tuple[str, Callable[[WebDriver], list[WebElement]]]]:
    tag = loc.tag or "*"
    out: list[tuple[str, Callable[[WebDriver], list[WebElement]]]] = []
    if loc.test_id:
        tid = loc.test_id
        out.append(
            (
                "test_id",
                lambda d: d.find_elements(
                    By.CSS_SELECTOR,
                    f'[data-testid="{tid}"], [data-test="{tid}"], [data-qa="{tid}"], [data-cy="{tid}"]',
                ),
            )
        )
    if loc.id:
        out.append(("id", lambda d: d.find_elements(By.ID, loc.id)))
    if loc.name:
        out.append(("name", lambda d: d.find_elements(By.CSS_SELECTOR, f'{tag}[name="{loc.name}"]')))
    if loc.aria_label:
        out.append(
            (
                "aria_label",
                lambda d: d.find_elements(By.CSS_SELECTOR, f'{tag}[aria-label="{loc.aria_label}"]'),
            )
        )
    if loc.label:
        lit = _xpath_literal(loc.label)
        out.append(
            (
                "label",
                lambda d: d.find_elements(
                    By.XPATH,
                    f"//label[normalize-space()={lit}]/following::*[self::input or self::select or self::textarea][1]"
                    f" | //*[@id=//label[normalize-space()={lit}]/@for]",
                ),
            )
        )
    if loc.placeholder:
        out.append(
            ("placeholder", lambda d: d.find_elements(By.CSS_SELECTOR, f'[placeholder="{loc.placeholder}"]'))
        )
    if loc.text:
        lit = _xpath_literal(loc.text)
        out.append(("text", lambda d: d.find_elements(By.XPATH, f"//{tag}[normalize-space()={lit}]")))
    if loc.css:
        out.append(("css", lambda d: d.find_elements(By.CSS_SELECTOR, loc.css)))
    if loc.xpath:
        out.append(("xpath", lambda d: d.find_elements(By.XPATH, loc.xpath)))
    return out


def find(driver: WebDriver, loc: LocatorSet) -> tuple[WebElement | None, str]:
    """Return (element, strategy name). Only accepts a strategy that resolves to exactly one displayed element."""
    for name, finder in strategies(loc):
        try:
            found = [e for e in finder(driver) if e.is_displayed() or e.tag_name in ("input",)]
        except WebDriverException:
            continue
        if len(found) == 1:
            return found[0], name
    return None, ""


def by_index(driver: WebDriver, index: int) -> WebElement | None:
    found = driver.find_elements(By.CSS_SELECTOR, f'[data-qap-index="{index}"]')
    return found[0] if found else None
