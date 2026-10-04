"""Safe Mode guard. Every browser action the engine takes on the target site passes through `SafetyGuard.check`.

Rules
-----
* `always_blocked` phrases are refused in every mode.
* Safe Mode refuses anything matching the deny-list (delete, pay, checkout, transfer ...), and only
  submits forms that look like search/filter forms.
* Full Mode (environments marked staging/test only) allows deny-listed actions but never `always_blocked`.
* While exploring we never click "log out" style elements (`preserve_session=True`), in any mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlparse

ActionKind = Literal["navigate", "click", "type", "select", "submit", "check", "upload"]
Mode = Literal["safe", "full"]


@dataclass
class ActionContext:
    kind: ActionKind
    text: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    href: str = ""
    context: str = ""  # surrounding text, e.g. the form's submit button label or a modal title
    form_is_safe: bool | None = None  # set by the caller for submits when known


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    matched: str = ""


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    # Word-boundary match that also treats _ - . / as separators, so "btn-delete" and "/user/delete/4" match
    # "delete" but "deleted_at" style substrings inside longer words do not.
    words = [re.escape(w) for w in phrase.lower().split()]
    body = r"[\s_\-./]+".join(words)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z])")


def _url_segments(url: str) -> list[str]:
    """Path segments plus query keys/values, lowercased, with -_. turned into spaces and extensions dropped."""
    p = urlparse(url)
    parts = [unquote(seg) for seg in p.path.split("/") if seg]
    for key, value in parse_qsl(p.query, keep_blank_values=True):
        parts.extend([key, value])
    out = []
    for part in parts:
        part = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part)  # purgeEmployee -> purge Employee
        part = re.sub(r"\.(html?|php|aspx?|jsp)$", "", part.lower())
        out.append(re.sub(r"[-_.+]+", " ", part).strip())
    return [x for x in out if x]


class SafetyGuard:
    def __init__(self, mode: Mode, safety_settings: dict, preserve_session: bool = False) -> None:
        self.mode: Mode = mode
        self.preserve_session = preserve_session
        self._deny = [(p, _phrase_pattern(p)) for p in safety_settings.get("deny_list", [])]
        self._always = [(p, _phrase_pattern(p)) for p in safety_settings.get("always_blocked", [])]
        self._session = [(p, _phrase_pattern(p)) for p in safety_settings.get("session_enders", [])]
        self._safe_forms = [(p, _phrase_pattern(p)) for p in safety_settings.get("safe_form_hints", [])]

    @staticmethod
    def _haystack(ctx: ActionContext) -> str:
        # javascript:void(0) / "#" hrefs say nothing about the action; matching them would flag "void".
        href = "" if ctx.href.strip().lower().startswith(("javascript:", "#")) else ctx.href
        parts = [ctx.text, href, ctx.context]
        for key in (
            "id",
            "name",
            "aria-label",
            "title",
            "value",
            "class",
            "data-testid",
            "data-test",
            "formaction",
        ):
            if ctx.attributes.get(key):
                parts.append(ctx.attributes[key])
        return " | ".join(p for p in parts if p).lower()

    @staticmethod
    def _first_match(patterns: list[tuple[str, re.Pattern[str]]], haystack: str) -> str:
        for phrase, pattern in patterns:
            if pattern.search(haystack):
                return phrase
        return ""

    def is_safe_form(self, form_text: str) -> bool:
        return bool(self._first_match(self._safe_forms, form_text.lower()))

    def _check_url(self, url: str) -> Decision:
        """GET navigation is only risky when a path segment *starts with* an action word: /users/5/delete,
        /logout, /checkout-step-one. A page named /add_remove_elements or /payments is just a page."""
        segments = _url_segments(url)

        def hit(patterns: list[tuple[str, re.Pattern[str]]]) -> str:
            for phrase, _ in patterns:
                rx = re.compile(r"^" + r"\s+".join(map(re.escape, phrase.lower().split())) + r"\b")
                if any(rx.search(seg) for seg in segments):
                    return phrase
            return ""

        found = hit(self._always)
        if found:
            return Decision(False, f"'{found}' is blocked in every mode", found)
        if self.preserve_session:
            found = hit(self._session)
            if found:
                return Decision(False, f"'{found}' would end the logged-in session during exploration", found)
        if self.mode == "safe":
            found = hit(self._deny)
            if found:
                return Decision(False, f"Safe Mode: '{found}' looks destructive or transactional", found)
        return Decision(True, "allowed")

    def check(self, ctx: ActionContext) -> Decision:
        if ctx.kind == "navigate":
            return self._check_url(ctx.href)
        haystack = self._haystack(ctx)
        hit = self._first_match(self._always, haystack)
        if hit:
            return Decision(False, f"'{hit}' is blocked in every mode", hit)
        if self.preserve_session:
            hit = self._first_match(self._session, haystack)
            if hit:
                return Decision(False, f"'{hit}' would end the logged-in session during exploration", hit)
        if ctx.kind in ("type", "check", "select") and self.mode == "safe":
            # Typing into a field is harmless by itself; what matters is what gets submitted.
            return Decision(True, "input only")
        if self.mode == "safe":
            hit = self._first_match(self._deny, haystack)
            if hit:
                return Decision(False, f"Safe Mode: '{hit}' looks destructive or transactional", hit)
            if ctx.kind == "submit" and not (ctx.form_is_safe or self.is_safe_form(haystack)):
                return Decision(False, "Safe Mode: only search/filter forms are submitted")
            if ctx.kind == "upload":
                return Decision(False, "Safe Mode: file uploads are disabled")
        return Decision(True, "allowed")
