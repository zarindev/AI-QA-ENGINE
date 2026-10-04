"""Automatic checks (detection layer 1): run on every crawled page, no AI involved.

Each check returns raw findings; `FindingCollector` merges identical symptoms across pages/roles so one
broken script included on 30 pages is one finding with 30 occurrences, not 30 findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.storage.schemas import Finding, PageRecord, Severity

_ERROR_PAGE_PATTERNS: list[tuple[re.Pattern[str], Severity]] = [
    (re.compile(r"\bInternal Server Error\b", re.I), "critical"),
    (re.compile(r"Traceback \(most recent call last\)"), "critical"),
    (re.compile(r"\b(Fatal error|Parse error):", re.I), "critical"),
    (re.compile(r"\bSQLSTATE\[|\bsyntax error at or near\b|ORA-\d{5}", re.I), "critical"),
    (re.compile(r"\bUncaught (?:\w+)?Exception\b|\bNullReferenceException\b|\bStack trace:", re.I), "major"),
    (re.compile(r"\b(Undefined (index|variable|offset)|Notice: |Warning: [a-z_]+\()", re.I), "major"),
    (re.compile(r"\b(404|Page) Not Found\b", re.I), "major"),
    (re.compile(r"\bSomething went wrong\b", re.I), "major"),
    (re.compile(r"\{\{\s*[a-z_.]+\s*\}\}|\$\{[a-z_.]+\}", re.I), "minor"),  # unrendered template placeholders
    (re.compile(r"\bNaN\b|\[object Object\]"), "minor"),
]


_MIXED = re.compile(r"Mixed Content:.*?requested an insecure \w+ '([^']+)'", re.S)


@dataclass
class RawFinding:
    check: str
    severity: Severity
    title: str
    detail: str
    key: str  # symptom key used for de-duplication
    data: dict[str, Any] = field(default_factory=dict)


def _strip_dynamic(text: str) -> str:
    text = re.sub(r"https?://[^\s'\"]+", "<url>", text)
    text = re.sub(r"\d+", "#", text)
    return text[:200]


def _same_site(url: str, site_host: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return (
        not site_host or host == site_host or host.endswith("." + site_host) or site_host.endswith("." + host)
    )


def check_page(
    page: PageRecord,
    *,
    broken_images: list[str],
    overflow_x: int,
    slow_page_ms: int,
    site_host: str = "",
) -> list[RawFinding]:
    out: list[RawFinding] = []
    status = page.status_code
    if status in (401, 403):
        out.append(
            RawFinding(
                "auth_required",
                "trivial",
                f"Page requires authentication (HTTP {status})",
                f"{page.url} answered {status} for role '{page.role}'. Expected if this page is restricted; "
                "the permission matrix checks whether that matches the intended access rules.",
                f"auth:{status}:{page.url_template}",
                {"status": status},
            )
        )
    elif status and status >= 400:
        sev: Severity = "critical" if status >= 500 else "major"
        linked = f" Linked from {page.discovered_from}." if page.discovered_from else ""
        title = (
            f"Server error on page (HTTP {status})"
            if status >= 500
            else f"Broken link: page returns HTTP {status}"
        )
        out.append(
            RawFinding(
                "http_error",
                sev,
                title,
                f"{page.url} responded with status {status}.{linked}",
                f"http:{status}:{page.url_template}",
                {"status": status, "linked_from": page.discovered_from},
            )
        )

    for entry in page.console:
        mixed = _MIXED.search(entry.message)
        if mixed:
            resource = mixed.group(1)
            out.append(
                RawFinding(
                    "mixed_content",
                    "minor",
                    "Insecure (HTTP) resource on an HTTPS page",
                    f"The page requests {resource} over plain HTTP; browsers block or warn about it.",
                    f"mixed:{_strip_dynamic(resource)}",
                    {"resource": resource},
                )
            )
            continue
        if entry.level != "error":
            continue
        severity: Severity = (
            "major" if re.search(r"Uncaught|TypeError|ReferenceError|SyntaxError", entry.message) else "minor"
        )
        # Failed resource loads and CSP/CORS noise also appear as console errors; the network check reports them.
        if re.search(r"Failed to load resource|net::ERR_", entry.message):
            continue
        out.append(
            RawFinding(
                "js_error",
                severity,
                "JavaScript error in console",
                entry.message[:500],
                f"js:{_strip_dynamic(entry.message)}",
                {"source": entry.source},
            )
        )

    for event in page.failed_requests:
        if event.resource_type == "Document" and event.url.rstrip("/") == page.url.rstrip("/"):
            continue  # already covered by http_error
        kind = event.resource_type or "Resource"
        if not _same_site(event.url, site_host):
            # Analytics/ads/CDNs failing is worth knowing but is rarely the site's own bug.
            sev, title = (
                "trivial",
                f"Third-party {kind.lower()} request failed ({event.status or event.error or 'blocked'})",
            )
        elif urlparse(event.url).path.endswith("favicon.ico"):
            sev, title = "trivial", f"Missing favicon (HTTP {event.status or event.error})"
        elif event.status:
            sev = (
                "major"
                if event.status >= 500 or event.resource_type in ("XHR", "Fetch", "Script")
                else "minor"
            )
            title = f"{kind} request failed with HTTP {event.status}"
        else:
            sev = "minor"
            title = f"{kind} request failed ({event.error or 'blocked'})"
        out.append(
            RawFinding(
                "failed_request",
                sev,
                title,
                f"{event.method} {event.url}",
                f"net:{event.status or event.error}:{_strip_dynamic(event.url)}",
                {"url": event.url, "status": event.status, "error": event.error},
            )
        )

    for src in broken_images:
        out.append(
            RawFinding(
                "broken_image",
                "minor",
                "Broken image",
                f"Image failed to load: {src}",
                f"img:{_strip_dynamic(src)}",
                {"src": src},
            )
        )

    if page.load_time_ms and page.load_time_ms > slow_page_ms:
        out.append(
            RawFinding(
                "slow_page",
                "minor",
                f"Slow page load ({page.load_time_ms / 1000:.1f}s)",
                f"{page.url} took {page.load_time_ms} ms to load (threshold {slow_page_ms} ms).",
                f"slow:{page.url_template}",
                {"load_time_ms": page.load_time_ms},
            )
        )

    if overflow_x > 4:
        out.append(
            RawFinding(
                "horizontal_overflow",
                "minor",
                "Content overflows horizontally",
                f"The page is {overflow_x}px wider than the viewport, causing a horizontal scrollbar.",
                f"overflow:{overflow_x}",
                {"overflow_px": overflow_x},
            )
        )

    visible_text = f"{page.title}\n{page.text_excerpt}"
    # On an error status the generic "not found"/"went wrong" text is the same symptom as the status itself;
    # only leaked internals (stack traces, SQL errors) are worth a separate finding.
    patterns = (
        [(p, sev) for p, sev in _ERROR_PAGE_PATTERNS if sev == "critical"]
        if status and status >= 400
        else _ERROR_PAGE_PATTERNS
    )
    for pattern, sev in patterns:
        m = pattern.search(visible_text)
        if m:
            snippet = visible_text[max(0, m.start() - 60) : m.end() + 60].replace("\n", " ")
            out.append(
                RawFinding(
                    "error_text",
                    sev,
                    f"Error text visible on page: “{m.group(0)[:40]}”",
                    f"…{snippet}…",
                    f"text:{pattern.pattern[:30]}:{page.url_template}",
                    {"match": m.group(0)},
                )
            )
            break
    return out


@dataclass
class _Agg:
    raw: RawFinding
    pages: list[PageRecord] = field(default_factory=list)


class FindingCollector:
    def __init__(self) -> None:
        self._by_key: dict[str, _Agg] = {}

    def add(self, page: PageRecord, raws: list[RawFinding]) -> None:
        for raw in raws:
            agg = self._by_key.setdefault(raw.key, _Agg(raw))
            if all(p.url != page.url or p.role != page.role for p in agg.pages):
                agg.pages.append(page)

    def add_broken_link(self, from_page: PageRecord, url: str, status: int) -> None:
        """Only "gone" or "server error" counts: 401/403 mean restricted, 405 means POST-only (e.g. API docs)."""
        if status not in (404, 410) and status < 500:
            return
        sev: Severity = "major" if status >= 500 or status == 404 else "minor"
        raw = RawFinding(
            "broken_link",
            sev,
            f"Broken link (HTTP {status})",
            f"Link to {url} returns {status}.",
            f"link:{status}:{url}",
            {"url": url, "status": status},
        )
        self.add(from_page, [raw])

    def findings(self) -> list[Finding]:
        order = {"critical": 0, "major": 1, "minor": 2, "trivial": 3}
        aggs = sorted(
            self._by_key.values(), key=lambda a: (order[a.raw.severity], -len(a.pages), a.raw.check)
        )
        out = []
        for i, agg in enumerate(aggs, 1):
            first = agg.pages[0]
            data = dict(agg.raw.data)
            data["occurrences"] = len(agg.pages)
            data["pages"] = [{"url": p.url, "role": p.role, "page_id": p.id} for p in agg.pages[:50]]
            roles = sorted({p.role for p in agg.pages})
            out.append(
                Finding(
                    id=f"F-{i:03d}",
                    check=agg.raw.check,
                    severity=agg.raw.severity,
                    title=agg.raw.title,
                    detail=agg.raw.detail,
                    page_url=first.url,
                    page_id=first.id,
                    role=", ".join(roles),
                    evidence=[first.screenshot] if first.screenshot else [],
                    data=data,
                )
            )
        return out
