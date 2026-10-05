"""Stage ① Explore: breadth-first crawl, public pages first, then once per role.

For every page we record URL, template, title, status, screenshot, simplified DOM (indexed elements,
forms, tables), console errors, failed requests and load time, and run the automatic checks.
SPA navigation is discovered by clicking link-like elements that have no real href ("click discovery").
Every navigation and click goes through the Safe Mode guard first.
"""

from __future__ import annotations

import io
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import Image
from selenium.common.exceptions import WebDriverException

from app.browser import auth, locators
from app.browser.dom_snapshot import Snapshot, take_snapshot
from app.browser.driver import BrowserSession
from app.core.logging import get_logger, redact
from app.core.paths import slugify
from app.core.safety import ActionContext, SafetyGuard
from app.execute import privacy
from app.explore import urls
from app.explore.checks import FindingCollector, RawFinding, check_page
from app.storage.repository import Repository
from app.storage.schemas import (
    CrawlResult,
    Element,
    FindingsDoc,
    PageRecord,
    Project,
    Role,
    RoleCrawlSummary,
    Run,
    utcnow,
)

log = get_logger("crawl")

_LINK_ROLES = ("link", "menuitem", "tab")

LINK_CHECK_JS = """
const [urls, timeoutMs, done] = [arguments[0], arguments[1], arguments[arguments.length - 1]];
const out = {};
const get = (u, method) => {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  return fetch(u, {method, credentials: 'include', redirect: 'follow', signal: ctl.signal}).finally(() => clearTimeout(t));
};
const one = async u => {
  try {
    let r = await get(u, 'HEAD');
    if (r.status === 405 || r.status === 501) r = await get(u, 'GET');
    out[u] = r.status;
  } catch (e) { out[u] = 0; }
};
Promise.all(urls.map(one)).then(() => done(out));
"""


