"""Logging in as a role.

Two strategies (never CAPTCHA solving or 2FA bypass):
* credentials — find the login form (heuristics first, Claude as a fallback), type the stored credentials,
  submit, then verify we actually got in.
* manual_session — open a visible browser, let the human log in (handles 2FA/SSO), export cookies and
  web storage, store them encrypted, and restore them for later runs.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.keys import Keys

from app.browser import locators
from app.browser.dom_snapshot import Snapshot, take_snapshot
from app.browser.driver import BrowserSession
from app.core.logging import get_logger
from app.core.safety import ActionContext, SafetyGuard
from app.storage.schemas import Element

log = get_logger("auth")

_LOGIN_WORDS = re.compile(
    r"\b(log\s?in|sign\s?in|signin|login|anmelden|connexion|iniciar sesi[oó]n|entrar)\b", re.I
)
_USER_HINT = re.compile(r"user|email|e-mail|login|account|phone|mobile|id", re.I)
_ERROR_SELECTORS = (
    "[role=alert], .alert-danger, .alert-error, .error, .error-message, .errors, .invalid-feedback, "
    ".notification.is-danger, [data-test=error], [data-testid*=error], .oxd-alert-content, .flash.error, #flash.error"
)


@dataclass
class LoginForm:
    username: int | None
    password: int
    submit: int | None


@dataclass
class LoginResult:
    ok: bool
    message: str
    landing_url: str = ""
    method: str = ""
    login_page_url: str = ""  # where the login form was; logged-in crawls skip it instead of re-logging in


class _AILoginLocate(BaseModel):
    """Claude's answer when the heuristics cannot find the login form."""

    username_index: int | None = None
    password_index: int | None = None
    submit_index: int | None = None
    open_login_index: int | None = None
    notes: str = ""


def _is_text_input(e: Element) -> bool:
    return e.tag == "input" and e.type in ("", "text", "email", "tel", "username") and not e.disabled


def find_login_form(snap: Snapshot) -> LoginForm | None:
    password = next(
        (e for e in snap.elements if e.tag == "input" and e.type == "password" and not e.disabled), None
    )
    if password is None:
        return None
    same_form = [
        e for e in snap.elements if password.form_index is not None and e.form_index == password.form_index
    ]
    pool = same_form or snap.elements
    before = [e for e in pool if _is_text_input(e) and e.index < password.index]
    hinted = [
        e
        for e in before
        if _USER_HINT.search(
            " ".join(
                [
                    e.name,
                    e.label,
                    e.placeholder,
                    e.attributes.get("id", ""),
                    e.attributes.get("autocomplete", ""),
                ]
            )
        )
    ]
    candidates = hinted or before
    username = candidates[-1] if candidates else None
    submit = None
    buttons = [
        e
        for e in pool
        if e.index > password.index
        and (
            (e.tag == "button" and e.type in ("", "submit"))
            or (e.tag == "input" and e.type in ("submit", "button", "image"))
            or e.role == "button"
        )
    ]
    worded = [
        b
        for b in buttons
        if _LOGIN_WORDS.search(b.text or b.value or b.label)
        or re.search(r"submit|continue", b.text or b.value, re.I)
    ]
    if worded:
        submit = worded[0].index
    elif buttons:
        submit = buttons[0].index
    return LoginForm(username.index if username else None, password.index, submit)


def _open_login_candidates(snap: Snapshot) -> list[Element]:
    return [
        e
        for e in snap.elements
        if e.tag in ("a", "button") or e.role in ("link", "button")
        if _LOGIN_WORDS.search(" ".join([e.text, e.label, e.href]))
    ]


def _visible_errors(session: BrowserSession) -> str:
    try:
        texts = session.driver.execute_script(
            "return Array.from(document.querySelectorAll(arguments[0])).filter(e => e.offsetParent !== null)"
            ".map(e => e.innerText.trim()).filter(Boolean).slice(0, 6);",
            _ERROR_SELECTORS,
        )
    except WebDriverException:
        return ""
    # nested error containers repeat the same message; keep each distinct text once
    unique: list[str] = []
    for text in texts:
        if not any(text in u or u in text for u in unique):
            unique.append(text)
    return " | ".join(unique)[:300]


def _type(session: BrowserSession, index: int, text: str) -> None:
    el = locators.by_index(session.driver, index)
    if el is None:
        raise RuntimeError(f"Login field [{index}] disappeared")
    el.click()
    el.clear()
    # React/Vue controlled inputs can keep the old value after clear(); reset through the native setter.
    if el.get_attribute("value"):
        session.driver.execute_script(CLEAR_INPUT_JS, el)
    el.send_keys(text)


CLEAR_INPUT_JS = (
    "const el = arguments[0];"
    "const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
    "Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, '');"
    "el.dispatchEvent(new Event('input', {bubbles: true}));"
)


