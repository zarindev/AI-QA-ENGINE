"""Run stage ⑤ Test design and persist testcases.json (also used by "Regenerate" in the review screen)."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.jobs.run_state import RunTracker
from app.storage.repository import Repository
from app.storage.schemas import CrawlResult, RequirementsDoc, Run, SiteProfile, TestSuite
from app.testdesign.generator import design

log = get_logger("design")

TESTCASES_FILE = "testcases.json"


def design_suite(
    repo: Repository, run: Run, crawl: CrawlResult, profile: SiteProfile, req: RequirementsDoc, ai: Any = None
) -> TestSuite:
    previous = (
        repo.load_run_doc(run, TESTCASES_FILE, TestSuite) if repo.has_run_doc(run, TESTCASES_FILE) else None
    )
    suite = design(crawl, profile, req, ai=ai, previous=previous)
    repo.save_run_doc(run, TESTCASES_FILE, suite)
    return suite


def run_design(
    repo: Repository,
    tracker: RunTracker,
    crawl: CrawlResult,
    profile: SiteProfile,
    req: RequirementsDoc,
    ai: Any = None,
) -> TestSuite:
    run = tracker.run
    if run.stages["design"].status == "done" and repo.has_run_doc(run, TESTCASES_FILE):
        return repo.load_run_doc(run, TESTCASES_FILE, TestSuite)
    tracker.stage_start("design", "Designing test cases")
    suite = design_suite(repo, run, crawl, profile, req, ai)
    by_source = sum(1 for c in suite.cases if c.source == "ai")
    tracker.stage_done(
        "design",
        f"{len(suite.cases)} test cases ready for review ({by_source} designed by Claude)",
    )
    return suite