@dataclass
class CrawlOptions:
    max_pages: int = 40
    max_depth: int = 4
    rate_limit_s: float = 0.5
    click_discovery: bool = True
    max_clicks_per_page: int = 12
    slow_page_ms: int = 3000
    instances_per_template: int = 2
    ignore_params: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    headless: bool = True
    width: int = 1440
    height: int = 900
    page_load_timeout_s: int = 30
    max_link_checks: int = 80

    @classmethod
    def from_settings(cls, settings: dict[str, Any], project: Project, **overrides: Any) -> CrawlOptions:
        c, b = settings["crawl"], settings["browser"]
        opts = cls(
            max_pages=project.scope.max_pages or c["max_pages"],
            max_depth=project.scope.max_depth or c["max_depth"],
            rate_limit_s=c["rate_limit_s"],
            click_discovery=c["click_discovery"],
            max_clicks_per_page=c["max_clicks_per_page"],
            slow_page_ms=c["slow_page_ms"],
            ignore_params=c.get("ignore_query_params", []),
            exclude_patterns=list(c.get("exclude_patterns", [])) + project.scope.exclude_patterns,
            include_patterns=project.scope.include_patterns,
            headless=b["headless"],
            width=b["window_width"],
            height=b["window_height"],
            page_load_timeout_s=b["page_load_timeout_s"],
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(opts, key, value)
        return opts


@dataclass
class _QueueItem:
    url: str
    depth: int
    source: str
    via: str


ProgressFn = Callable[[float, str, dict[str, Any]], None]


class Crawler:
    def __init__(
        self,
        repo: Repository,
        run: Run,
        project: Project,
        options: CrawlOptions,
        guard: SafetyGuard,
        secrets: dict[str, Any],
        ai: Any = None,
        progress: ProgressFn | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.repo = repo
        self.run = run
        self.project = project
        self.opts = options
        self.guard = guard
        self.secrets = secrets
        self.ai = ai
        self.progress = progress or (lambda f, m, d: None)
        self.cancelled = cancelled or (lambda: False)
        self.scope = urls.Scope(project.url, options.include_patterns, options.exclude_patterns)
        self.result = CrawlResult(start_url=project.url)
        self.collector = FindingCollector()
        self._page_seq = 0
        self._roles: list[Role] = [Role(name="public", login_strategy="none"), *project.roles]
        self.browser_version = ""
        self._session: BrowserSession | None = None
        self._login_pages: set[str] = set()
        self._unvisited_links: dict[str, PageRecord] = {}

    @property
    def session(self) -> BrowserSession:
        if self._session is None:
            raise RuntimeError("No browser session is open")
        return self._session

    @session.setter
    def session(self, value: BrowserSession) -> None:
        self._session = value

    # ------------------------------------------------------------------ public API

    def crawl(self) -> tuple[CrawlResult, FindingsDoc]:
        for i, role in enumerate(self._roles):
            if self.cancelled():
                break
            summary = RoleCrawlSummary(role=role.name)
            self.result.roles.append(summary)
            self._crawl_role(role, summary, i)
        self.result.finished_at = utcnow()
        findings = FindingsDoc(findings=self.collector.findings())
        return self.result, findings

    # ------------------------------------------------------------------ per role

    def _norm(self, url: str) -> str:
        return urls.normalize(url, self.opts.ignore_params)

    def _report(self, role_i: int, done: int, message: str, **data: Any) -> None:
        n = len(self._roles)
        frac = (role_i + min(1.0, done / max(1, self.opts.max_pages))) / n
        self.progress(frac, message, data)

    def _login(self, session: BrowserSession, role: Role, summary: RoleCrawlSummary) -> str | None:
        """Log in as `role`; return the landing URL or None when login failed."""
        if role.login_strategy == "manual_session":
            saved = self.secrets.get(f"session:{role.name}")
            if not saved:
                summary.login_ok, summary.login_message = False, "No saved manual session for this role."
                return None
            result = auth.restore_session(session, saved, self.project.url)
        else:
            creds = self.secrets.get(role.secret_ref or f"role:{role.name}") or {}
            if not creds.get("username") or not creds.get("password"):
                summary.login_ok, summary.login_message = False, "No credentials stored for this role."
                return None
            result = auth.login_with_credentials(
                session,
                self.project.url,
                creds["username"],
                creds["password"],
                self.guard,
                ai=self.ai,
                login_url=role.login_url,
            )
        summary.login_ok, summary.login_message = result.ok, result.message
        if result.login_page_url:
            self._login_pages.add(self._norm(result.login_page_url))
        log.info("[%s] login: %s", role.name, result.message)
        return result.landing_url if result.ok else None

    def _new_session(self) -> BrowserSession:
        o = self.opts
        session = BrowserSession(
            headless=o.headless, width=o.width, height=o.height, page_load_timeout_s=o.page_load_timeout_s
        )
        self.browser_version = session.browser_version
        return session

    def _recover(self, role: Role) -> bool:
        """After a browser-level failure: keep the session if it still answers, otherwise restart and re-login."""
        try:
            self.session.driver.execute_script("window.stop();")
            _ = self.session.driver.title
            return True
        except WebDriverException:
            pass
        log.warning("[%s] browser stopped responding; restarting it", role.name)
        self.session.close()
        self.session = self._new_session()
        if role.name == "public":
            return True
        return self._login(self.session, role, RoleCrawlSummary(role=role.name)) is not None

    def _crawl_role(self, role: Role, summary: RoleCrawlSummary, role_i: int) -> None:
        try:
            self.session = self._new_session()
        except RuntimeError as exc:
            summary.login_ok, summary.login_message = False, str(exc)
            raise
        try:
            seeds = [self._norm(self.project.url)]
            if role.name != "public":
                self._report(role_i, 0, f"Logging in as {role.name}")
                landing = self._login(self.session, role, summary)
                if landing is None:
                    return
                seeds.insert(0, self._norm(landing))
            self._bfs(role, summary, seeds, role_i)
            self._check_links(self.session, role)
        finally:
            self.session.close()

    def _bfs(self, role: Role, summary: RoleCrawlSummary, seeds: list[str], role_i: int) -> None:
        o = self.opts
        queue: deque[_QueueItem] = deque(
            _QueueItem(s, 0, "", "seed" if i else ("login" if role.name != "public" else "seed"))
            for i, s in enumerate(dict.fromkeys(seeds))
        )
        self._queued: set[str] = {q.url for q in queue}
        self._visited: set[str] = set()
        self._template_counts: dict[str, int] = {}
        self._unvisited_links = {}
        self._relogins = 0
        retried: set[str] = set()
        pages_for_role: list[PageRecord] = []

        while queue and len(pages_for_role) < o.max_pages and not self.cancelled():
            item = queue.popleft()
            try:
                page, snap = self._visit(role, item, summary)
            except WebDriverException as exc:
                reason = (exc.msg or type(exc).__name__).splitlines()[0][:200]
                if not self._recover(role):
                    log.warning(
                        "[%s] could not log in again after a browser restart; stopping this role", role.name
                    )
                    break
                self._visited.discard(item.url)
                if item.url not in retried:
                    retried.add(item.url)
                    log.info("[%s] retrying %s after: %s", role.name, item.url, reason)
                    queue.appendleft(item)
                else:
                    log.warning("[%s] could not capture %s: %s", role.name, item.url, reason)
                    self.result.errors.append({"role": role.name, "url": item.url, "error": reason})
                continue
            if page is None:
                continue
            pages_for_role.append(page)
            summary.pages = len(pages_for_role)
            self._report(
                role_i,
                len(pages_for_role),
                f"[{role.name}] {page.title or page.url}",
                page_id=page.id,
                url=page.url,
                screenshot=page.screenshot,
                role=role.name,
            )

            if item.depth >= o.max_depth:
                for link in page.links:
                    self._unvisited_links.setdefault(link, page)
                continue
            for link in page.links:
                if link not in self._visited and link not in self._queued:
                    self._queued.add(link)
                    queue.append(_QueueItem(link, item.depth + 1, page.url, "link"))
            if o.click_discovery and snap is not None:
                try:
                    found_urls = self._click_discover(self.session, role, page, snap, summary)
                except WebDriverException as exc:
                    log.warning(
                        "[%s] click discovery stopped on %s: %s", role.name, page.url, (exc.msg or "")[:120]
                    )
                    found_urls = []
                    self._recover(role)
                for found in found_urls:
                    if found not in self._visited and found not in self._queued:
                        self._queued.add(found)
                        queue.append(_QueueItem(found, item.depth + 1, page.url, "click"))

        for item in queue:
            if item.via == "link" and item.url not in self._visited:
                src = next((p for p in pages_for_role if p.url == item.source), None)
                if src is not None:
                    self._unvisited_links.setdefault(item.url, src)

    def _visit(
        self, role: Role, item: _QueueItem, summary: RoleCrawlSummary
    ) -> tuple[PageRecord | None, Snapshot | None]:
        o, session = self.opts, self.session
        if item.url in self._visited:
            return None, None
        if self._template_counts.get(urls.template(item.url), 0) >= o.instances_per_template:
            return None, None
        decision = self.guard.check(ActionContext(kind="navigate", href=item.url))
        if not decision.allowed:
            self._blocked(role, item.source, "navigate", item.url, decision.reason, summary)
            return None, None
        self._visited.add(item.url)
        time.sleep(o.rate_limit_s)
        nav = session.navigate(item.url)
        final = self._norm(session.current_url)
        if not self.scope.allows(final):
            log.info("[%s] %s redirected out of scope to %s", role.name, item.url, final)
            return None, None
        if role.name != "public" and final in self._login_pages:
            return None, None  # the login screen itself was already captured in the public pass

        snap = take_snapshot(session.driver)
        if role.name != "public" and auth.find_login_form(snap) and item.via != "login":
            # The session ended (or this page needs a different role). Re-login and retry a few times per role.
            if self._relogins < 3:
                self._relogins += 1
                log.info("[%s] landed on a login page at %s; logging in again", role.name, final)
                if self._login(session, role, RoleCrawlSummary(role=role.name)):
                    nav = session.navigate(item.url)
                    final = self._norm(session.current_url)
                    snap = take_snapshot(session.driver)
            if auth.find_login_form(snap):
                log.info("[%s] %s requires login again; skipping", role.name, item.url)
                return None, None
        if final != item.url:
            if final in self._visited:
                return None, None
            self._visited.add(final)
        final_tpl = urls.template(final)
        if self._template_counts.get(final_tpl, 0) >= o.instances_per_template:
            return None, None
        self._template_counts[final_tpl] = self._template_counts.get(final_tpl, 0) + 1
        return self._capture(session, role, snap, nav, final, item, summary), snap

    # ------------------------------------------------------------------ capture

    def _capture(
        self,
        session: BrowserSession,
        role: Role,
        snap: Snapshot,
        nav: Any,
        final: str,
        item: _QueueItem,
        summary: RoleCrawlSummary,
    ) -> PageRecord:
        self._page_seq += 1
        page_id = f"PG-{self._page_seq:04d}"
        role_dir = slugify(role.name)
        png = session.screenshot_png()
        shot_rel = f"artifacts/screenshots/crawl/{role_dir}/{page_id}.png"
        thumb_rel = f"artifacts/screenshots/crawl/{role_dir}/{page_id}.thumb.jpg"
        self.repo.write_bytes(self.repo.run_path(self.run, shot_rel), png)
        pii = privacy.pii_rects(session.driver)
        if pii:
            self.repo.write_text(
                privacy.sidecar(self.repo.run_path(self.run, shot_rel)), privacy.sidecar_text(pii)
            )
        self.repo.write_bytes(self.repo.run_path(self.run, thumb_rel), _thumbnail(png))
        console, failed = session.drain()
        links = [self._norm(u) for u in snap.absolute_links(final)]
        in_scope = sorted({u for u in links if self.scope.allows(u)})
        page = PageRecord(
            id=page_id,
            role=role.name,
            url=final,
            url_template=urls.template(final),
            title=snap.title,
            status_code=nav.status_code,
            depth=item.depth,
            discovered_from=item.source,
            discovered_via=item.via if final == item.url else "redirect",  # type: ignore[arg-type]
            load_time_ms=nav.load_time_ms,
            screenshot=shot_rel,
            thumbnail=thumb_rel,
            headings=snap.headings,
            text_excerpt=snap.text[:1500],
            elements=snap.elements,
            forms=snap.forms,
            tables=snap.tables,
            links=in_scope,
            console=console,
            failed_requests=failed,
            is_login_page=auth.find_login_form(snap) is not None,
        )
        _scrub(page)
        self.result.pages.append(page)
        raws = check_page(
            page,
            broken_images=snap.broken_images,
            overflow_x=snap.overflow_x,
            slow_page_ms=self.opts.slow_page_ms,
            site_host=self.scope.host,
        )
        if nav.timed_out:
            raws.append(
                RawFinding(
                    "page_timeout",
                    "major",
                    "Page did not finish loading",
                    f"{final} was still loading after {self.opts.page_load_timeout_s}s.",
                    f"timeout:{page.url_template}",
                    {"timeout_s": self.opts.page_load_timeout_s},
                )
            )
        self.collector.add(page, raws)
        return page

    # ------------------------------------------------------------------ SPA click discovery

    @staticmethod
    def _click_candidates(snap: Snapshot) -> list[Element]:
        out: list[Element] = []
        seen: set[tuple[str, str, str]] = set()
        for e in snap.elements:
            if e.disabled or e.form_index is not None:
                continue
            href = e.href.strip()
            no_real_href = e.tag == "a" and (
                not href or href == "#" or href.startswith("#") or href.lower().startswith("javascript:")
            )
            if not (no_real_href or (e.role in _LINK_ROLES and e.tag != "a")):
                continue
            # Twelve identical "Add to cart" links lead to the same place: probe one of them.
            key = ((e.text or e.label).strip().lower(), href, e.role)
            if key[0] and key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    def _click_discover(
        self,
        session: BrowserSession,
        role: Role,
        page: PageRecord,
        snap: Snapshot,
        summary: RoleCrawlSummary,
    ) -> list[str]:
        found: list[str] = []
        candidates = self._click_candidates(snap)[: self.opts.max_clicks_per_page]
        for cand in candidates:
            if self.cancelled():
                break
            label = cand.text or cand.label or cand.locators.test_id
            decision = self.guard.check(
                ActionContext(kind="click", text=label, attributes=cand.attributes, href=cand.href)
            )
            if not decision.allowed:
                self._blocked(role, page.url, "click", label or cand.locators.css, decision.reason, summary)
                continue
            # Reload only when needed: the previous click navigated away, or something (a modal) now
            # covers the element. Reloading after every click made discovery the slowest part of a crawl.
            for attempt in (1, 2):
                if attempt == 2 or self._norm(session.current_url) != page.url:
                    session.navigate(page.url)
                el, _ = locators.find(session.driver, cand.locators)
                if el is None:
                    break
                try:
                    el.click()
                except WebDriverException:
                    continue  # intercepted or stale: reload and retry once
                session.wait_ready(timeout_s=5, settle_ms=300)
                new_url = self._norm(session.current_url)
                if new_url != page.url and self.scope.allows(new_url):
                    found.append(new_url)
                break
        session.drain()  # console noise from discovery clicks belongs to no page
        return found

    # ------------------------------------------------------------------ link check

    def _check_links(self, session: BrowserSession, role: Role) -> None:
        """HEAD-check in-scope links we did not visit (template limit / page budget), with the role's cookies."""
        pending = []
        for url, src in self._unvisited_links.items():
            if self.guard.check(ActionContext(kind="navigate", href=url)).allowed:
                pending.append((url, src))
        pending = pending[: self.opts.max_link_checks]
        if not pending:
            return
        statuses: dict[str, int] = {}
        session.driver.set_script_timeout(60)
        try:
            for i in range(0, len(pending), 15):
                batch = [u for u, _ in pending[i : i + 15]]
                try:
                    statuses.update(session.driver.execute_async_script(LINK_CHECK_JS, batch, 15000))
                except WebDriverException as exc:
                    log.warning(
                        "[%s] link check batch failed: %s", role.name, (exc.msg or "").splitlines()[0]
                    )
        finally:
            session.driver.set_script_timeout(20)
        for url, src in pending:
            status = int(statuses.get(url) or 0)
            if status >= 400:
                self.collector.add_broken_link(src, url, status)

    def _blocked(
        self, role: Role, page_url: str, action: str, target: str, reason: str, summary: RoleCrawlSummary
    ) -> None:
        summary.blocked_actions += 1
        entry = {
            "role": role.name,
            "page": page_url,
            "action": action,
            "target": target[:200],
            "reason": reason,
        }
        if entry not in self.result.blocked_actions:
            self.result.blocked_actions.append(entry)
            log.info("[%s] blocked %s '%s': %s", role.name, action, target[:80], reason)


def _scrub(page: PageRecord) -> None:
    """Credentials must never reach JSON: remove any registered secret that appears in captured page content."""
    page.title = redact(page.title)
    page.text_excerpt = redact(page.text_excerpt)
    page.headings = [redact(h) for h in page.headings]
    for e in page.elements:
        e.text, e.label, e.value, e.placeholder = (
            redact(e.text),
            redact(e.label),
            redact(e.value),
            redact(e.placeholder),
        )
        e.locators.text, e.locators.label = redact(e.locators.text), redact(e.locators.label)
    for c in page.console:
        c.message = redact(c.message)


def _thumbnail(png: bytes, width: int = 360) -> bytes:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    ratio = width / img.width
    img = img.resize((width, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80, optimize=True)
    return buf.getvalue()
