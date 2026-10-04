"""Review endpoints: requirements (confirm / edit / reject), test cases (edit, approve, add, plain English,
regenerate), cost estimate and exports (requirements PDF/Markdown, Excel, Gherkin)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai.client import DEFAULT_PRICE, PRICING, AIClient, AIUnavailable
from app.api.deps import executor, get_project_or_404, get_run_or_404, repo
from app.core.config import get_settings
from app.explore.stage import PAGES_FILE
from app.jobs.run_state import RunTracker
from app.reports import excel, gherkin, requirements_doc
from app.requirements.stage import REQUIREMENTS_FILE
from app.storage.repository import NotFoundError
from app.storage.schemas import (
    CrawlResult,
    RequirementsDoc,
    Run,
    SiteProfile,
    TestCase,
    TestStep,
    TestSuite,
)
from app.testdesign.generator import assemble, estimate
from app.testdesign.plain_english import from_plain_english
from app.testdesign.rules_based import Draft
from app.testdesign.stage import TESTCASES_FILE, design_suite
from app.understand.stage import PROFILE_FILE

router = APIRouter(prefix="/api/projects/{slug}/runs/{run_id}", tags=["review"])


def _load(run: Run, path: str, cls: Any) -> Any:
    try:
        return repo().load_run_doc(run, path, cls)
    except NotFoundError:
        raise HTTPException(404, "Not available yet for this run.") from None


def _idle(run_id: str) -> None:
    if executor().is_running(run_id):
        raise HTTPException(409, "Wait until the run finishes before editing.")


# ---------------------------------------------------------------- requirements


@router.get("/requirements")
def get_requirements(slug: str, run_id: str) -> dict[str, Any]:
    return _load(get_run_or_404(slug, run_id), REQUIREMENTS_FILE, RequirementsDoc).model_dump(mode="json")


class RuleUpdate(BaseModel):
    status: Literal["proposed", "confirmed", "rejected"] | None = None
    statement: str | None = None
    condition: str | None = None
    notes: str | None = None


@router.patch("/requirements/rules/{rule_id}")
def update_rule(slug: str, run_id: str, rule_id: str, body: RuleUpdate) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)

    def change(doc: RequirementsDoc) -> dict[str, Any]:
        rule = next((r for r in doc.rules if r.id == rule_id), None)
        if rule is None:
            raise HTTPException(404, f"Rule {rule_id} not found")
        edited = False
        for field in ("statement", "condition", "notes"):
            value = getattr(body, field)
            if value is not None and value != getattr(rule, field):
                setattr(rule, field, value.strip())
                edited = field != "notes"
        if body.status:
            rule.status = body.status
        if edited and rule.status in ("confirmed", "proposed") and body.status != "rejected":
            rule.status = "edited"  # an edited rule counts as confirmed
        return rule.model_dump(mode="json")

    return repo().update_run_doc(run, REQUIREMENTS_FILE, RequirementsDoc, change)


class BulkRules(BaseModel):
    ids: list[str]
    status: Literal["proposed", "confirmed", "rejected"]


@router.post("/requirements/rules/bulk")
def bulk_rules(slug: str, run_id: str, body: BulkRules) -> dict[str, int]:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)

    def change(doc: RequirementsDoc) -> int:
        n = 0
        for rule in doc.rules:
            if rule.id in body.ids:
                rule.status = body.status
                n += 1
        return n

    return {"updated": repo().update_run_doc(run, REQUIREMENTS_FILE, RequirementsDoc, change)}


class StoryUpdate(BaseModel):
    status: Literal["proposed", "confirmed", "rejected"]


@router.patch("/requirements/stories/{story_id}")
def update_story(slug: str, run_id: str, story_id: str, body: StoryUpdate) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)

    def change(doc: RequirementsDoc) -> dict[str, Any]:
        story = next((s for s in doc.stories if s.id == story_id), None)
        if story is None:
            raise HTTPException(404, f"Story {story_id} not found")
        story.status = body.status
        return story.model_dump(mode="json")

    return repo().update_run_doc(run, REQUIREMENTS_FILE, RequirementsDoc, change)


# ---------------------------------------------------------------- test cases


@router.get("/testcases")
def get_testcases(slug: str, run_id: str) -> dict[str, Any]:
    return _load(get_run_or_404(slug, run_id), TESTCASES_FILE, TestSuite).model_dump(mode="json")


class StepIn(BaseModel):
    action: str
    data: str = ""
    expected: str = ""


class CaseUpdate(BaseModel):
    title: str | None = None
    priority: Literal["P1", "P2", "P3", "P4"] | None = None
    role: str | None = None
    status: Literal["draft", "approved", "skipped"] | None = None
    preconditions: list[str] | None = None
    steps: list[StepIn] | None = None
    expected_result: str | None = None
    requires_full_mode: bool | None = None


@router.patch("/testcases/{case_id}")
def update_case(slug: str, run_id: str, case_id: str, body: CaseUpdate) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)

    def change(suite: TestSuite) -> dict[str, Any]:
        case = next((c for c in suite.cases if c.id == case_id), None)
        if case is None:
            raise HTTPException(404, f"Test case {case_id} not found")
        content = body.model_dump(exclude_none=True, exclude={"status"})
        if "steps" in content:
            content["steps"] = [TestStep(order=i, **s) for i, s in enumerate(content["steps"], 1)]
        for key, value in content.items():
            setattr(case, key, value)
        if content:
            case.edited = True
        if body.status:
            case.status = body.status
        return case.model_dump(mode="json")

    return repo().update_run_doc(run, TESTCASES_FILE, TestSuite, change)


class BulkCases(BaseModel):
    ids: list[str] = Field(default_factory=list)
    status: Literal["draft", "approved", "skipped"]


@router.post("/testcases/bulk")
def bulk_cases(slug: str, run_id: str, body: BulkCases) -> dict[str, int]:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)

    def change(suite: TestSuite) -> int:
        n = 0
        for case in suite.cases:
            if case.id in body.ids:
                case.status = body.status
                n += 1
        return n

    return {"updated": repo().update_run_doc(run, TESTCASES_FILE, TestSuite, change)}


@router.delete("/testcases/{case_id}", status_code=204)
def delete_case(slug: str, run_id: str, case_id: str) -> None:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)

    def change(suite: TestSuite) -> None:
        before = len(suite.cases)
        suite.cases = [c for c in suite.cases if c.id != case_id]
        if len(suite.cases) == before:
            raise HTTPException(404, f"Test case {case_id} not found")

    repo().update_run_doc(run, TESTCASES_FILE, TestSuite, change)


class CaseIn(BaseModel):
    title: str = Field(min_length=3)
    module: str = "General"
    role: str = ""
    priority: Literal["P1", "P2", "P3", "P4"] = "P2"
    technique: Literal["e2e", "negative", "permission", "business_rule", "data_integrity", "validation"] = (
        "e2e"
    )
    preconditions: list[str] = Field(default_factory=list)
    steps: list[StepIn] = Field(default_factory=list)
    expected_result: str = ""
    requires_full_mode: bool = False


def _add(run: Run, case: TestCase) -> dict[str, Any]:
    def change(suite: TestSuite) -> dict[str, Any]:
        merged = assemble(
            [Draft(case, module=case.module or "General", key=f"user:{case.title}")], suite.cases
        )
        added = next(c for c in merged.cases if c.title == case.title and c.source == case.source and c.id)
        suite.cases = merged.cases
        return added.model_dump(mode="json")

    return repo().update_run_doc(run, TESTCASES_FILE, TestSuite, change)


@router.post("/testcases", status_code=201)
def add_case(slug: str, run_id: str, body: CaseIn) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)
    case = TestCase(
        id="",
        title=body.title,
        module=body.module,
        role=body.role,
        priority=body.priority,
        technique=body.technique,
        preconditions=body.preconditions,
        expected_result=body.expected_result,
        source="user",
        steps=[TestStep(order=i, **s.model_dump()) for i, s in enumerate(body.steps, 1)],
        requires_full_mode=body.requires_full_mode,
        edited=True,
    )
    return _add(run, case)


class PlainEnglishIn(BaseModel):
    text: str = Field(min_length=8, max_length=1000)
    role: str = ""


@router.post("/testcases/plain-english", status_code=201)
def add_plain_english(slug: str, run_id: str, body: PlainEnglishIn) -> dict[str, Any]:
    run = get_run_or_404(slug, run_id)
    _idle(run_id)
    if not AIClient.available():
        raise HTTPException(400, "Plain-English tests need an Anthropic API key (Settings → Claude).")
    crawl = _load(run, PAGES_FILE, CrawlResult)
    profile = _load(run, PROFILE_FILE, SiteProfile)
    ai = AIClient(usage=run.token_usage)
    try:
        case = from_plain_english(ai, body.text, crawl, profile, body.role)
    except AIUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc
    _record_usage(run, ai)
    return _add(run, case)


def _record_usage(run: Run, ai: AIClient) -> None:
    def change(r: Run) -> None:
        r.token_usage = ai.usage

    repo().update_run_doc(run, "run.json", Run, change)


@router.post("/testcases/regenerate", status_code=202)
def regenerate(slug: str, run_id: str) -> dict[str, str]:
    """Re-run test design (e.g. after confirming business rules). Reviewed, edited and hand-written cases are kept."""
    run = get_run_or_404(slug, run_id)
    _idle(run_id)
    crawl = _load(run, PAGES_FILE, CrawlResult)
    profile = _load(run, PROFILE_FILE, SiteProfile)
    req = _load(run, REQUIREMENTS_FILE, RequirementsDoc)

    def job(r: Any, tracker: RunTracker, _overrides: Any) -> None:
        ai = (
            AIClient(usage=tracker.run.token_usage, on_usage=tracker.usage_update)
            if AIClient.available()
            else None
        )
        run_state = tracker.run
        previous_status = run_state.status
        try:
            run_state.status = "running"
            tracker.stage_start("design", "Redesigning test cases with the confirmed rules")
            suite = design_suite(r, run_state, crawl, profile, req, ai)
            tracker.stage_done("design", f"{len(suite.cases)} test cases ready for review")
            tracker.complete(
                run_state.message if previous_status == "completed" else "Test cases regenerated"
            )
        except Exception as exc:
            tracker.fail(f"{type(exc).__name__}: {exc}")

    executor().submit(run, target=job)
    return {"status": "regenerating"}


@router.get("/testcases/estimate")
def get_estimate(
    slug: str, run_id: str, status: str = "approved", mode: Literal["safe", "full"] | None = None
) -> dict:
    run = get_run_or_404(slug, run_id)
    suite: TestSuite = _load(run, TESTCASES_FILE, TestSuite)
    cases = [c for c in suite.cases if status == "all" or c.status == status]
    model = get_settings()["ai"]["model"]
    price = PRICING.get(model, DEFAULT_PRICE)
    est = estimate(cases, (price[0], price[1]), safe_mode=(mode or run.mode) == "safe")
    return {**est.model_dump(), "model": model, "mode": mode or run.mode}


# ---------------------------------------------------------------- exports


EXPORTS = {
    "requirements_pdf": requirements_doc.PDF_FILE,
    "requirements_md": requirements_doc.MD_FILE,
    "testcases_xlsx": excel.TESTCASES_XLSX,
    "gherkin_zip": gherkin.GHERKIN_ZIP,
}


@router.get("/exports")
def list_exports(slug: str, run_id: str) -> list[dict[str, Any]]:
    run = get_run_or_404(slug, run_id)
    out = []
    for kind, rel in EXPORTS.items():
        path = repo().run_path(run, rel)
        if path.exists():
            out.append(
                {"kind": kind, "path": rel, "size": path.stat().st_size, "modified": path.stat().st_mtime}
            )
    return out


@router.post("/exports/{kind}")
def create_export(
    slug: str,
    run_id: str,
    kind: Literal["requirements", "testcases_xlsx", "gherkin_zip"],
    include: Literal["approved", "all"] = "approved",
) -> dict[str, Any]:
    project = get_project_or_404(slug)
    run = get_run_or_404(slug, run_id)
    if kind == "requirements":
        paths = requirements_doc.export(
            repo(),
            project,
            run,
            _load(run, PROFILE_FILE, SiteProfile),
            _load(run, REQUIREMENTS_FILE, RequirementsDoc),
        )
        return {"files": [repo().relative_to_run(run, p) for p in paths.values()]}
    suite: TestSuite = _load(run, TESTCASES_FILE, TestSuite)
    if kind == "testcases_xlsx":
        req = (
            repo().load_run_doc(run, REQUIREMENTS_FILE, RequirementsDoc)
            if repo().has_run_doc(run, REQUIREMENTS_FILE)
            else None
        )
        path = excel.export_testcases(repo(), project, run, suite, req)
    else:
        statuses = ("approved",) if include == "approved" else ("approved", "draft")
        if not any(c.status in statuses for c in suite.cases):
            raise HTTPException(400, "No approved test cases yet — approve some first, or export all.")
        path = gherkin.export(repo(), run, suite, statuses)
    return {"files": [repo().relative_to_run(run, path)]}
