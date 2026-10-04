"""Run stage ① for a run and persist crawl/pages.json + crawl/findings.json."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.core.safety import SafetyGuard
from app.explore.crawler import Crawler, CrawlOptions
from app.jobs.run_state import RunTracker
from app.storage.repository import Repository
from app.storage.schemas import CrawlResult, FindingsDoc, Project

log = get_logger("explore")

PAGES_FILE = "crawl/pages.json"
FINDINGS_FILE = "crawl/findings.json"


def run_explore(
    repo: Repository,
    tracker: RunTracker,
    project: Project,
    settings: dict[str, Any],
    ai: Any = None,
    **overrides: Any,
) -> tuple[CrawlResult, FindingsDoc]:
    run = tracker.run
    if tracker.run.stages["explore"].status == "done" and repo.has_run_doc(run, PAGES_FILE):
        log.info("Explore already finished for this run; reusing crawl results")
        return repo.load_run_doc(run, PAGES_FILE, CrawlResult), repo.load_run_doc(
            run, FINDINGS_FILE, FindingsDoc
        )

    tracker.stage_start("explore", f"Exploring {project.url}")
    guard = SafetyGuard(run.mode, settings["safety"], preserve_session=True)
    options = CrawlOptions.from_settings(settings, project, **overrides)
    secrets = repo.load_secrets(project.slug)
    crawler = Crawler(
        repo,
        run,
        project,
        options,
        guard,
        secrets,
        ai=ai,
        progress=lambda frac, msg, data: tracker.stage_progress("explore", frac, msg, **data),
        cancelled=tracker.cancel_requested.is_set,
    )
    result, findings = crawler.crawl()
    run.options["browser"] = crawler.browser_version
    repo.save_run_doc(run, PAGES_FILE, result)
    repo.save_run_doc(run, FINDINGS_FILE, findings)
    repo.update_run_summary(project.slug, run.id, pages=len(result.pages), findings=len(findings.findings))
    roles_ok = ", ".join(
        f"{r.role}:{'ok' if r.login_ok in (None, True) else 'login failed'}" for r in result.roles
    )
    tracker.stage_done(
        "explore", f"{len(result.pages)} pages, {len(findings.findings)} findings ({roles_ok})"
    )
    return result, findings
