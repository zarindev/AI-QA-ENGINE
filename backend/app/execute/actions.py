"""Browser actions the test agent (and the replayer) can perform, each checked by the Safe Mode guard first.

Elements are addressed by the index the DOM snapshot assigned (`[12] button "Save"`). Every action returns an
`Outcome` describing what happened, so the agent's next turn can reason about it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select

from app.browser import locators
from app.browser.dom_snapshot import Snapshot, take_snapshot
from app.browser.driver import BrowserSession
from app.core.safety import ActionContext, SafetyGuard
from app.explore.urls import Scope
from app.storage.schemas import Element, LocatorSet

RECT_JS = (
    "const r = arguments[0].getBoundingClientRect();"
    "return {x: r.left, y: r.top, width: r.width, height: r.height};"
)
VISIBLE_MESSAGES_JS = """
const sel = '[role=alert], [role=status], .alert, .flash, .error, .errors, .invalid-feedback, .toast, .notification, .message, .success';
const out = Array.from(document.querySelectorAll(sel)).filter(e => e.offsetParent !== null)
  .map(e => e.innerText.trim()).filter(Boolean);
const invalid = Array.from(document.querySelectorAll('input, select, textarea')).filter(e => e.willValidate && !e.validity.valid)
  .map(e => (e.labels && e.labels[0] ? e.labels[0].innerText.trim() : (e.name || e.id)) + ': ' + e.validationMessage);
