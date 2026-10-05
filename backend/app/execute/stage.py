"""Stages ⑥ Execute and ⑦ Verify for the approved test cases of a run.

Routing per case:
  requires Full Mode in a Safe Mode run → blocked (reported, not executed)
  rules-based smoke / permission / responsive / accessibility → rule runner (no AI)
  everything else → the browser agent (or a replay of an earlier recording of the same case)
Failures are re-run (default 2×): rule cases by the rule runner, agent cases by replaying the failing trajectory and
re-judging, so reproducibility is measured cheaply. Then bugs are written, de-duplicated and saved.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.ai.client import AIUnavailable, BudgetExceeded
from app.core.logging import get_logger
from app.execute.privacy import privacy_enabled
from app.execute.replayer import replay_case, script_from
from app.execute.rule_runner import RULE_TECHNIQUES, run_rule_case
from app.execute.runner import RunContext, blocked_execution, run_agent_case
from app.explore.stage import FINDINGS_FILE
from app.jobs.run_state import RunCancelled, RunTracker
from app.requirements.stage import REQUIREMENTS_FILE
from app.storage.repository import Repository
from app.storage.schemas import (
    BugsDoc,
    Execution,
    ExecutionsDoc,
    FindingsDoc,
    ReplayScript,
    RequirementsDoc,
    ResultsDoc,
    SiteProfile,
    TestCase,
    TestRunResult,
    TestSuite,
    utcnow,
)
from app.testdesign.stage import TESTCASES_FILE
from app.understand.stage import PROFILE_FILE
from app.verify import bugs as bugbuilder
from app.verify.rule_check import check_rule

log = get_logger("execute")

RESULTS_FILE = "results.json"
BUGS_FILE = "bugs.json"


def expand_viewports(cases: list[TestCase], viewports: list[str]) -> list[TestCase]:
    """Multi-viewport runs: every chosen test also runs at tablet / phone size as its own result
    (`TC-APP-004@mobile`). Responsive and accessibility tests already choose their own sizes."""
    out: list[TestCase] = []
    for case in cases:
        for vp in viewports:
            if vp == "desktop":
                out.append(case)
            elif case.technique not in ("ui_responsive", "accessibility"):
                out.append(
                    case.model_copy(
                        update={"id": f"{case.id}@{vp}", "title": f"{case.title} ({vp})", "viewports": [vp]}
                    )
                )
    return out


def _is_rule_case(case: TestCase) -> bool:
    return case.source == "generated" and case.technique in RULE_TECHNIQUES


def execute_once(ctx: RunContext, case: TestCase, attempt: int) -> Execution:
    if case.requires_full_mode and ctx.run.mode == "safe":
        return blocked_execution(
            case, attempt, "Needs Full Mode (it creates or changes data); this run is in Safe Mode."
        )
    if _is_rule_case(case):
        return run_rule_case(ctx, case, attempt)
    if ctx.ai is None or not ctx.ai.available():
        return blocked_execution(
            case, attempt, "Needs an Anthropic API key (the browser agent runs this test)."
        )
    return run_agent_case(ctx, case, attempt)


def rerun(ctx: RunContext, case: TestCase, first: Execution, attempt: int) -> Execution:
    if _is_rule_case(case) or first.method == "rule":
        return run_rule_case(ctx, case, attempt)
    script = script_from(case, first)
    ctx.repo.save_run_doc(ctx.run, f"replay/{case.id}.json", script)
    return replay_case(ctx, case, script, attempt)


def run_execution(
    repo: Repository,
    tracker: RunTracker,
    ctx: RunContext,
    case_ids: list[str] | None = None,
    resume: bool = False,
    viewports: list[str] | None = None,
) -> ResultsDoc:
    run = tracker.run
    suite = repo.load_run_doc(run, TESTCASES_FILE, TestSuite)
    cases = [c for c in suite.cases if (c.id in case_ids if case_ids else c.status == "approved")]
    cases = expand_viewports(cases, viewports or ["desktop"])
    # Resume: keep first attempts already finished in this execution pass (pass / fail / blocked); errors are retried.
    since = run.options.get("execution_started_at", "")
    if not resume or not since:
        since = utcnow().isoformat()
        run.options["execution_started_at"] = since
    finished: dict[str, Execution] = {}
    if resume:
        for c in cases:
            path = f"executions/{c.id}.json"
            if repo.has_run_doc(run, path):
                first = repo.load_run_doc(run, path, ExecutionsDoc).attempts[0]
                if first.started_at.isoformat() >= since and first.result in ("pass", "fail", "blocked"):
                    finished[c.id] = first
    settings = ctx.settings.get("execute", {})
    workers = max(1, int(settings.get("workers", 2)))
    reruns = max(0, int(settings.get("reruns", 2)))
    results = ResultsDoc(mode=run.mode)
    attempts: dict[str, list[Execution]] = {}
    lock = threading.Lock()
    done = 0
    abort: list[str] = []

    tracker.stage_start(
        "execute",
        f"Running {len(cases)} approved test cases"
        + (f" ({len(finished)} already done)" if finished else ""),
    )
    for case_id, execution in finished.items():
        attempts[case_id] = [execution]
    done = len(finished)

    def save(case: TestCase) -> None:
        repo.save_run_doc(
            run, f"executions/{case.id}.json", ExecutionsDoc(test_case_id=case.id, attempts=attempts[case.id])
        )

    def work(case: TestCase) -> Execution:
        if tracker.cancel_requested.is_set():
            raise RunCancelled()
        tracker.stage_progress(
            "execute", done / max(1, len(cases)), f"▶ {case.id} {case.title}", test_id=case.id
        )
        try:
            return execute_once(ctx, case, 1)
        except RunCancelled:
            raise
        except (AIUnavailable, BudgetExceeded) as exc:
            # No credits / no key / budget spent: every remaining test would fail the same way. Stop the run.
            abort.append(str(exc))
            tracker.cancel_requested.set()
            raise RunCancelled() from exc
        except Exception as exc:  # one broken test must not stop the suite
            log.exception("%s crashed", case.id)
            return Execution(
                test_case_id=case.id,
                result="error",
                reason=f"{type(exc).__name__}: {exc}"[:500],
                finished_at=utcnow(),
            )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qap-test") as pool:
        futures = {pool.submit(work, c): c for c in cases if c.id not in finished}
        for fut in as_completed(futures):
            case = futures[fut]
            try:
                execution = fut.result()
            except RunCancelled:
                if abort:
                    for pending in futures:
                        pending.cancel()
                    if "budget" in abort[0].lower():
                        raise BudgetExceeded(abort[0]) from None
                    raise AIUnavailable(abort[0]) from None
                raise
            with lock:
                attempts[case.id] = [execution]
                done += 1
                save(case)
                if execution.method == "agent" and execution.result == "pass":
                    repo.save_run_doc(run, f"replay/{case.id}.json", script_from(case, execution))
            last = next((s.screenshot_after for s in reversed(execution.steps) if s.screenshot_after), "")
            tracker.stage_progress(
                "execute",
                done / len(cases),
                f"{_icon(execution.result)} {case.id} {case.title}",
                test_id=case.id,
                result=execution.result,
                screenshot=last,
            )
    tracker.stage_done("execute", _summary(attempts))

    # ---------------------------------------------------------------- verify
    tracker.stage_start("verify", "Re-running failures to measure reproducibility")
    failing = [c for c in cases if attempts[c.id][0].result == "fail"]
    for i, case in enumerate(failing):
        for n in range(reruns):
            tracker.stage_progress(
                "verify",
                (i + n / max(1, reruns)) / max(1, len(failing) + 1),
                f"Re-run {n + 2}/{reruns + 1} of {case.id}",
                test_id=case.id,
            )
            try:
                again = rerun(ctx, case, attempts[case.id][0], n + 2)
            except Exception as exc:
                log.warning("re-run of %s failed: %s", case.id, exc)
                again = Execution(test_case_id=case.id, attempt=n + 2, result="error", reason=str(exc)[:300])
            attempts[case.id].append(again)
        save(case)

    if ctx.ai is not None and ctx.ai.available():
        tracker.stage_progress("verify", 0.8, "Recalculating business rules in Python")
        recalculate_rules(repo, ctx, cases, attempts, save)

    by_id = {c.id: c for c in cases}
    for case in cases:
        tries = attempts[case.id]
        first = tries[0]
        fails = sum(1 for t in tries if t.result == "fail")
        final = first.result
        if first.result == "fail" and fails == 1 and len(tries) > 1:
            final = "fail"  # flaky: keep it visible, the bug goes to "Needs review"
        results.results.append(
            TestRunResult(
                test_case_id=case.id,
                title=case.title,
                module=case.module,
                technique=case.technique,
                priority=case.priority,
                role=first.role or case.role,
                result=final,
                method=first.method,
                viewport=case.viewports[0] if "@" in case.id and case.viewports else "desktop",
                reproducibility=f"{fails}/{len(tries)}" if first.result == "fail" else "",
                flaky=first.result == "fail" and len(tries) > 1 and fails < len(tries),
                reason=first.reason,
                duration_ms=sum(
                    int(((t.finished_at or t.started_at) - t.started_at).total_seconds() * 1000)
                    for t in tries
                ),
                cost_usd=round(sum(t.token_usage.cost_usd for t in tries), 4),
            )
        )

    tracker.stage_progress("verify", 0.9, "Writing bug reports")
    failures = [
        bugbuilder.Failure(by_id[r.test_case_id], attempts[r.test_case_id])
        for r in results.results
        if r.result == "fail"
    ]
    drafts: list[bugbuilder.BugDraft] = []
    rule_failures = [f for f in failures if f.first_fail.method == "rule"]
    drafts += bugbuilder.rule_bugs(rule_failures, run)
    for f in failures:
        if f.first_fail.method != "rule":
            try:
                drafts.append(bugbuilder.agent_bug(ctx.ai, f, run))
            except Exception as exc:
                log.warning("bug report for %s failed: %s", f.case.id, exc)
    if repo.has_run_doc(run, FINDINGS_FILE):
        drafts += bugbuilder.finding_bugs(repo.load_run_doc(run, FINDINGS_FILE, FindingsDoc).findings, run)
    drafts = bugbuilder.dedupe(drafts, ctx.ai if ctx.ai is not None and ctx.ai.available() else None)
    bug_list = bugbuilder.finalize(repo, run, drafts, blur=ctx.privacy)
    for bug in bug_list:
        for tc in bug.test_case_ids:
            res = next((r for r in results.results if r.test_case_id == tc), None)
            if res:
                res.bug_ids.append(bug.id)
    results.finished_at = utcnow()
    repo.save_run_doc(run, RESULTS_FILE, results)
    repo.save_run_doc(run, BUGS_FILE, BugsDoc(bugs=bug_list))
    repo.update_run_summary(run.project_slug, run.id, bugs=sum(1 for b in bug_list if b.status != "rejected"))
    from app.verify import store  # local import: store reads this module's file names

    q = store.refresh_quality(repo, run)
    store.permission_matrix(repo, run)
    review = sum(1 for b in bug_list if b.status == "needs_review")
    tracker.stage_done(
        "verify",
        f"{len(bug_list)} bugs ({review} need review) from {len(failures)} failing tests"
        + (f" · quality {q.score:g} ({q.grade})" if q and q.score is not None else ""),
    )
    return results


def recalculate_rules(
    repo: Repository, ctx: RunContext, cases: list[TestCase], attempts: dict[str, list[Execution]], save: Any
) -> None:
    """Layer 3: for tests linked to confirmed rules, re-check the rule in Python from values read off the page."""
    if not repo.has_run_doc(ctx.run, REQUIREMENTS_FILE):
        return
    rules = {
        r.id: r
        for r in repo.load_run_doc(ctx.run, REQUIREMENTS_FILE, RequirementsDoc).rules
        if r.status in ("confirmed", "edited") and r.condition
    }
    for case in cases:
        linked = [rid for rid in case.links.get("rules", []) if rid in rules][:2]
        first = attempts.get(case.id, [None])[0]
        if not linked or first is None or first.method != "agent" or first.result not in ("pass", "fail"):
            continue
        if first.rule_checks:
            continue  # already recalculated (resumed run)
        shot = next((s.screenshot_after for s in reversed(first.steps) if s.screenshot_after), "")
        png = (
            repo.run_path(ctx.run, shot).read_bytes()
            if shot and repo.run_path(ctx.run, shot).exists()
            else None
        )
        for rid in linked:
            rule = rules[rid]
            try:
                check = check_rule(ctx.ai, rid, rule.statement, rule.condition, first.final_page_text, png)
            except Exception as exc:
                log.warning("rule recalculation %s/%s failed: %s", case.id, rid, exc)
                continue
            first.rule_checks.append(check.model_dump())
            if check.holds is False and first.result == "pass":
                values = ", ".join(f"{k}={v:g}" for k, v in check.values.items())
                first.result, first.confidence = "fail", 0.75
                first.reason = f"Python recalculation: {rid} does not hold ({check.expression}; {values})."
                first.expected = first.expected or rule.statement
                first.actual = f"Values on the page: {values}; rule {rid} evaluates to false."
                first.failure_step = len(first.steps)
            elif check.holds is True and first.result == "fail":
                first.confidence = round(
                    first.confidence * 0.6, 2
                )  # the numbers say the rule holds: review it
        save(case)


def _icon(result: str) -> str:
    return {"pass": "✓", "fail": "✗", "blocked": "⊘", "error": "!"}.get(result, "•")


def _summary(attempts: dict[str, list[Execution]]) -> str:
    counts = {
        k: sum(1 for a in attempts.values() if a[0].result == k) for k in ("pass", "fail", "blocked", "error")
    }
    return f"{counts['pass']} passed · {counts['fail']} failed · {counts['blocked']} blocked · {counts['error']} errors"


def load_replay(repo: Repository, ctx: RunContext, case_id: str) -> ReplayScript | None:
    path = f"replay/{case_id}.json"
    return repo.load_run_doc(ctx.run, path, ReplayScript) if repo.has_run_doc(ctx.run, path) else None


def execute_job(repo: Repository, tracker: RunTracker, overrides: dict[str, Any] | None) -> None:
    """Executor target for "Run approved tests"."""
    from app.ai.client import AIClient, AIUnavailable, BudgetExceeded
    from app.core.config import get_settings

    run = tracker.run
    overrides = overrides or {}
    started = time.monotonic()
    try:
        project = repo.get_project(run.project_slug)
        settings = get_settings()
        ai = AIClient(usage=run.token_usage, on_usage=tracker.usage_update) if AIClient.available() else None
        domain = (
            repo.load_run_doc(run, PROFILE_FILE, SiteProfile).domain
            if repo.has_run_doc(run, PROFILE_FILE)
            else ""
        )
        ctx = RunContext(
            repo,
            run,
            project,
            repo.load_secrets(project.slug),
            settings,
            ai,
            headless=overrides.get("headless", settings["browser"]["headless"]),
            privacy=privacy_enabled(project, domain),
        )
        for stage in ("execute", "verify"):
            state = run.stages[stage]
            state.status, state.progress, state.message = "pending", 0.0, ""
            state.started_at = state.finished_at = None
        run.status = "running"
        run.finished_at = None
        tracker.save()
        results = run_execution(
            repo,
            tracker,
            ctx,
            overrides.get("case_ids"),
            resume=bool(overrides.get("resume")),
            viewports=overrides.get("viewports"),
        )
        counts = {
            k: sum(1 for r in results.results if r.result == k) for k in ("pass", "fail", "blocked", "error")
        }
        bugs = repo.load_run_doc(run, BUGS_FILE, BugsDoc).bugs
        tracker.complete(
            f"{counts['pass']} passed · {counts['fail']} failed · {counts['blocked']} blocked · "
            f"{len(bugs)} bugs · {(time.monotonic() - started) / 60:.0f} min"
        )
    except RunCancelled:
        tracker.cancel()
    except (AIUnavailable, BudgetExceeded) as exc:
        tracker.fail(str(exc))
    except Exception as exc:
        log.exception("execution of %s failed", run.id)
        tracker.fail(f"{type(exc).__name__}: {exc}")
