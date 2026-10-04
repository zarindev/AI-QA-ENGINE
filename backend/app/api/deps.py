"""Process-wide singletons shared by the API routers."""

from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from app.jobs.executor import JobExecutor
from app.storage.repository import NotFoundError, Repository
from app.storage.schemas import Project, Run


@lru_cache(maxsize=1)
def repo() -> Repository:
    return Repository()


@lru_cache(maxsize=1)
def executor() -> JobExecutor:
    return JobExecutor(repo())


def get_project_or_404(slug: str) -> Project:
    try:
        return repo().get_project(slug)
    except NotFoundError:
        raise HTTPException(404, f"Project '{slug}' not found") from None


def get_run_or_404(slug: str, run_id: str) -> Run:
    get_project_or_404(slug)
    try:
        return repo().get_run(slug, run_id)
    except NotFoundError:
        raise HTTPException(404, f"Run '{run_id}' not found") from None
