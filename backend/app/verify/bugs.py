"""Stage ⑦ Verify → bugs.json.

* Failing tests become bug reports with every field: steps to reproduce, expected / actual, environment,
  reproducibility (from re-runs), severity + priority with written reasons, confidence, evidence.
* Agent-found failures are written up by Claude (one short call each); rule-runner failures use templates and are
  grouped (e.g. one bug per unprotected page, listing every role that can open it).
* Automatic-check findings from exploration (broken links, JavaScript errors, …) also become bugs.
* De-duplication: identical symptom keys merge; then one Claude pass merges remaining duplicates by root symptom.
* Low confidence or flaky (1/3) → status `needs_review`.
"""

from __future__ import annotations

import json
import platform
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from app.core.logging import get_logger
from app.execute import media
from app.explore import urls
from app.storage.repository import Repository
from app.storage.schemas import (
    Bug,
    BugEnvironment,
    Execution,
    Finding,
    Priority,
    Run,
    Severity,
    TestCase,
)

log = get_logger("verify")

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "trivial": 3}
_MONEY = re.compile(
    r"pay|price|invoice|bill|refund|total|vat|tax|fee|revenue|profit|discount|cost|salary|money|stock", re.I
)
_MEDICAL = re.compile(r"prescri|medic|dosage|diagnos|patient record|allerg", re.I)
_PRIVILEGED = re.compile(r"report|revenue|profit|admin|billing|edit|new|delete|price|user", re.I)


@dataclass
class Failure:
    case: TestCase
    attempts: list[Execution]

    @property
    def first_fail(self) -> Execution:
        return next(a for a in self.attempts if a.result == "fail")

    @property
    def reproducibility(self) -> str:
        return f"{sum(1 for a in self.attempts if a.result == 'fail')}/{len(self.attempts)}"

    @property
    def fail_ratio(self) -> float:
        return sum(1 for a in self.attempts if a.result == "fail") / max(1, len(self.attempts))


@dataclass
class BugDraft:
    bug: Bug
    frames: list[tuple[str, str]] = field(default_factory=list)
    failure_shot: str = ""
    rect: dict[str, float] | None = None


class AIBugReport(BaseModel):
    title: str
    summary: str
    module: str
    category: Literal[
        "calculation",
        "business_rule",
        "permission",
        "validation",
        "data_integrity",
        "state_transition",
        "broken_link",
        "js_error",
        "ui_responsive",
        "accessibility",
        "performance",
        "other",
    ]
    severity: Literal["critical", "major", "minor", "trivial"]
    severity_reason: str
    priority: Literal["P1", "P2", "P3", "P4"]
    preconditions: list[str]
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    symptom_key: str


BUG_SYSTEM = (
    "You are a QA lead writing a bug report developers will act on, from an automated test that failed. Be specific "
    "and factual: quote values, URLs and messages from the evidence; never speculate about code. Title: the defect in "
    "under 90 characters (what is wrong, where). Steps to reproduce: numbered, concrete, minimal, with the test data. "
    "Severity: critical = money/medical/security/data loss or a core workflow broken; major = wrong behaviour of an "
    "important feature, no workaround; minor = validation or UI defect with a workaround; trivial = cosmetic. "
    "Money, medical and permission failures weigh higher. Priority P1–P4 by business impact. symptom_key: a short "
    "kebab-case id of the root symptom (e.g. 'invoice-ignores-insurance-coverage') so duplicates can be merged."
)


def _steps_text(execution: Execution, limit: int = 30) -> str:
    out = []
    for s in execution.steps[:limit]:
        line = f"{s.order}. [{s.result}] {s.action} {s.target} {('← ' + s.input) if s.input else ''} → {s.observation[:220]}"
        out.append(line)
    return "\n".join(out)


def environment(execution: Execution, run: Run, url: str) -> BugEnvironment:
    return BugEnvironment(
        browser=run.options.get("browser", "Chrome"),
        os=f"{platform.system()} {platform.release()}",
        viewport=execution.viewport if execution.viewport != "desktop" else "1440×900 (desktop)",
        url=url,
        role=execution.role or "signed out",
        date_time=(execution.finished_at or execution.started_at).strftime("%Y-%m-%d %H:%M UTC"),
    )


