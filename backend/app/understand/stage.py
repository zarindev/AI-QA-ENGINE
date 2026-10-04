"""Run stages ② Understand and ③ Site Model for a run and persist site_profile.json + site_model.json."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.jobs.run_state import RunTracker
from app.storage.repository import Repository
from app.storage.schemas import CrawlResult, SiteProfile
from app.understand import classifier, model_builder

log = get_logger("understand")

PROFILE_FILE = "site_profile.json"
MODEL_FILE = "site_model.json"


def run_understand(repo: Repository, tracker: RunTracker, crawl: CrawlResult, ai: Any = None) -> SiteProfile:
    run = tracker.run
    if run.stages["understand"].status == "done" and repo.has_run_doc(run, PROFILE_FILE):
        return repo.load_run_doc(run, PROFILE_FILE, SiteProfile)
    if ai is not None and ai.available():
        tracker.stage_start("understand", "Claude is reading the screens to work out what this app is")
        profile = classifier.classify_with_ai(ai, crawl, repo.run_dir(run.project_slug, run.id))
    else:
        tracker.stage_start("understand", "No API key: classifying offline from keywords")
        log.warning(
            "ANTHROPIC_API_KEY not set — using the heuristic classifier (lower confidence, fewer details)"
        )
        profile = classifier.classify_heuristic(crawl)
    repo.save_run_doc(run, PROFILE_FILE, profile)
    repo.update_run_summary(run.project_slug, run.id, domain=profile.domain)
    tracker.stage_done(
        "understand", f"{profile.domain} · {profile.sub_type} ({profile.confidence:.0%}, {profile.method})"
    )
    return profile


def run_model(repo: Repository, tracker: RunTracker, crawl: CrawlResult, profile: SiteProfile) -> dict:
    run = tracker.run
    tracker.stage_start("model", "Building the site knowledge graph")
    graph = model_builder.build_model(crawl, profile)
    data = model_builder.to_json(graph)
    repo.write_json(repo.run_path(run, MODEL_FILE), data)
    s = data["stats"]
    tracker.stage_done(
        "model", f"{s['page']} screens, {s['entity']} entities, {s['role']} roles, {s['edges']} links"
    )
    return data
