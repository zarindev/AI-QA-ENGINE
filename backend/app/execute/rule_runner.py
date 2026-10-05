"""Deterministic execution for the rules-based techniques that need no judgement (and no AI cost):

* smoke          — every page loads: HTTP < 400, no login wall, no error text, no JavaScript errors
* permission     — the page must NOT be usable by this role (403 / redirect / login / denial message = pass)
* ui_responsive  — no horizontal overflow at tablet (768) and phone (390) widths
* accessibility  — axe-core: no critical or serious WCAG 2 A/AA violations
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import axe_selenium_python
from selenium.common.exceptions import WebDriverException

from app.browser import auth
from app.browser.dom_snapshot import take_snapshot
from app.browser.driver import BrowserSession, NavigationResult
from app.execute.recorder import Recorder
from app.execute.runner import VIEWPORTS, LoginFailed, RunContext, open_session, resolve_role
from app.explore import urls
from app.explore.checks import _ERROR_PAGE_PATTERNS
from app.storage.schemas import Execution, ResultKind, StepResult, TestCase, utcnow

RULE_TECHNIQUES = ("smoke", "permission", "ui_responsive", "accessibility")
AXE_JS = (Path(axe_selenium_python.__file__).parent / "node_modules" / "axe-core" / "axe.min.js").read_text(
    encoding="utf-8"
)
_DENIED = re.compile(
    r"\b(403|forbidden|not authori[sz]ed|unauthori[sz]ed|access denied|permission|"
    r"not allowed|no access|sign in|log in)\b",
    re.I,
)


def _urls(case: TestCase) -> list[str]:
    return [s.data for s in case.steps if s.data.startswith(("http://", "https://"))]


def run_rule_case(ctx: RunContext, case: TestCase, attempt: int) -> Execution:
    role = resolve_role(ctx.project, case.role) or ("public" if case.role == "public" else "")
    started = utcnow()
    viewports = [v for v in case.viewports if v in VIEWPORTS] or ["desktop"]
    w, h = VIEWPORTS[viewports[0]]
    try:
        session, _ = open_session(ctx, role, w, h)
    except LoginFailed as exc:
        return Execution(
            test_case_id=case.id,
            attempt=attempt,
            result="blocked",
            reason=str(exc),
            role=role,
            started_at=started,
            finished_at=utcnow(),
            method="rule",
        )
    recorder = Recorder(ctx.repo, ctx.run, session, case.id, attempt, urls.Scope(ctx.project.url).host)
    steps: list[StepResult] = []
    try:
        runner = {
            "smoke": _smoke,
            "permission": _permission,
            "ui_responsive": _responsive,
            "accessibility": _a11y,
        }[case.technique]
        runner(ctx, session, recorder, case, steps, viewports)
        files = recorder.finish(f"{case.id} · {case.title}", blur=ctx.privacy)
    finally:
        session.close()
    failed = [s for s in steps if s.result == "fail"]
    result: ResultKind = "fail" if failed else "pass"
    return Execution(
        test_case_id=case.id,
        attempt=attempt,
        result=result,
        method="rule",
        role=role,
        started_at=started,
        finished_at=utcnow(),
        steps=steps,
        failure_step=failed[0].order if failed else None,
        confidence=0.9,
        reason=(
            f"{len(failed)} of {len(steps)} checks failed" if failed else f"All {len(steps)} checks passed"
        ),
        expected=case.expected_result,
        actual="; ".join(f"{s.target}: {s.observation}" for s in failed[:5]) if failed else "As expected",
        auto_findings=recorder.findings,
        video=files.get("video", ""),
        console_log=files.get("console", ""),
        network_log=files.get("network", ""),
        viewport=",".join(viewports),
    )


def _visit(
    session: BrowserSession, recorder: Recorder, steps: list[StepResult], url: str
) -> tuple[StepResult, NavigationResult]:
    n = len(steps) + 1
    before = recorder.last_shot
    nav = session.navigate(url)
    recorder.capture(n)
    step = StepResult(
        order=n,
        action="navigate",
        target=urls.template(url),
        input=url,
        url=session.current_url,
        screenshot_before=before,
        screenshot_after=recorder.last_shot,
    )
    steps.append(step)
    return step, nav


def _smoke(ctx, session, recorder, case, steps, _viewports) -> None:
    for url in _urls(case):
        js_before = len([f for f in recorder.findings if f.check == "js_error"])
        step, nav = _visit(session, recorder, steps, url)
        snap = take_snapshot(session.driver)
        text = f"{snap.title}\n{snap.text}"
        problems = []
        if nav.status_code and nav.status_code >= 400:
            problems.append(f"HTTP {nav.status_code}")
        if auth.find_login_form(snap) and case.role != "public":
            problems.append("redirected to the login page")
        for pattern, _sev in _ERROR_PAGE_PATTERNS:
            m = pattern.search(text)
            if m:
                problems.append(f"error text “{m.group(0)[:40]}”")
                break
        new_js = [f for f in recorder.findings if f.check == "js_error"][js_before:]
        if new_js:
            problems.append(f"JavaScript error: {new_js[0].detail[:160]}")
        step.result = "fail" if problems else "pass"
        step.observation = (
            "; ".join(problems) if problems else f"Loaded “{snap.title}” (HTTP {nav.status_code or '—'})"
        )
        recorder.note_step(step)


def _permission(ctx, session, recorder, case, steps, _viewports) -> None:
    for url in _urls(case):
        target = urls.template(url)
        step, nav = _visit(session, recorder, steps, url)
        snap = take_snapshot(session.driver)
        final = urls.template(session.current_url)
        status = nav.status_code or 200
        login_wall = auth.find_login_form(snap) is not None
        denial = bool(_DENIED.search(f"{snap.title} {' '.join(snap.headings)}"))
        redirected = final != target
        if status in (401, 403, 404) or login_wall or redirected or denial:
            why = (
                f"HTTP {status}"
                if status in (401, 403, 404)
                else (
                    "login page shown"
                    if login_wall
                    else f"redirected to {final}" if redirected else "access-denied message"
                )
            )
            step.result, step.observation = "pass", f"Access refused ({why})."
        else:
            step.result = "fail"
            step.observation = (
                f"The page opened for {case.role or 'a signed-out visitor'}: HTTP {status}, "
                f"title “{snap.title}”, headings: {' | '.join(snap.headings[:3]) or '—'}"
            )
        recorder.note_step(step)


def _responsive(ctx, session, recorder, case, steps, viewports) -> None:
    for vp in viewports:
        w, h = VIEWPORTS[vp]
        session.set_viewport(w, h)
        for url in _urls(case):
            step, _ = _visit(session, recorder, steps, url)
            step.target = f"{step.target} @ {w}px"
            snap = take_snapshot(session.driver)
            if snap.overflow_x > 4:
                step.result = "fail"
                step.observation = (
                    f"Content is {snap.overflow_x}px wider than the {w}px screen (horizontal scrolling)."
                )
            else:
                step.result, step.observation = "pass", f"Fits the {w}px screen."
            recorder.note_step(step)


def _a11y(ctx, session, recorder, case, steps, _viewports) -> None:
    for url in _urls(case):
        step, _ = _visit(session, recorder, steps, url)
        try:
            session.driver.execute_script(AXE_JS)
            session.driver.set_script_timeout(60)
            result = session.driver.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                "axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa']}, resultTypes: ['violations']})"
                ".then(r => done(r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,"
                " targets: v.nodes.slice(0, 3).map(n => n.target.join(' '))})))).catch(e => done({error: String(e)}));"
            )
        except WebDriverException as exc:
            step.result, step.observation = "error", f"axe-core could not run: {(exc.msg or '')[:120]}"
            continue
        finally:
            session.driver.set_script_timeout(20)
        if isinstance(result, dict) and result.get("error"):
            step.result, step.observation = "error", result["error"][:200]
            continue
        serious = [v for v in result if v.get("impact") in ("critical", "serious")]
        step.result = "fail" if serious else "pass"
        step.observation = (
            "; ".join(
                f"{v['impact']}: {v['help']} ({v['nodes']}×, e.g. {v['targets'][0] if v['targets'] else '?'})"
                for v in serious[:5]
            )
            if serious
            else f"No critical/serious violations ({len(result)} minor/moderate)."
        )
        step.input = json.dumps(result)[:4000]
        recorder.note_step(step)
