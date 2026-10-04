"""Execution endpoints: run approved tests, results, per-test attempts, bugs (status, replay)."""

from __future__ import annotations

import threading
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai.client import AIClient
from app.api.deps import executor, get_project_or_404, get_run_or_404, repo
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.safety import SafetyGuard
from app.execute.actions import Actions
from app.execute.replayer import REPLAYABLE, _replay_step
from app.execute.runner import RunContext, open_session, resolve_role
from app.execute.stage import BUGS_FILE, RESULTS_FILE, execute_job
from app.explore.urls import Scope
from app.storage.repository import NotFoundError
from app.storage.schemas import BugsDoc, ExecutionsDoc, ReplayScript, ResultsDoc, TestSuite
from app.testdesign.stage import TESTCASES_FILE

router = APIRouter(prefix="/api/projects/{slug}/runs/{run_id}", tags=["execution"])
log = get_logger("api.execution")


class ExecuteIn(BaseModel):
    case_ids: list[str] | None = None
    headless: bool | None = None
    resume: bool = False  # skip tests that already finished in the last execution pass


@router.post("/execute", status_code=202)
def start_execution(slug: str, run_id: str, body: ExecuteIn) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    if executor().is_running(run_id):
        raise HTTPException(409, "This run is busy.")
    try:
        suite = repo().load_run_doc(run, TESTCASES_FILE, TestSuite)
    except NotFoundError:
        raise HTTPException(404, "Design and approve test cases first.") from None
    chosen = [c for c in suite.cases if (c.id in body.case_ids if body.case_ids else c.status == "approved")]
    if not chosen:
        raise HTTPException(400, "No approved test cases to run.")
    needs_ai = [
        c
        for c in chosen
        if not (
            c.source == "generated"
            and c.technique in ("smoke", "permission", "ui_responsive", "accessibility")
        )
    ]
    overrides: dict[str, Any] = {"case_ids": body.case_ids, "resume": body.resume}
    if body.headless is not None:
        overrides["headless"] = body.headless
    executor().submit(run, overrides, target=execute_job)
    return {
        "status": "running",
        "cases": len(chosen),
        "agent_cases": len(needs_ai),
        "ai": AIClient.available(),
        "mode": run.mode,
    }


@router.get("/results")
def get_results(slug: str, run_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    try:
        return repo().load_run_doc(run, RESULTS_FILE, ResultsDoc).model_dump(mode="json")
    except NotFoundError:
        raise HTTPException(404, "No results yet — run the approved tests.") from None


@router.get("/executions/{case_id}")
def get_executions(slug: str, run_id: str, case_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    try:
        return repo().load_run_doc(run, f"executions/{case_id}.json", ExecutionsDoc).model_dump(mode="json")
    except NotFoundError:
        raise HTTPException(404, f"{case_id} has not been executed.") from None


@router.get("/bugs")
def get_bugs(slug: str, run_id: str) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    try:
        return repo().load_run_doc(run, BUGS_FILE, BugsDoc).model_dump(mode="json")
    except NotFoundError:
        raise HTTPException(404, "No bugs file yet.") from None


class BugUpdate(BaseModel):
    status: Literal["new", "needs_review", "confirmed", "rejected", "fixed"] | None = None
    severity: Literal["critical", "major", "minor", "trivial"] | None = None
    priority: Literal["P1", "P2", "P3", "P4"] | None = None


@router.patch("/bugs/{bug_id}")
def update_bug(slug: str, run_id: str, bug_id: str, body: BugUpdate) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)

    def change(doc: BugsDoc) -> dict[str, Any]:
        bug = next((b for b in doc.bugs if b.id == bug_id), None)
        if bug is None:
            raise HTTPException(404, f"{bug_id} not found")
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(bug, k, v)
        return bug.model_dump(mode="json")

    result = repo().update_run_doc(run, BUGS_FILE, BugsDoc, change)
    bugs = repo().load_run_doc(run, BUGS_FILE, BugsDoc).bugs
    repo().update_run_summary(
        slug, run_id, bugs=sum(1 for b in bugs if b.status not in ("rejected", "fixed"))
    )
    return result


_replays: dict[str, str] = {}


@router.post("/bugs/{bug_id}/replay", status_code=202)
def replay_bug(slug: str, run_id: str, bug_id: str) -> dict[str, str]:
    """One-click Bug Replay: a visible Chrome window replays the recorded steps so a developer can watch it fail."""
    project = get_project_or_404(slug)
    run = get_run_or_404(slug, run_id)
    bugs = repo().load_run_doc(run, BUGS_FILE, BugsDoc).bugs
    bug = next((b for b in bugs if b.id == bug_id), None)
    if bug is None:
        raise HTTPException(404, f"{bug_id} not found")
    case_id = next(iter(bug.test_case_ids), "")
    key = f"{slug}/{run_id}/{bug_id}"
    if _replays.get(key) == "running":
        raise HTTPException(409, "This bug is already being replayed.")
    script: ReplayScript | None = None
    if case_id and repo().has_run_doc(run, f"replay/{case_id}.json"):
        script = repo().load_run_doc(run, f"replay/{case_id}.json", ReplayScript)
    elif case_id and repo().has_run_doc(run, f"executions/{case_id}.json"):
        first = repo().load_run_doc(run, f"executions/{case_id}.json", ExecutionsDoc).attempts[0]
        from app.execute.replayer import script_from

        suite = repo().load_run_doc(run, TESTCASES_FILE, TestSuite)
        case = next(c for c in suite.cases if c.id == case_id)
        script = script_from(case, first)
        if not script.steps:  # rule-runner tests: replay = open the pages they checked
            from app.storage.schemas import ReplayStep

            script.steps = [
                ReplayStep(action="navigate", url=s.input or s.url)
                for s in first.steps
                if s.action == "navigate"
            ]
    if script is None:
        if not bug.environment.url:
            raise HTTPException(400, "Nothing recorded to replay for this bug.")
        from app.storage.schemas import ReplayStep

        script = ReplayScript(
            test_case_id="",
            role=bug.environment.role,
            steps=[ReplayStep(action="navigate", url=bug.environment.url)],
        )

    settings = get_settings()

    def work() -> None:
        _replays[key] = "running"
        ctx = RunContext(repo(), run, project, repo().load_secrets(slug), settings, None, headless=False)
        role = resolve_role(project, script.role) or (
            "public" if script.role in ("", "public", "signed out") else ""
        )
        try:
            session, _ = open_session(ctx, role)
            actions = Actions(session, SafetyGuard(run.mode, settings["safety"]), Scope(project.url))
            for step in script.steps:
                if step.action in REPLAYABLE:
                    _replay_step(actions, step)
                    threading.Event().wait(1.2)  # slow enough to follow along
            # leave the window open for inspection, close after a while
            threading.Event().wait(120)
            session.close()
            _replays[key] = "done"
        except Exception as exc:
            log.warning("replay of %s failed: %s", bug_id, exc)
            _replays[key] = "error"

    threading.Thread(target=work, daemon=True, name=f"replay-{bug_id}").start()
    return {
        "status": "replaying",
        "message": "A Chrome window is replaying the bug. It closes after two minutes.",
    }
