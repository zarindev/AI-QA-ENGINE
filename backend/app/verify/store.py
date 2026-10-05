"""Loads run documents and computes the insight views (quality, heatmap, permission matrix, regression)."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.execute.stage import BUGS_FILE, RESULTS_FILE
from app.explore.stage import PAGES_FILE
from app.storage.repository import Repository
from app.storage.schemas import Bug, BugsDoc, CrawlResult, ExecutionsDoc, ResultsDoc, Run, TestSuite
from app.testdesign.stage import TESTCASES_FILE
from app.verify import insights

QUALITY_FILE = "quality.json"
PERMISSIONS_FILE = "permissions.json"


def _load(repo: Repository, run: Run, path: str, cls: type) -> Any:
    return repo.load_run_doc(run, path, cls) if repo.has_run_doc(run, path) else None


def bugs_of(repo: Repository, run: Run) -> list[Bug]:
    doc = _load(repo, run, BUGS_FILE, BugsDoc)
    return doc.bugs if doc else []


def refresh_quality(repo: Repository, run: Run) -> insights.Quality | None:
    """Recompute the Quality Score (after execution, and whenever a bug is triaged) and store it."""
    results = _load(repo, run, RESULTS_FILE, ResultsDoc)
    if results is None:
        return None
    crawl = _load(repo, run, PAGES_FILE, CrawlResult)
    slow_ms = int(get_settings().get("crawl", {}).get("slow_page_ms", 3000))
    q = insights.quality(results, bugs_of(repo, run), crawl, slow_ms)
    repo.save_model(repo.run_path(run, QUALITY_FILE), q)
    repo.update_run_summary(run.project_slug, run.id, quality_score=q.score)
    return q


def quality(repo: Repository, run: Run) -> insights.Quality | None:
    if repo.has_run_doc(run, QUALITY_FILE):
        return repo.load_run_doc(run, QUALITY_FILE, insights.Quality)
    return refresh_quality(repo, run)


def heatmap(repo: Repository, run: Run) -> insights.Heatmap | None:
    suite = _load(repo, run, TESTCASES_FILE, TestSuite)
    if suite is None:
        return None
    return insights.heatmap(suite, _load(repo, run, RESULTS_FILE, ResultsDoc))


def first_attempts(repo: Repository, run: Run, case_ids: list[str]) -> dict[str, Any]:
    out = {}
    for cid in case_ids:
        doc = _load(repo, run, f"executions/{cid}.json", ExecutionsDoc)
        if doc and doc.attempts:
            out[cid] = doc.attempts[0]
    return out


def permission_matrix(repo: Repository, run: Run) -> insights.PermissionMatrixView | None:
    crawl = _load(repo, run, PAGES_FILE, CrawlResult)
    if crawl is None:
        return None
    suite = _load(repo, run, TESTCASES_FILE, TestSuite)
    ids = [c.id for c in suite.cases if c.technique == "permission"] if suite else []
    view = insights.permission_matrix(crawl, suite, first_attempts(repo, run, ids))
    repo.save_model(repo.run_path(run, PERMISSIONS_FILE), view)
    return view


def compare(repo: Repository, run: Run, base_id: str | None = None) -> insights.Comparison | None:
    """Regression comparison against `base_id`, or the newest earlier run that has bugs."""
    earlier = [
        r
        for r in repo.list_runs(run.project_slug)
        if r.id < run.id and repo.has_run_doc(r, BUGS_FILE) and r.id != run.id
    ]
    if base_id:
        base = next((r for r in earlier if r.id == base_id), None)
        if base is None:
            return None
    elif earlier:
        base = earlier[0]
    else:
        return None
    history = [bugs_of(repo, r) for r in earlier if r.id < base.id]
    return insights.compare(run.id, bugs_of(repo, run), base.id, bugs_of(repo, base), history)
