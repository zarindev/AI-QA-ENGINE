"""Coverage & Quality, Permission Matrix and Regression comparison views."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import get_run_or_404, repo
from app.verify import store

router = APIRouter(prefix="/api/projects/{slug}/runs/{run_id}", tags=["insights"])


@router.get("/quality")
def get_quality(slug: str, run_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    q = store.quality(repo(), run)
    if q is None:
        raise HTTPException(404, "No results yet — the Quality Score is computed after tests run.")
    heat = store.heatmap(repo(), run)
    return {"quality": q.model_dump(mode="json"), "heatmap": heat.model_dump(mode="json") if heat else None}


@router.get("/permissions")
def get_permissions(slug: str, run_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    view = store.permission_matrix(repo(), run)
    if view is None:
        raise HTTPException(404, "No exploration data yet.")
    return view.model_dump(mode="json")


@router.get("/compare")
def get_compare(slug: str, run_id: str, base: str | None = None) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    earlier = [r.id for r in repo().list_runs(slug) if r.id < run_id and repo().has_run_doc(r, "bugs.json")]
    cmp = store.compare(repo(), run, base)
    return {"available": earlier, "comparison": cmp.model_dump(mode="json") if cmp else None}
