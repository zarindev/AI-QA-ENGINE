"""Run stage ④ Requirements and persist requirements.json."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.jobs.run_state import RunTracker
from app.requirements import generator
from app.storage.repository import Repository
from app.storage.schemas import CrawlResult, RequirementsDoc, SiteProfile

log = get_logger("requirements")

REQUIREMENTS_FILE = "requirements.json"


def run_requirements(
    repo: Repository, tracker: RunTracker, crawl: CrawlResult, profile: SiteProfile, ai: Any = None
) -> RequirementsDoc:
    run = tracker.run
    if run.stages["requirements"].status == "done" and repo.has_run_doc(run, REQUIREMENTS_FILE):
        return repo.load_run_doc(run, REQUIREMENTS_FILE, RequirementsDoc)
    if ai is not None and ai.available():
        tracker.stage_start("requirements", "Claude is writing user stories, workflows and business rules")
        doc = generator.generate_with_ai(ai, crawl, profile)
    else:
        tracker.stage_start(
            "requirements", "No API key: deriving requirements from forms and the domain pack"
        )
        doc = generator.generate_heuristic(crawl, profile)
    repo.save_run_doc(run, REQUIREMENTS_FILE, doc)
    tracker.stage_done(
        "requirements",
        f"{len(doc.stories)} stories, {len(doc.workflows)} workflows, {len(doc.rules)} rules to review",
    )
    return doc
