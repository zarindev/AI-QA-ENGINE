"""Offline integration tests: a real headless Chrome against tests/fixtures/site served on localhost."""

from __future__ import annotations

import json

import pytest

from app.browser import auth, locators
from app.browser.dom_snapshot import take_snapshot
from app.browser.driver import BrowserSession
from app.core.logging import register_secret
from app.core.safety import SafetyGuard
from app.explore.crawler import Crawler, CrawlOptions
from app.explore.stage import run_explore
from app.jobs.run_state import RunTracker
from app.storage.schemas import Project, Role, Run, Scope, utcnow

from .conftest import requires_chrome

pytestmark = [pytest.mark.browser, requires_chrome]

PASSWORD = "Sup3r-Secret!"


@pytest.fixture(scope="module")
def browser():
    with BrowserSession(headless=True) as s:
        yield s


def test_snapshot_indexes_elements_forms_and_locators(browser, fixture_site):
    browser.navigate(f"{fixture_site}/patient.html")
    snap = take_snapshot(browser.driver)
    name = next(e for e in snap.elements if e.name == "name")
    age = next(e for e in snap.elements if e.name == "age")
    assert name.required and name.maxlength == 40 and name.label.startswith("Name")
    assert age.type == "number" and (age.min, age.max) == ("0", "120")
    assert snap.forms[0].purpose in ("create", "edit", "other") and snap.forms[0].submit_index is not None
    assert '[0] input:text "Name' in snap.outline() or "input" in snap.outline()
    el, strategy = locators.find(browser.driver, name.locators)
    assert el is not None and strategy == "name"
    assert locators.by_index(browser.driver, age.index).get_attribute("name") == "age"


def test_login_heuristics_and_failure_message(browser, fixture_site, settings):
    guard = SafetyGuard("safe", settings["safety"], preserve_session=True)
    bad = auth.login_with_credentials(
        browser, f"{fixture_site}/login.html", "doc@example.test", "wrong", guard
    )
    assert not bad.ok and "Invalid credentials" in bad.message
    good = auth.login_with_credentials(
        browser, f"{fixture_site}/login.html", "doc@example.test", PASSWORD, guard
    )
    assert good.ok and good.landing_url.endswith("/dashboard.html")
    saved = browser.export_session()
    assert saved["local_storage"] == {"session": "doc"}


def test_full_crawl_public_and_role(repo, settings, fixture_site):
    project = repo.create_project(
        Project(
            slug="fixture",
            name="Fixture Clinic",
            url=f"{fixture_site}/index.html",
            environment="test",
            authorized_by="pytest",
            authorized_at=utcnow(),
            roles=[Role(name="doctor", secret_ref="role:doctor", login_url=f"{fixture_site}/login.html")],
            scope=Scope(max_pages=20, max_depth=3),
        )
    )
    repo.update_secret(project.slug, "role:doctor", {"username": "doc@example.test", "password": PASSWORD})
    register_secret(PASSWORD)
    run = repo.create_run(Run(id="20260101-000000", project_slug=project.slug, mode="safe"))
    tracker = RunTracker(repo, run)
    tracker.start(["explore"])
    settings["crawl"]["rate_limit_s"] = 0
    crawl, findings = run_explore(repo, tracker, project, settings, slow_page_ms=60000)

    by_role = {}
    for p in crawl.pages:
        by_role.setdefault(p.role, set()).add(p.url.rsplit("/", 1)[-1])
    # public pass
    assert {"index.html", "about.html", "patients.html", "reports.html", "login.html"} <= by_role["public"]
    assert "reports.html" in by_role["public"]  # reached only by clicking an href="#" SPA link
    # record pages are grouped by template: only 2 of the 3 patient records are crawled
    assert (
        sum(1 for p in crawl.pages if p.role == "public" and p.url_template == "/patient.html?id={id}") == 2
    )
    # role pass: logged in, saw role-only pages, never re-captured the login page or followed "Log out"
    assert crawl.roles[1].login_ok is True
    assert {"dashboard.html", "schedule.html"} <= by_role["doctor"]
    assert "login.html" not in by_role["doctor"] and "logout.html" not in by_role["doctor"]
    # Safe Mode never opened the delete page
    assert not any("delete" in p.url for p in crawl.pages)
    reasons = " ".join(b["reason"] for b in crawl.blocked_actions)
    assert "delete" in reasons and "logout" in reasons

    checks = {f.check for f in findings.findings}
    assert {"http_error", "js_error", "broken_image", "horizontal_overflow"} <= checks
    missing = next(f for f in findings.findings if f.check == "http_error")
    assert "missing.html" in missing.page_url and missing.severity == "major"

    # files on disk: pages.json, findings.json, screenshots + thumbnails, run state, no credentials anywhere
    rdir = repo.run_dir(project.slug, run.id)
    pages_json = (rdir / "crawl" / "pages.json").read_text(encoding="utf-8")
    assert json.loads(pages_json)["schema_version"] == 1
    for page in crawl.pages:
        assert (rdir / page.screenshot).stat().st_size > 1000
        assert (rdir / page.thumbnail).exists()
    for f in rdir.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".jsonl", ".html"):
            assert PASSWORD not in f.read_text(encoding="utf-8"), f
    assert repo.get_run(project.slug, run.id).stages["explore"].status == "done"
    assert repo.get_index(project.slug).runs[0].pages == len(crawl.pages)


def test_crawler_options_from_settings(settings):
    project = Project(
        slug="p",
        name="p",
        url="https://x.test",
        authorized_by="a",
        authorized_at=utcnow(),
        scope=Scope(max_pages=7, exclude_patterns=[r"/admin"]),
    )
    opts = CrawlOptions.from_settings(settings, project, headless=True, max_depth=None)
    assert opts.max_pages == 7 and opts.max_depth == settings["crawl"]["max_depth"]
    assert r"/admin" in opts.exclude_patterns
    assert Crawler._click_candidates  # click discovery is part of the crawler API
