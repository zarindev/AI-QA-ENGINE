"""Per-project index.json helpers for fast listing (the repository keeps it in sync on every run save)."""

from __future__ import annotations

from app.storage.repository import Repository
from app.storage.schemas import RunSummary


def latest_run(repo: Repository, slug: str) -> RunSummary | None:
    runs = repo.get_index(slug).runs
    return runs[0] if runs else None


def latest_completed_run(repo: Repository, slug: str) -> RunSummary | None:
    for summary in repo.get_index(slug).runs:
        if summary.status == "completed":
            return summary
    return None
