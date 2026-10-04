"""Condense a crawl into what the classifier needs: one entry per screen (URL template), with the roles that
could see it, its headings, forms, tables and the actions it offers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.storage.schemas import CrawlResult, Element, PageRecord

_SKIP_LABELS = {"", "×", "x", "close", "menu", "open menu", "close menu"}


@dataclass
class ScreenSummary:
    template: str
    title: str
    roles: list[str]
    sample_url: str
    page_ids: list[str]
    headings: list[str] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    is_login: bool = False


def _label(e: Element) -> str:
    return (e.label or e.text or e.placeholder or e.name or "").strip()


def _form_line(page: PageRecord, form_index: int) -> str:
    form = next(f for f in page.forms if f.index == form_index)
    fields = []
    for idx in form.field_indices:
        e = next((x for x in page.elements if x.index == idx), None)
        if (
            e is None
            or e.tag not in ("input", "select", "textarea")
            or e.type in ("hidden", "submit", "button")
        ):
            continue
        bits = [e.type or e.tag]
        if e.required:
            bits.append("required")
        for name, value in (("min", e.min), ("max", e.max), ("pattern", e.pattern)):
            if value:
                bits.append(f"{name}={value}")
        if e.maxlength:
            bits.append(f"maxlength={e.maxlength}")
        if e.options:
            bits.append("options=" + "|".join(e.options[:6]))
        fields.append(f"{_label(e) or e.name}({', '.join(bits)})")
    submit = next((x for x in page.elements if x.index == form.submit_index), None)
    submit_label = _label(submit) if submit else ""
    return f"[{form.purpose}] {form.heading or ''} fields: {'; '.join(fields)} submit: {submit_label}".strip()


def summarize(crawl: CrawlResult, max_screens: int = 60) -> list[ScreenSummary]:
    by_template: dict[str, list[PageRecord]] = {}
    for page in crawl.pages:
        by_template.setdefault(page.url_template, []).append(page)
    screens = []
    for template, pages in by_template.items():
        first = pages[0]
        forms = []
        for f in first.forms:
            if len(f.field_indices) > 1:
                forms.append(_form_line(first, f.index))
        # One-click actions ("Complete visit", "Mark paid") are buttons alone in their own little form.
        single_button_forms = {f.index for f in first.forms if len(f.field_indices) <= 1}
        actions = []
        for e in first.elements:
            if (e.tag == "button" or e.role == "button") and (
                e.form_index is None or e.form_index in single_button_forms
            ):
                lab = _label(e)
                if lab.lower() not in _SKIP_LABELS:
                    actions.append(lab)
        screens.append(
            ScreenSummary(
                template=template,
                title=first.title,
                roles=sorted({p.role for p in pages}),
                sample_url=first.url,
                page_ids=[p.id for p in pages],
                headings=first.headings[:6],
                forms=forms[:4],
                tables=[
                    f"{t.row_count} rows: {', '.join(t.headers[:12])}" for t in first.tables[:3] if t.headers
                ],
                actions=sorted(set(actions))[:12],
                is_login=first.is_login_page,
            )
        )
    # The most-visited screens first (seen by more roles), then by template for stability.
    screens.sort(key=lambda s: (-len(s.roles), s.template))
    return screens[:max_screens]


def navigation_labels(crawl: CrawlResult) -> dict[str, list[str]]:
    """Per role, link labels that appear on at least half of the role's pages — that is the app's menu."""
    from urllib.parse import urljoin, urlparse

    site_host = (urlparse(crawl.start_url).hostname or "").lower()

    broken = {p.url for p in crawl.pages if p.status_code and p.status_code >= 400}
    page_by_url = {p.url: p for p in crawl.pages}
    out: dict[str, list[str]] = {}
    for role in sorted({p.role for p in crawl.pages}):
        pages = [p for p in crawl.pages if p.role == role]
        counts: Counter[str] = Counter()
        target: dict[str, str] = {}
        for page in pages:
            for e in page.elements:
                if e.tag == "a" and e.href and _label(e):
                    target.setdefault(_label(e), urljoin(page.url, e.href))
            counts.update({_label(e) for e in page.elements if e.tag == "a" and e.href and _label(e)})
        threshold = max(2, len(pages) // 2)
        frequent = [
            label
            for label, n in counts.most_common()
            if n >= threshold
            and len(label) < 40
            and (urlparse(target.get(label, "")).hostname or site_host).lower()
            == site_host  # no social/external links
        ]

        # Two labels for one URL (logo "CarePoint Clinic" and "Dashboard" both -> /): keep the one that names the
        # page it opens (matches its title or heading), then the shorter, menu-like one.
        def fit(label: str, url: str) -> tuple[bool, int]:
            page = page_by_url.get(url)
            names = f"{page.title} {' '.join(page.headings)}".lower() if page else ""
            return (label.lower() in names, -len(label))

        by_url: dict[str, str] = {}
        for label in frequent:
            url = target.get(label, "")
            if url in broken:
                continue
            if url not in by_url or fit(label, url) > fit(by_url[url], url):
                by_url[url] = label
        keep = set(by_url.values())
        out[role] = [label for label in frequent if label in keep][:20]
    return out


def render(crawl: CrawlResult, screens: list[ScreenSummary]) -> str:
    lines = [f"Start URL: {crawl.start_url}", f"Roles crawled: {', '.join(r.role for r in crawl.roles)}"]
    for role, labels in navigation_labels(crawl).items():
        if labels:
            lines.append(f"Menu for {role}: {' | '.join(labels)}")
    lines.append(f"\nScreens ({len(screens)} distinct URL templates):")
    for s in screens:
        lines.append(
            f"\n## {s.template}  — “{s.title}”  roles: {', '.join(s.roles)}{'  [login page]' if s.is_login else ''}"
        )
        if s.headings:
            lines.append("headings: " + " | ".join(s.headings))
        for t in s.tables:
            lines.append("table " + t)
        for f in s.forms:
            lines.append("form " + f)
        if s.actions:
            lines.append("buttons: " + ", ".join(s.actions))
    return "\n".join(lines)