def _confidence(f: Failure) -> float:
    fails = [a for a in f.attempts if a.result == "fail"]
    base = sum(a.confidence for a in fails) / len(fails)
    return round(base * (1.0 if f.fail_ratio >= 0.99 else 0.85 if f.fail_ratio >= 0.6 else 0.55), 2)


def _escalate(sev: Severity, text: str) -> tuple[Severity, str]:
    """Money, medical and permission failures weigh higher (spec ⑦)."""
    if sev in ("minor", "trivial") and (_MONEY.search(text) or _MEDICAL.search(text)):
        return "major", " Raised to major: the defect affects money or medical data."
    return sev, ""


def _failure_evidence(execution: Execution) -> tuple[str, dict[str, float] | None, list[tuple[str, str]]]:
    upto = execution.failure_step or len(execution.steps)
    steps = [s for s in execution.steps if s.order <= upto]
    last = next((s for s in reversed(steps) if s.screenshot_after), None)
    shot = last.screenshot_after if last else ""
    # only a box measured on that very screenshot is meaningful (an earlier step may be another page)
    rect = last.rect if last else None
    frames = [
        (s.screenshot_after, f"{s.order}. {s.action} {s.target}"[:150])
        for s in steps
        if s.screenshot_after and s.action != "assert"
    ]
    if steps and steps[-1].action == "assert" and steps[-1].screenshot_after:
        frames.append(
            (steps[-1].screenshot_after, f"✗ {steps[-1].target[:70]} — saw: {steps[-1].observation[:70]}")
        )
    return shot, rect, frames


# ---------------------------------------------------------------- agent failures


def agent_bug(ai: Any, f: Failure, run: Run) -> BugDraft:
    ex = f.first_fail
    shot, rect, frames = _failure_evidence(ex)
    url = next((s.url for s in reversed(ex.steps) if s.url), "")
    if ai is not None:
        content = (
            f"# Test case {f.case.id}: {f.case.title}\nTechnique: {f.case.technique}  Role: {ex.role or 'signed out'}\n"
            f"Preconditions: {f.case.preconditions}\nTest data: {json.dumps(f.case.test_data, ensure_ascii=False)}\n"
            f"Expected result: {f.case.expected_result}\n\n# Verdict\nExpected: {ex.expected}\nActual: {ex.actual}\n"
            f"Reason: {ex.reason}\nReproducibility: {f.reproducibility}\n\n# Executed steps\n{_steps_text(ex)}"
        )
        r: AIBugReport = ai.structured(
            system=BUG_SYSTEM,
            content=content,
            schema=AIBugReport,
            purpose="write bug report",
            effort="low",
            max_tokens=6000,
        )
        severity, note = _escalate(r.severity, f"{r.title} {r.summary} {f.case.title}")
        bug = Bug(
            id="",
            title=r.title,
            summary=r.summary,
            module=r.module or f.case.module,
            severity=severity,
            severity_reason=r.severity_reason + note,
            priority=r.priority,
            preconditions=r.preconditions,
            steps_to_reproduce=r.steps_to_reproduce,
            expected=r.expected,
            actual=r.actual,
            category=r.category,
            symptom_key=r.symptom_key,
        )
    else:
        severity, note = _escalate("major", f.case.title)
        bug = Bug(
            id="",
            title=f"{f.case.title} — failed",
            summary=ex.reason,
            module=f.case.module,
            severity=severity,
            severity_reason="Default severity (no AI available to assess)." + note,
            priority=f.case.priority,
            preconditions=f.case.preconditions,
            steps_to_reproduce=[
                f"{s.action} {s.target} {s.input}".strip() for s in ex.steps if s.action != "assert"
            ],
            expected=ex.expected or f.case.expected_result,
            actual=ex.actual or ex.reason,
            category=f.case.technique,
            symptom_key=re.sub(r"\W+", "-", f.case.title.lower())[:60],
        )
    bug.confidence = _confidence(f)
    bug.reproducibility = f.reproducibility
    bug.environment = environment(ex, run, url)
    bug.links = {"test_cases": [f.case.id], **{k: v for k, v in f.case.links.items() if k != "pages"}}
    bug.test_case_ids = [f.case.id]
    bug.video = ex.video
    bug.console = [a.detail for a in ex.auto_findings if a.check == "js_error"][:5]
    bug.network = [a.detail for a in ex.auto_findings if a.check == "server_error"][:5]
    return BugDraft(bug, frames, shot, rect)


