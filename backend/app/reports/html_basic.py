"""Basic HTML crawl report (Phase 1). Written to <run>/exports/crawl_report.html; open it in any browser."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import __version__
from app.core.paths import TEMPLATES_DIR
from app.storage.repository import Repository
from app.storage.schemas import CrawlResult, FindingsDoc, Project, Run

REPORT_FILE = "exports/crawl_report.html"


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html"]))


def render_crawl_report(
    repo: Repository, project: Project, run: Run, crawl: CrawlResult, findings: FindingsDoc
) -> Path:
    severity_counts = Counter(f.severity for f in findings.findings)
    pages_by_role: dict[str, list] = {}
    for page in crawl.pages:
        pages_by_role.setdefault(page.role, []).append(page)
    html = (
        _env()
        .get_template("crawl_report.html.j2")
        .render(
            project=project,
            run=run,
            crawl=crawl,
            findings=findings.findings,
            severity_counts=severity_counts,
            pages_by_role=pages_by_role,
            version=__version__,
            # the report lives in exports/, artifacts are one level up
            asset_prefix="../",
        )
    )
    path = repo.run_path(run, REPORT_FILE)
    repo.write_text(path, html)
    return path