return {messages: [...new Set(out)].slice(0, 6), invalid: invalid.slice(0, 6)};
"""


@dataclass
class Outcome:
    ok: bool
    observation: str
    element: Element | None = None
    rect: dict[str, float] | None = None
    blocked_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class Actions:
    def __init__(
        self, session: BrowserSession, guard: SafetyGuard, scope: Scope, upload_file: Path | None = None
    ) -> None:
        self.session = session
        self.guard = guard
        self.scope = scope
        self.upload_file = upload_file
        self.snapshot: Snapshot | None = None

    # ------------------------------------------------------------------ observation

    def observe(self) -> Snapshot:
        self.snapshot = take_snapshot(self.session.driver)
        return self.snapshot

    def page_messages(self) -> dict[str, list[str]]:
        try:
            return self.session.driver.execute_script(VISIBLE_MESSAGES_JS)
        except WebDriverException:
            return {"messages": [], "invalid": []}

    def _element(self, index: int) -> tuple[Element | None, WebElement | None]:
        meta = self.snapshot.element(index) if self.snapshot else None
        web = locators.by_index(self.session.driver, index)
        return meta, web

    def _rect(self, web: WebElement) -> dict[str, float] | None:
        try:
            self.session.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", web
            )
            return self.session.driver.execute_script(RECT_JS, web)
        except WebDriverException:
            return None

    def _context(self, meta: Element, kind: str) -> ActionContext:
        """Safety context. A submit button is judged by its form (heading, action, other buttons), not its label."""
        form_text, form_safe = "", None
        if meta.form_index is not None and self.snapshot:
            form = next((f for f in self.snapshot.forms if f.index == meta.form_index), None)
            if form:
                form_text = f"{form.heading} {form.action}"
                form_safe = form.purpose in ("search", "filter", "login")
        is_submit = (
            meta.tag == "button" and meta.type in ("", "submit") and meta.form_index is not None
        ) or (meta.tag == "input" and meta.type in ("submit", "image"))
        return ActionContext(
            kind="submit" if (kind == "click" and is_submit) else kind,  # type: ignore[arg-type]
            text=meta.text or meta.label or meta.value,
            attributes=meta.attributes,
            href=meta.href,
            context=form_text,
            form_is_safe=form_safe,
        )

    def _after(self, settle_ms: int = 500) -> str:
        self.session.wait_ready(timeout_s=8, settle_ms=settle_ms)
        msgs = self.page_messages()
        bits = [f"Now on {self.session.current_url}"]
        if msgs["messages"]:
            bits.append("Messages: " + " | ".join(m[:160] for m in msgs["messages"]))
        if msgs["invalid"]:
            bits.append("Browser validation: " + " | ".join(msgs["invalid"]))
        return ". ".join(bits)

    # ------------------------------------------------------------------ actions

    def run(self, tool: str, args: dict[str, Any]) -> Outcome:
        handler = getattr(self, f"do_{tool}", None)
        if handler is None:
            return Outcome(False, f"Unknown action '{tool}'.")
        try:
            return handler(**args)
        except StaleElementReferenceException:
            return Outcome(False, "The page changed before the action; look at the new page and try again.")
        except WebDriverException as exc:
            return Outcome(False, f"Browser error: {(exc.msg or type(exc).__name__).splitlines()[0][:200]}")
        except TypeError as exc:
            return Outcome(False, f"Invalid arguments for {tool}: {exc}")

    def do_click(self, index: int, **_: Any) -> Outcome:
        meta, web = self._element(index)
        if meta is None or web is None:
            return Outcome(False, f"No element [{index}] on this page.")
        decision = self.guard.check(self._context(meta, "click"))
        if not decision.allowed:
            return Outcome(
                False, f"Blocked by Safe Mode: {decision.reason}", meta, blocked_reason=decision.reason
            )
        rect = self._rect(web)
        try:
            web.click()
        except (ElementClickInterceptedException, ElementNotInteractableException):
            self.session.driver.execute_script("arguments[0].click();", web)
        return Outcome(True, f"Clicked {meta.describe()}. " + self._after(), meta, rect)

    def do_type(self, index: int, text: str, clear: bool = True, **_: Any) -> Outcome:
        meta, web = self._element(index)
        if meta is None or web is None:
            return Outcome(False, f"No element [{index}] on this page.")
        decision = self.guard.check(self._context(meta, "type"))
        if not decision.allowed:
            return Outcome(
                False, f"Blocked by Safe Mode: {decision.reason}", meta, blocked_reason=decision.reason
            )
        rect = self._rect(web)
        input_type = (web.get_attribute("type") or "").lower()
        if input_type in ("date", "time", "datetime-local", "month", "week", "color", "range"):
            # Typing into date pickers is locale-dependent; set the value the way the app would receive it.
            self.session.driver.execute_script(
                "const el = arguments[0]; const proto = Object.getPrototypeOf(el);"
                "Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, arguments[1]);"
                "el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));",
                web,
                text,
            )
        else:
            if clear:
                web.clear()
                if web.get_attribute("value"):
                    self.session.driver.execute_script(
                        "const el = arguments[0]; const proto = Object.getPrototypeOf(el);"
                        "Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, '');"
                        "el.dispatchEvent(new Event('input', {bubbles: true}));",
                        web,
                    )
            web.send_keys(text)
        value = web.get_attribute("value") or ""
        note = "" if value == text else f" (the field now contains “{value[:80]}”)"
        return Outcome(True, f"Typed “{text[:80]}” into {meta.describe()}{note}.", meta, rect)

    def do_select(self, index: int, option: str, **_: Any) -> Outcome:
        meta, web = self._element(index)
        if meta is None or web is None or meta.tag != "select":
            return Outcome(False, f"[{index}] is not a dropdown.")
        rect = self._rect(web)
        sel = Select(web)
        texts = [o.text.strip() for o in sel.options]
        match = next((t for t in texts if t.lower() == option.lower()), None) or next(
            (t for t in texts if option.lower() in t.lower()), None
        )
        if match is None:
            return Outcome(
                False, f"Option “{option}” not found. Options: {', '.join(texts[:20])}", meta, rect
            )
        sel.select_by_visible_text(match)
        return Outcome(True, f"Selected “{match}” in {meta.describe()}. " + self._after(200), meta, rect)

    def do_check(self, index: int, checked: bool = True, **_: Any) -> Outcome:
        meta, web = self._element(index)
        if meta is None or web is None:
            return Outcome(False, f"No element [{index}] on this page.")
        rect = self._rect(web)
        if web.is_selected() != checked:
            self.session.driver.execute_script("arguments[0].click();", web)
        return Outcome(True, f"{'Checked' if checked else 'Unchecked'} {meta.describe()}.", meta, rect)

    def do_upload(self, index: int, **_: Any) -> Outcome:
        meta, web = self._element(index)
        if meta is None or web is None:
            return Outcome(False, f"No element [{index}] on this page.")
        decision = self.guard.check(
            ActionContext(kind="upload", text=meta.label or meta.name, attributes=meta.attributes)
        )
        if not decision.allowed or self.upload_file is None:
            return Outcome(
                False,
                f"Blocked: {decision.reason or 'no upload fixture'}",
                meta,
                blocked_reason=decision.reason,
            )
        web.send_keys(str(self.upload_file.resolve()))
        return Outcome(
            True, f"Uploaded the QA Pilot test file into {meta.describe()}.", meta, self._rect(web)
        )

    def do_navigate(self, url: str, **_: Any) -> Outcome:
        target = urljoin(self.session.current_url, url)
        if not self.scope.allows(target):
            return Outcome(False, f"{target} is outside the site under test.")
        decision = self.guard.check(ActionContext(kind="navigate", href=target))
        if not decision.allowed:
            return Outcome(False, f"Blocked by Safe Mode: {decision.reason}", blocked_reason=decision.reason)
        nav = self.session.navigate(target)
        status = f" (HTTP {nav.status_code})" if nav.status_code else ""
        return Outcome(True, f"Opened {target}{status}. " + self._after(), data={"status": nav.status_code})

    def do_scroll(self, direction: str = "down", **_: Any) -> Outcome:
        dy = -700 if direction == "up" else 700
        self.session.driver.execute_script("window.scrollBy(0, arguments[0]);", dy)
        time.sleep(0.3)
        return Outcome(True, f"Scrolled {direction}.")

    def do_wait_for(self, text: str, seconds: float = 5, **_: Any) -> Outcome:
        found = self.session.wait_for(
            f"document.body && document.body.innerText.includes({text!r})", timeout_s=min(15, seconds)
        )
        return Outcome(found, f"“{text}” {'appeared' if found else 'did not appear'} within {seconds:g}s.")

    def do_read(self, index: int, **_: Any) -> Outcome:
        meta, web = self._element(index)
        if meta is None or web is None:
            return Outcome(False, f"No element [{index}] on this page.")
        value = web.get_attribute("value") if meta.tag in ("input", "select", "textarea") else web.text
        return Outcome(
            True, f"{meta.describe()} contains: “{(value or '').strip()[:300]}”", meta, self._rect(web)
        )


def locator_set(element: Element | None) -> LocatorSet | None:
    return element.locators if element else None