# ---------------------------------------------------------------- rule-runner failures (grouped, templated)


def rule_bugs(failures: list[Failure], run: Run) -> list[BugDraft]:
    drafts: dict[str, BugDraft] = {}
    for f in failures:
        ex = f.first_fail
        for step in (s for s in ex.steps if s.result == "fail"):
            key, make = _rule_symptom(f.case, step.target, step.observation)
            if key in drafts:
                d = drafts[key]
                if f.case.id not in d.bug.test_case_ids:
                    d.bug.test_case_ids.append(f.case.id)
                    d.bug.links.setdefault("test_cases", []).append(f.case.id)
                role = ex.role or "signed out"
                if role not in d.bug.actual:
                    d.bug.actual += f" Also reproduced as {role}."
                continue
            bug = make(ex.role or "signed out")
            bug.reproducibility = f.reproducibility
            bug.confidence = round(0.92 if f.fail_ratio >= 0.99 else 0.6, 2)
            bug.environment = environment(ex, run, step.url or step.input)
            bug.test_case_ids = [f.case.id]
            bug.links = {"test_cases": [f.case.id]}
            bug.video = ex.video
            bug.console = [a.detail for a in ex.auto_findings if a.check == "js_error"][:5]
            frames = (
                [(step.screenshot_after, f"{step.target}: {step.observation[:100]}")]
                if step.screenshot_after
                else []
            )
            drafts[key] = BugDraft(bug, frames, step.screenshot_after, None)
    return list(drafts.values())


def _rule_symptom(case: TestCase, target: str, observation: str) -> tuple[str, Callable[[str], Bug]]:
    page = target.split(" @ ")[0]
    if case.technique == "permission":

        def make_permission(role: str) -> Bug:
            sev: Severity = "critical" if _PRIVILEGED.search(page) else "major"
            return Bug(
                id="",
                title=f"{role.capitalize()} can open restricted page {page} by direct URL",
                summary=f"{page} is not in the {role} menu, but typing its URL opens it with full content.",
                module=case.module,
                severity=sev,
                priority="P1",
                category="permission",
                severity_reason="Broken access control: a role reaches a screen meant for other roles"
                + (" that exposes privileged data or actions." if sev == "critical" else "."),
                preconditions=[f"Logged in as {role}"],
                steps_to_reproduce=[f"Log in as {role}", f"Open {page} by typing its URL in the address bar"],
                expected="Access is refused (403, redirect or error) for this role.",
                actual=observation,
                symptom_key=f"access:{page}",
            )

        return f"perm:{page}", make_permission
    if case.technique == "ui_responsive":
        width = target.split(" @ ")[1] if " @ " in target else ""

        def make_overflow(role: str) -> Bug:
            return Bug(
                id="",
                title=f"{page} overflows horizontally on small screens",
                module=case.module,
                summary=f"At {width} the page is wider than the screen, so users must scroll sideways.",
                severity="minor",
                priority="P3",
                category="ui_responsive",
                severity_reason="Layout defect on tablet/phone; content is still reachable by scrolling.",
                steps_to_reproduce=[
                    f"Log in as {role}",
                    f"Open {page}",
                    f"Resize the window to {width} wide",
                ],
                expected="The page fits the screen width without horizontal scrolling.",
                actual=observation,
                symptom_key=f"overflow:{page}",
            )

        return f"overflow:{page}", make_overflow
    if case.technique == "accessibility":
        rule = observation.split("(")[0].split(":", 1)[-1].strip()[:80]

        def make_a11y(role: str) -> Bug:
            return Bug(
                id="",
                title=f"Accessibility: {rule} on {page}",
                module="Accessibility",
                summary=f"axe-core reports a critical/serious WCAG violation on {page}.",
                severity="minor",
                priority="P3",
                category="accessibility",
                severity_reason="WCAG 2 A/AA violation that blocks or hinders assistive-technology users.",
                steps_to_reproduce=[
                    f"Log in as {role}",
                    f"Open {page}",
                    "Run an axe-core / Lighthouse accessibility scan",
                ],
                expected="No critical or serious accessibility violations.",
                actual=observation,
                symptom_key=f"a11y:{rule}:{page}",
            )

        return f"a11y:{rule}:{page}", make_a11y

    # smoke
    def make_smoke(role: str) -> Bug:
        js = "JavaScript error" in observation
        http = re.search(r"HTTP (\d{3})", observation)
        sev: Severity = "critical" if http and http.group(1).startswith("5") else "major" if http else "minor"
        title = f"JavaScript error on {page}" if js else f"{page} fails to load ({observation[:40]})"
        return Bug(
            id="",
            title=title,
            module=case.module,
            summary=observation[:300],
            severity=sev,
            priority="P2" if sev != "minor" else "P3",
            category="js_error" if js else "broken_link",
            severity_reason=(
                "Script error breaks part of the page's behaviour." if js else "Page cannot be used."
            ),
            steps_to_reproduce=[
                f"Log in as {role}",
                f"Open {page}",
                "Open the browser console" if js else "Observe the page",
            ],
            expected="The page loads without errors.",
            actual=observation,
            symptom_key=f"smoke:{page}:{observation[:40]}",
        )

    return f"smoke:{page}:{observation[:40]}", make_smoke


