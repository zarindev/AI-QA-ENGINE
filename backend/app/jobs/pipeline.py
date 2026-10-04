"""The run pipeline: executes the stages in order, skipping stages that already finished (resume).

Stages implemented so far: explore → understand → model. Later phases append their stages here.
"""

from __future__ import annotations

from typing import Any

from app.ai.client import AIClient, AIUnavailable, BudgetExceeded
from app.core.config import get_settings
from app.core.logging import get_logger
from app.explore.stage import run_explore
from app.jobs.run_state import RunCancelled, RunTracker
from app.reports.html_basic import render_crawl_report
from app.requirements.stage import run_requirements
from app.storage.repository import Repository
from app.testdesign.stage import run_design
from app.understand.stage import run_model, run_understand

log = get_logger("pipeline")

IMPLEMENTED_STAGES = ["explore", "understand", "model", "requirements", "design", "report"]


def execute(repo: Repository, tracker: RunTracker, overrides: dict[str, Any] | None = None) -> None:
    """Run (or resume) every implemented stage for tracker.run. Never raises: failures are recorded in run.json."""
    run = tracker.run
    settings = get_settings()
    overrides = overrides or {}
    try:
        project = repo.get_project(run.project_slug)
        ai = AIClient(usage=run.token_usage, on_usage=tracker.usage_update) if AIClient.available() else None
        tracker.start(IMPLEMENTED_STAGES)
        crawl, findings = run_explore(repo, tracker, project, settings, ai=ai, **overrides)
        profile = run_understand(repo, tracker, crawl, ai=ai)
        run_model(repo, tracker, crawl, profile)
        req = run_requirements(repo, tracker, crawl, profile, ai=ai)
        suite = run_design(repo, tracker, crawl, profile, req, ai=ai)
        tracker.stage_start("report", "Writing the exploration report")
        render_crawl_report(repo, project, run, crawl, findings)
        tracker.stage_done("report", "Exploration report written")
        tracker.complete(
            f"{len(crawl.pages)} pages · {profile.domain} ({profile.confidence:.0%}) · "
            f"{len(findings.findings)} automatic findings · {len(suite.cases)} test cases to review"
        )
    except RunCancelled:
        tracker.cancel()
    except AIUnavailable as exc:
        tracker.fail(str(exc))  # e.g. no API credits: a plain explanation, resumable once fixed
    except BudgetExceeded as exc:
        tracker.fail(f"Token budget reached: {exc}")
    except Exception as exc:  # the job thread must never die silently
        log.exception("Run %s failed", run.id)
        tracker.fail(f"{type(exc).__name__}: {exc}")
