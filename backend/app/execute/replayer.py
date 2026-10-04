"""Deterministic replay with self-healing.

A recorded agent run becomes a replay script (actions + multi-strategy locators). Replaying it needs no AI per
step; at the end one Claude call judges the final state against the test's checks. If an element can no longer
be found by any locator strategy, the agent takes over for that test (self-healing) and the result is marked
`replay_healed`.
"""

from __future__ import annotations

import base64
from typing import Any, Literal

from pydantic import BaseModel

from app.browser import locators
from app.core.logging import get_logger
from app.core.safety import SafetyGuard
from app.execute import media
from app.execute.actions import Actions
from app.execute.recorder import Recorder
from app.execute.runner import (
    UPLOAD_FIXTURE,
    LoginFailed,
    RunContext,
    _usage_delta,
    open_session,
    resolve_role,
    run_agent_case,
)
from app.explore.urls import Scope
from app.storage.schemas import Execution, ReplayScript, ReplayStep, StepResult, TestCase, utcnow

log = get_logger("replay")

REPLAYABLE = ("click", "type", "select", "check", "upload", "navigate", "scroll")


def script_from(case: TestCase, execution: Execution) -> ReplayScript:
    steps = [
        ReplayStep(action=s.action, locators=s.locators, input=s.input, url=s.url, target=s.target)
        for s in execution.steps
        if s.action in REPLAYABLE and s.result != "blocked"
    ]
    checks = [s.target for s in execution.steps if s.action == "assert"] or [case.expected_result]
    return ReplayScript(
        test_case_id=case.id,
        role=execution.role,
        steps=steps,
        checks=checks,
        recorded_result=execution.result,
    )


class Judgement(BaseModel):
    result: Literal["pass", "fail", "blocked"]
    expected: str
    actual: str
    confidence: float


JUDGE_SYSTEM = (
    "You verify the final state of a web application after a recorded test was replayed. Compare what the page "
    "shows with every check listed. 'fail' when any check is not met by the application; 'blocked' when the page "
    "is not the one the checks are about (the replay went wrong); otherwise 'pass'. Quote the values you see in "
    "`actual`. Recompute numbers yourself."
)


def replay_case(ctx: RunContext, case: TestCase, script: ReplayScript, attempt: int) -> Execution:
    role = resolve_role(ctx.project, case.role) or script.role
    started = utcnow()
    usage_before = ctx.ai.usage.model_copy()
    try:
        session, _ = open_session(ctx, role)
    except LoginFailed as exc:
        return Execution(
            test_case_id=case.id,
            attempt=attempt,
            result="blocked",
            reason=str(exc),
            role=role,
            started_at=started,
            finished_at=utcnow(),
            method="replay",
        )
    healed = False
    final_url = ""
    png = b""
    try:
        scope = Scope(ctx.project.url, ctx.project.scope.include_patterns, ctx.project.scope.exclude_patterns)
        actions = Actions(session, SafetyGuard(ctx.run.mode, ctx.settings["safety"]), scope, UPLOAD_FIXTURE)
        recorder = Recorder(ctx.repo, ctx.run, session, case.id, attempt, scope.host)
        recorder.current_png()
        steps: list[StepResult] = []
        for i, rs in enumerate(script.steps, 1):
            outcome, ok = _replay_step(actions, rs)
            if not ok:
                healed = True
                log.info(
                    "%s: step %d (%s) no longer matches; handing over to the agent", case.id, i, rs.target
                )
                break
            png = recorder.capture(i)
            step = StepResult(
                order=i,
                action=rs.action,
                target=rs.target,
                input=rs.input,
                url=session.current_url,
                observation=outcome.observation[:600],
                result="pass" if outcome.ok else "error",
                screenshot_after=recorder.last_shot,
                locators=rs.locators,
                rect=outcome.rect,
            )
            steps.append(step)
            recorder.note_step(step)
        if not healed:
            actions.observe()
            judgement = _judge(ctx.ai, case, script, actions, png or recorder.current_png())
            final_url = session.current_url
            files = recorder.finish(f"{case.id} · {case.title} (replay)")
    finally:
        session.close()
    if healed:
        healed_run = run_agent_case(ctx, case, attempt)
        healed_run.method = "replay_healed"
        return healed_run
    n = len(steps) + 1
    steps.append(
        StepResult(
            order=n,
            action="assert",
            target="; ".join(script.checks)[:500],
            observation=judgement.actual,
            result="pass" if judgement.result == "pass" else "fail",
            url=final_url,
            screenshot_after=recorder.last_shot,
        )
    )
    return Execution(
        test_case_id=case.id,
        attempt=attempt,
        result=judgement.result,
        method="replay",
        role=role,
        started_at=started,
        finished_at=utcnow(),
        steps=steps,
        failure_step=n if judgement.result == "fail" else None,
        expected=judgement.expected,
        actual=judgement.actual,
        confidence=judgement.confidence,
        reason=f"Replayed {len(script.steps)} recorded actions and re-judged the result.",
        auto_findings=recorder.findings,
        video=files.get("video", ""),
        console_log=files.get("console", ""),
        network_log=files.get("network", ""),
        token_usage=_usage_delta(usage_before, ctx.ai.usage),
    )


def _replay_step(actions: Actions, rs: ReplayStep) -> tuple[Any, bool]:
    if rs.action == "navigate":
        return actions.do_navigate(rs.url or rs.input), True
    if rs.action == "scroll":
        return actions.do_scroll(rs.input or "down"), True
    actions.observe()
    if rs.locators is None:
        return None, False
    el, _strategy = locators.find(actions.session.driver, rs.locators)
    index = el.get_attribute("data-qap-index") if el is not None else None
    if index is None:
        return None, False
    args: dict[str, Any] = {"index": int(index)}
    if rs.action == "type":
        args["text"] = rs.input
    elif rs.action == "select":
        args["option"] = rs.input
    outcome = actions.run(rs.action, args)
    return outcome, outcome.ok or bool(outcome.blocked_reason)


def _judge(ai: Any, case: TestCase, script: ReplayScript, actions: Actions, png: bytes) -> Judgement:
    snap = actions.snapshot
    content = [
        {
            "type": "text",
            "text": f"# Test\n{case.title}\nExpected result: {case.expected_result}\n\n# Checks\n"
            + "\n".join(f"- {c}" for c in script.checks),
        },
        {
            "type": "text",
            "text": "# Final page\n"
            + (snap.outline(120) if snap else "")
            + "\n\nPage text:\n"
            + (snap.text[:2500] if snap else ""),
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(media.model_image(png)).decode("ascii"),
            },
        },
    ]
    return ai.structured(
        system=JUDGE_SYSTEM,
        content=content,
        schema=Judgement,
        purpose="judge replay",
        effort="low",
        max_tokens=4000,
        use_cache=False,
    )