# ---------------------------------------------------------------- automatic-check findings from exploration

_FINDING_CATEGORY = {
    "http_error": "broken_link",
    "broken_link": "broken_link",
    "js_error": "js_error",
    "broken_image": "broken_link",
    "failed_request": "other",
    "error_text": "other",
    "horizontal_overflow": "ui_responsive",
    "mixed_content": "other",
    "page_timeout": "performance",
}


def finding_bugs(findings: list[Finding], run: Run) -> list[BugDraft]:
    out = []
    for f in findings:
        if f.severity == "trivial" or f.check not in _FINDING_CATEGORY:
            continue
        pages = f.data.get("pages", [])
        bug = Bug(
            id="",
            title=f"{f.title} — {urls.template(f.page_url)}",
            summary=f.detail[:400],
            module=urls.template(f.page_url).split("/")[1].title() if "/" in f.page_url else "Site",
            severity=f.severity,
            priority="P2" if f.severity in ("critical", "major") else "P3",
            severity_reason="Found by QA Pilot's automatic checks while exploring.",
            category=_FINDING_CATEGORY[f.check],
            source="automatic_check",
            confidence=0.85,
            steps_to_reproduce=[
                f"Log in as {f.role.split(',')[0]}" if f.role and f.role != "public" else "Open the site",
                f"Open {f.page_url}",
            ],
            expected="The page and its resources load without errors.",
            actual=f.detail[:400],
            reproducibility=f"seen on {len(pages) or 1} page(s) / role(s)",
            environment=BugEnvironment(
                browser=run.options.get("browser", "Chrome"),
                url=f.page_url,
                role=f.role,
                os=f"{platform.system()} {platform.release()}",
                viewport="1440×900 (desktop)",
            ),
            symptom_key=f"finding:{f.check}:{f.page_url}",
            links={"findings": [f.id]},
        )
        out.append(BugDraft(bug, [], f.evidence[0] if f.evidence else "", None))
    return out


# ---------------------------------------------------------------- de-duplication


class DedupeGroups(BaseModel):
    groups: list[list[int]]


DEDUPE_SYSTEM = (
    "You merge duplicate bug reports. Two reports are duplicates when they describe the same root defect (same "
    "symptom on the same feature), even if found by different tests or roles. Different pages, different "
    "calculations or different rules are NOT duplicates. Return groups of report numbers; every report must appear "
    "in exactly one group (singletons allowed)."
)