def _ai_locate(ai: Any, snap: Snapshot) -> _AILoginLocate | None:
    if ai is None or not ai.available():
        return None
    system = (
        "You help a QA tool log into a web application with credentials the site owner provided. "
        "Given the indexed interactive elements of the current page, identify the username/email field, "
        "the password field and the submit button. If the page has no login form but has an element that "
        "opens the login page or dialog, return it as open_login_index. Use null for anything not present. "
        "Never suggest bypassing CAPTCHA or two-factor authentication."
    )
    try:
        return ai.structured(
            system=system,
            content=snap.outline(),
            schema=_AILoginLocate,
            purpose="locate login form",
            effort="low",
            max_tokens=4000,
        )
    except Exception as exc:  # AI is a fallback here; a failure just means heuristics were our only chance
        log.warning("AI login-form lookup failed: %s", exc)
        return None


def login_with_credentials(
    session: BrowserSession,
    start_url: str,
    username: str,
    password: str,
    guard: SafetyGuard,
    ai: Any = None,
    login_url: str = "",
    timeout_s: float = 10.0,
) -> LoginResult:
    session.navigate(login_url or start_url)
    # Login forms in SPAs often render well after the load event.
    session.wait_for("document.querySelector('input[type=password]')", timeout_s=15)
    session.wait_ready(timeout_s=5)
    snap = take_snapshot(session.driver)
    form = find_login_form(snap)
    method = "heuristic"

    if form is None:
        for cand in _open_login_candidates(snap)[:2]:
            decision = guard.check(
                ActionContext(
                    kind="click", text=cand.text or cand.label, attributes=cand.attributes, href=cand.href
                )
            )
            if not decision.allowed:
                continue
            el = locators.by_index(session.driver, cand.index)
            if el is None:
                continue
            try:
                el.click()
            except WebDriverException:
                continue
            session.wait_for("document.querySelector('input[type=password]')", timeout_s=8)
            session.wait_ready()
            snap = take_snapshot(session.driver)
            form = find_login_form(snap)
            if form:
                break

    if form is None:
        located = _ai_locate(ai, snap)
        if located and located.open_login_index is not None and located.password_index is None:
            el = locators.by_index(session.driver, located.open_login_index)
            if el is not None:
                el.click()
                session.wait_ready()
                snap = take_snapshot(session.driver)
                form = find_login_form(snap)
                located = None if form else _ai_locate(ai, snap)
        if form is None and located and located.password_index is not None:
            form = LoginForm(located.username_index, located.password_index, located.submit_index)
            method = "ai"

    if form is None:
        return LoginResult(
            False, "No login form found on the start page or a linked login page.", session.current_url
        )

    before_url = session.current_url
    login_page = before_url
    try:
        if form.username is not None:
            _type(session, form.username, username)
        _type(session, form.password, password)
        submit_el = locators.by_index(session.driver, form.submit) if form.submit is not None else None
        decision = guard.check(ActionContext(kind="submit", text="log in", form_is_safe=True))
        if not decision.allowed:
            return LoginResult(False, f"Login submit blocked: {decision.reason}", session.current_url)
        if submit_el is not None:
            submit_el.click()
        else:
            pw = locators.by_index(session.driver, form.password)
            if pw is not None:
                pw.send_keys(Keys.ENTER)
    except WebDriverException as exc:
        return LoginResult(False, f"Could not fill the login form: {exc.msg}", session.current_url, method)

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(0.4)
        try:
            still_pw = session.driver.execute_script(
                "const p = document.querySelector('input[type=password]'); return !!(p && p.offsetParent !== null);"
            )
        except WebDriverException:
            still_pw = True
        if not still_pw:
            break
        if _visible_errors(session):
            break
    session.wait_ready()
    error = _visible_errors(session)
    try:
        still_pw = session.driver.execute_script(
            "const p = document.querySelector('input[type=password]'); return !!(p && p.offsetParent !== null);"
        )
    except WebDriverException:
        still_pw = False
    if still_pw:
        msg = f"Login did not succeed: {error}" if error else "Login form is still shown after submitting."
        return LoginResult(False, msg, session.current_url, method, login_page)
    landed = session.current_url
    note = "" if landed != before_url else " (same URL; form disappeared)"
    return LoginResult(True, f"Logged in via {method} form detection{note}", landed, method, login_page)


def looks_logged_out(session: BrowserSession, snap: Snapshot | None = None) -> bool:
    """True when the current page is a login page, i.e. the session was lost or a page requires auth."""
    snap = snap or take_snapshot(session.driver)
    return find_login_form(snap) is not None


def capture_manual_session(
    url: str,
    wait_for_user: Callable[[BrowserSession], None],
    width: int = 1440,
    height: int = 900,
) -> dict[str, Any]:
    """Open a visible Chrome, let the user log in by hand (2FA/SSO welcome), then export the session."""
    with BrowserSession(headless=False, width=width, height=height) as session:
        session.navigate(url)
        wait_for_user(session)
        return session.export_session()


def restore_session(session: BrowserSession, saved: dict[str, Any], start_url: str) -> LoginResult:
    session.import_session(saved)
    session.navigate(saved.get("url") or start_url)
    if looks_logged_out(session):
        return LoginResult(
            False, "Saved session has expired — capture a new manual login.", session.current_url, "session"
        )
    return LoginResult(True, "Restored saved session", session.current_url, "session")
