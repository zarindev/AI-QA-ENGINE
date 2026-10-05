"""Run one test case once: open Chrome, log in as the case's role, execute (agent, replay or rule runner),
record evidence and return an Execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.browser import auth
from app.browser.driver import BrowserSession
from app.core.logging import get_logger
from app.core.paths import BACKEND_DIR
from app.core.safety import SafetyGuard
from app.execute.actions import Actions
from app.execute.agent import Limits, TestAgent
from app.execute.recorder import Recorder
from app.explore.urls import Scope
from app.storage.repository import Repository
from app.storage.schemas import Execution, Project, Run, StepResult, TestCase, TokenUsage, utcnow

log = get_logger("runner")

UPLOAD_FIXTURE = BACKEND_DIR / "app" / "execute" / "fixtures" / "qap-test-upload.txt"
ACCEPT_CONFIRMS_JS = "window.confirm = () => true; window.alert = () => {};"


VIEWPORTS = {"desktop": (1440, 900), "tablet": (768, 1024), "mobile": (390, 844)}


@dataclass
class RunContext:
    repo: Repository
    run: Run
    project: Project
    secrets: dict[str, Any]
    settings: dict[str, Any]
    ai: Any = None
    headless: bool = True
    privacy: bool = False  # blur personal data in videos and bug evidence


def resolve_role(project: Project, wanted: str) -> str:
    """Claude may write "Receptionist" or "receptionists"; map to the project's role names."""
    w = (wanted or "").strip().lower().rstrip("s")
    if not w or w in ("public", "visitor", "anonymous", "guest", "signed out", "any role", "any"):
        return "public" if w in ("public", "visitor", "anonymous", "guest", "signed out") else ""
    for role in project.roles:
        if role.name.lower().rstrip("s") == w:
            return role.name
    return ""


def open_session(
    ctx: RunContext, role: str, width: int = 1440, height: int = 900
) -> tuple[BrowserSession, str]:
    """A fresh browser per test (clean cookies and storage), logged in as `role`. Returns (session, note)."""
    session = BrowserSession(headless=ctx.headless, width=width, height=height)
    if ctx.run.mode == "full":
        session.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument", {"source": ACCEPT_CONFIRMS_JS}
        )
    if not role or role == "public":
        session.navigate(ctx.project.url)
        return session, "Signed out"
    project_role = next((r for r in ctx.project.roles if r.name == role), None)
    if project_role is None:
        return session, f"Unknown role {role}"
    guard = SafetyGuard(ctx.run.mode, ctx.settings["safety"])
    if project_role.login_strategy == "manual_session":
        saved = ctx.secrets.get(f"session:{role}")
        result = (
            auth.restore_session(session, saved, ctx.project.url)
            if saved
            else auth.LoginResult(False, "No saved session")
        )
    else:
        creds = ctx.secrets.get(project_role.secret_ref or f"role:{role}", {})
        result = auth.login_with_credentials(
            session,
            ctx.project.url,
            creds.get("username", ""),
            creds.get("password", ""),
            guard,
            ai=ctx.ai,
            login_url=project_role.login_url,
        )
    if not result.ok:
        raise LoginFailed(f"Could not log in as {role}: {result.message}")
    session.drain()  # login noise is not part of the test
    return session, result.message


class LoginFailed(RuntimeError):
    pass


def run_agent_case(ctx: RunContext, case: TestCase, attempt: int) -> Execution:
    role = resolve_role(ctx.project, case.role)
    started = utcnow()
    usage_before = ctx.ai.usage.model_copy()
    viewport = next((v for v in case.viewports if v in VIEWPORTS), "desktop")
    try:
        session, _note = open_session(ctx, role, *VIEWPORTS[viewport])
    except LoginFailed as exc:
        return Execution(
            test_case_id=case.id,
            attempt=attempt,
            result="blocked",
            reason=str(exc),
            role=role,
            started_at=started,
            finished_at=utcnow(),
            method="agent",
        )
    try:
        scope = Scope(ctx.project.url, ctx.project.scope.include_patterns, ctx.project.scope.exclude_patterns)
        guard = SafetyGuard(ctx.run.mode, ctx.settings["safety"])
        actions = Actions(session, guard, scope, UPLOAD_FIXTURE)
        recorder = Recorder(ctx.repo, ctx.run, session, case.id, attempt, scope.host)
        limits = Limits(
            **{k: v for k, v in ctx.settings.get("execute", {}).items() if k in Limits.__dataclass_fields__}
        )
        agent = TestAgent(
            ctx.ai,
            actions,
            recorder,
            case,
            role,
            ctx.project.url,
            limits,
            effort=ctx.settings.get("execute", {}).get("agent_effort", "low"),
        )
        verdict = agent.run()
        try:
            final_text = actions.observe().text[:5000]
        except Exception:  # the page may be gone; the recalculation is then skipped
            final_text = ""
        files = recorder.finish(f"{case.id} · {case.title}", blur=ctx.privacy)
    finally:
        session.close()
    usage = _usage_delta(usage_before, ctx.ai.usage)
    return Execution(
        test_case_id=case.id,
        attempt=attempt,
        result=verdict.result,
        reason=verdict.reason,
        expected=verdict.expected,  # type: ignore[arg-type]
        actual=verdict.actual,
        confidence=verdict.confidence,
        method="agent",
        role=role,
        started_at=started,
        finished_at=utcnow(),
        steps=verdict.steps,
        failure_step=verdict.failure_step,
        viewport=viewport,
        auto_findings=recorder.findings,
        final_page_text=final_text,
        video=files.get("video", ""),
        console_log=files.get("console", ""),
        network_log=files.get("network", ""),
        token_usage=usage,
    )


def _usage_delta(before: TokenUsage, after: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=after.input_tokens - before.input_tokens,
        output_tokens=after.output_tokens - before.output_tokens,
        cache_read_tokens=after.cache_read_tokens - before.cache_read_tokens,
        cache_write_tokens=after.cache_write_tokens - before.cache_write_tokens,
        requests=after.requests - before.requests,
        cost_usd=round(after.cost_usd - before.cost_usd, 4),
    )


def blocked_execution(case: TestCase, attempt: int, reason: str, role: str = "") -> Execution:
    return Execution(
        test_case_id=case.id,
        attempt=attempt,
        result="blocked",
        reason=reason,
        role=role,
        finished_at=utcnow(),
        method="rule",
        steps=[
            StepResult(order=1, action="skip", observation=reason, result="blocked", blocked_reason=reason)
        ],
    )


def fixture_path() -> Path:
    return UPLOAD_FIXTURE
