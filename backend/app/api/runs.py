"""Runs: start / cancel / resume, run data (pages, findings, profile, model), artifacts and live events (SSE)."""

from __future__ import annotations

import asyncio
import json
import queue
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import executor, get_project_or_404, get_run_or_404, repo
from app.explore.stage import FINDINGS_FILE, PAGES_FILE
from app.reports.html_basic import REPORT_FILE
from app.storage.repository import NotFoundError
from app.storage.schemas import CrawlResult, FindingsDoc, Run, SiteProfile
from app.understand import model_builder
from app.understand.stage import MODEL_FILE, PROFILE_FILE

router = APIRouter(prefix="/api/projects/{slug}/runs", tags=["runs"])


class RunIn(BaseModel):
    mode: Literal["safe", "full"] = "safe"
    confirm_full_mode: bool = False
    max_pages: int | None = None
    headless: bool | None = None


@router.get("")
def list_runs(slug: str) -> list[dict[str, Any]]:
    get_project_or_404(slug)
    out = []
    for summary in repo().get_index(slug).runs:
        item = summary.model_dump(mode="json")
        item["running"] = executor().is_running(summary.id)
        out.append(item)
    return out


@router.post("", status_code=202)
def start_run(slug: str, body: RunIn) -> dict[str, Any]:
    project = get_project_or_404(slug)
    if body.mode == "full":
        if project.environment not in ("staging", "test"):
            raise HTTPException(400, "Full Mode is only available for projects marked staging or test.")
        if not body.confirm_full_mode:
            raise HTTPException(
                400, "Full Mode may change or delete data. Confirm it explicitly to continue."
            )
    index = repo().get_index(slug)
    if index.runs and executor().is_running(index.runs[0].id):
        raise HTTPException(409, "A run is already in progress for this project.")
    run = repo().create_run(Run(id=repo().new_run_id(slug), project_slug=slug, mode=body.mode))
    overrides = {
        k: v for k, v in {"max_pages": body.max_pages, "headless": body.headless}.items() if v is not None
    }
    executor().submit(run, overrides)
    return run.model_dump(mode="json")


@router.get("/{run_id}")
def get_run(slug: str, run_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    data = run.model_dump(mode="json")
    data["running"] = executor().is_running(run_id)
    data["available"] = {
        name: repo().has_run_doc(run, path)
        for name, path in (
            ("pages", PAGES_FILE),
            ("findings", FINDINGS_FILE),
            ("profile", PROFILE_FILE),
            ("model", MODEL_FILE),
            ("report", REPORT_FILE),
            ("requirements", "requirements.json"),
            ("testcases", "testcases.json"),
        )
    }
    return data


@router.post("/{run_id}/cancel")
def cancel_run(slug: str, run_id: str) -> dict[str, str]:
    get_run_or_404(slug, run_id)
    if not executor().cancel(run_id):
        raise HTTPException(409, "This run is not running.")
    return {"status": "cancelling"}


@router.post("/{run_id}/resume", status_code=202)
def resume_run(slug: str, run_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    if executor().is_running(run_id):
        raise HTTPException(409, "This run is already running.")
    if run.status not in ("interrupted", "failed", "cancelled"):
        raise HTTPException(400, f"A {run.status} run cannot be resumed.")
    executor().submit(run)
    return run.model_dump(mode="json")


def _doc(slug: str, run_id: str, path: str, cls: Any) -> Any:
    run = get_run_or_404(slug, run_id)
    try:
        return repo().load_run_doc(run, path, cls)
    except NotFoundError:
        raise HTTPException(404, "Not available yet for this run.") from None


@router.get("/{run_id}/pages")
def run_pages(slug: str, run_id: str, role: str | None = None) -> dict[str, Any]:
    crawl: CrawlResult = _doc(slug, run_id, PAGES_FILE, CrawlResult)
    pages = [p for p in crawl.pages if role is None or p.role == role]
    return {
        "roles": [r.model_dump(mode="json") for r in crawl.roles],
        "blocked_actions": crawl.blocked_actions,
        "errors": crawl.errors,
        # elements are heavy; the list view only needs counts
        "pages": [
            p.model_dump(mode="json", exclude={"elements", "text_excerpt"})
            | {"element_count": len(p.elements)}
            for p in pages
        ],
    }


@router.get("/{run_id}/pages/{page_id}")
def run_page(slug: str, run_id: str, page_id: str) -> dict[str, Any]:
    crawl: CrawlResult = _doc(slug, run_id, PAGES_FILE, CrawlResult)
    page = next((p for p in crawl.pages if p.id == page_id), None)
    if page is None:
        raise HTTPException(404, "Page not found in this run.")
    return page.model_dump(mode="json")


@router.get("/{run_id}/findings")
def run_findings(slug: str, run_id: str) -> dict[str, Any]:
    return _doc(slug, run_id, FINDINGS_FILE, FindingsDoc).model_dump(mode="json")


@router.get("/{run_id}/profile")
def run_profile(slug: str, run_id: str) -> dict[str, Any]:
    return _doc(slug, run_id, PROFILE_FILE, SiteProfile).model_dump(mode="json")


@router.get("/{run_id}/model")
def run_model(
    slug: str, run_id: str, view: Literal["graph", "reactflow"] = "reactflow", kinds: str = "role,page,entity"
) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    try:
        data = repo().read_json(repo().run_path(run, MODEL_FILE))
    except NotFoundError:
        raise HTTPException(404, "The site model is not built yet.") from None
    if view == "graph":
        return data
    return model_builder.to_react_flow(model_builder.from_json(data), [k for k in kinds.split(",") if k])


@router.get("/{run_id}/files/{path:path}")
def run_file(slug: str, run_id: str, path: str) -> FileResponse:
    run = get_run_or_404(slug, run_id)
    base = repo().run_dir(slug, run.id).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "File not found.")
    return FileResponse(target)


@router.get("/{run_id}/events")
async def run_events(slug: str, run_id: str, request: Request) -> EventSourceResponse:
    """Server-sent events: the run's history first (from events.jsonl), then live events until it finishes."""
    run = get_run_or_404(slug, run_id)
    bus = executor().bus
    q = bus.subscribe(run_id)
    log_file: Path = repo().run_path(run, "artifacts/logs/events.jsonl")

    async def stream():
        try:
            if log_file.exists():
                for line in log_file.read_text(encoding="utf-8").splitlines()[-300:]:
                    yield {"event": "history", "data": line}
            yield {"event": "state", "data": json.dumps(repo().get_run(slug, run_id).model_dump(mode="json"))}
            while not await request.is_disconnected():
                try:
                    event = await asyncio.to_thread(q.get, True, 1.0)
                except queue.Empty:
                    if not executor().is_running(run_id):
                        yield {
                            "event": "state",
                            "data": json.dumps(repo().get_run(slug, run_id).model_dump(mode="json")),
                        }
                        break
                    continue
                yield {"event": event["type"], "data": json.dumps(event, default=str)}
        finally:
            bus.unsubscribe(run_id, q)

    return EventSourceResponse(stream(), ping=15)