def dedupe(drafts: list[BugDraft], ai: Any) -> list[BugDraft]:
    by_key: dict[str, BugDraft] = {}
    for d in drafts:
        key = d.bug.symptom_key.lower()
        if key in by_key:
            _merge(by_key[key], d)
        else:
            by_key[key] = d
    merged = list(by_key.values())
    if ai is None or len(merged) < 2:
        return merged
    listing = "\n".join(
        f"{i}. [{d.bug.category}] {d.bug.title} — {d.bug.actual[:160]}" for i, d in enumerate(merged)
    )
    try:
        result: DedupeGroups = ai.structured(
            system=DEDUPE_SYSTEM,
            content=listing,
            schema=DedupeGroups,
            purpose="dedupe bugs",
            effort="low",
            max_tokens=4000,
            use_cache=False,
        )
    except Exception as exc:  # de-duplication is an optimisation; keep all bugs if it fails
        log.warning("AI de-duplication failed: %s", exc)
        return merged
    seen: set[int] = set()
    out = []
    for group in result.groups:
        group = [i for i in group if 0 <= i < len(merged) and i not in seen]
        if not group:
            continue
        seen.update(group)
        keeper = max(
            (merged[i] for i in group),
            key=lambda d: (d.bug.source == "test", -SEVERITY_ORDER[d.bug.severity]),
        )
        for i in group:
            if merged[i] is not keeper:
                _merge(keeper, merged[i])
        out.append(keeper)
    out += [d for i, d in enumerate(merged) if i not in seen]
    return out


def _merge(keeper: BugDraft, other: BugDraft) -> None:
    for tc in other.bug.test_case_ids:
        if tc not in keeper.bug.test_case_ids:
            keeper.bug.test_case_ids.append(tc)
            keeper.bug.links.setdefault("test_cases", []).append(tc)
    for k, v in other.bug.links.items():
        for item in v:
            if item not in keeper.bug.links.setdefault(k, []):
                keeper.bug.links[k].append(item)
    if SEVERITY_ORDER[other.bug.severity] < SEVERITY_ORDER[keeper.bug.severity]:
        keeper.bug.severity = other.bug.severity
        keeper.bug.severity_reason += (
            f" Raised to {other.bug.severity}: the same symptom was also found "
            f"{'by the automatic checks' if other.bug.source == 'automatic_check' else 'by another test'}."
        )
    keeper.bug.confidence = max(keeper.bug.confidence, other.bug.confidence)


# ---------------------------------------------------------------- evidence + final assembly


def finalize(repo: Repository, run: Run, drafts: list[BugDraft], viewport_width: int = 1440) -> list[Bug]:
    drafts.sort(key=lambda d: (SEVERITY_ORDER[d.bug.severity], d.bug.priority, d.bug.title))
    bugs = []
    for i, d in enumerate(drafts, 1):
        bug = d.bug
        bug.id = f"BUG-{i:03d}"
        if d.failure_shot and repo.run_path(run, d.failure_shot).exists():
            bug.screenshot = d.failure_shot
            caption = (
                f"{bug.id}: expected {textwrap.shorten(bug.expected, 90, placeholder='…')} — "
                f"actual {textwrap.shorten(bug.actual, 110, placeholder='…')}"
            )
            png = media.annotate(
                repo.run_path(run, d.failure_shot).read_bytes(), d.rect, caption, viewport_width
            )
            rel = f"artifacts/bugs/{bug.id}/annotated.png"
            repo.write_bytes(repo.run_path(run, rel), png)
            bug.annotated_screenshot = rel
            frames = [(repo.run_path(run, p), c) for p, c in d.frames if p]
            clip = media.build_clip(
                frames, repo.run_path(run, rel), repo.run_path(run, f"artifacts/bugs/{bug.id}/clip.mp4")
            )
            if clip:
                bug.clip = f"artifacts/bugs/{bug.id}/clip.mp4"
        bug.evidence = [p for p in (bug.annotated_screenshot, bug.screenshot, bug.clip, bug.video) if p]
        flaky = bug.reproducibility.startswith("1/") and not bug.reproducibility.endswith("/1")
        bug.status = "needs_review" if (bug.confidence < 0.6 or flaky) else "new"
        bug.priority = _priority(bug)
        bugs.append(bug)
    return bugs


def _priority(bug: Bug) -> Priority:
    floor: dict[str, Priority] = {"critical": "P1", "major": "P2", "minor": "P3", "trivial": "P4"}
    return min(bug.priority, floor[bug.severity])  # never lower than the severity implies
