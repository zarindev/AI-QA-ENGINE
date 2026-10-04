"""The test agent: observe → decide → act, one browser action per Claude turn.

Each turn is a single, self-contained request (no growing transcript): the test case sits in a cached block,
followed by a compact history of what was done, the current page's indexed elements and a screenshot. That keeps
every turn at a predictable ~5k input tokens and lets prompt caching serve the test case after the first turn.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.paths import PROMPTS_DIR
from app.execute import media
from app.execute.actions import Actions, Outcome
from app.execute.recorder import Recorder
from app.storage.schemas import ResultKind, StepResult, TestCase

log = get_logger("agent")


NOTE = {
    "type": "string",
    "description": "Your working memory, 1–2 sentences: what you have established so far and what you will do next. "
    "You only see these notes from earlier turns, so keep track of ids, values and progress here.",
}


def _tool(name: str, description: str, props: dict[str, Any]) -> dict[str, Any]:
    props = {"note": NOTE, **props}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


INDEX = {"type": "integer", "description": "Element index from the list, e.g. 12 for [12]"}
TOOLS = [
    _tool("click", "Click an element (link, button, checkbox label…).", {"index": INDEX}),
    _tool(
        "type",
        "Type text into an input or textarea. For date inputs use YYYY-MM-DD, for time HH:MM.",
        {
            "index": INDEX,
            "text": {"type": "string"},
            "clear": {"type": "boolean", "description": "Clear the field first"},
        },
    ),
    _tool(
        "select",
        "Choose an option in a dropdown by its visible text.",
        {"index": INDEX, "option": {"type": "string"}},
    ),
    _tool("check", "Tick or untick a checkbox / radio.", {"index": INDEX, "checked": {"type": "boolean"}}),
    _tool("upload", "Attach QA Pilot's harmless test file to a file input.", {"index": INDEX}),
    _tool(
        "navigate",
        "Open a URL of the site under test (absolute, or a path like /patients/3).",
        {"url": {"type": "string"}},
    ),
    _tool("scroll", "Scroll the page.", {"direction": {"type": "string", "enum": ["up", "down"]}}),
    _tool(
        "wait_for",
        "Wait until some text appears on the page.",
        {"text": {"type": "string"}, "seconds": {"type": "number"}},
    ),
    _tool("read", "Read the full text or value of an element.", {"index": INDEX}),
    _tool(
        "assert",
        "Record one check of an expected result from the test.",
        {
            "index": {
                "type": "integer",
                "description": "Element that shows the observed value (e.g. the total cell), or -1 if none",
            },
            "check": {"type": "string", "description": "What should be true"},
            "observed": {"type": "string", "description": "What you actually see, quoting values"},
            "passed": {"type": "boolean"},
        },
    ),
    _tool(
        "finish",
        "End the test with a verdict.",
        {
            "result": {"type": "string", "enum": ["pass", "fail", "blocked"]},
            "reason": {"type": "string", "description": "One sentence"},
            "expected": {"type": "string"},
            "actual": {"type": "string"},
            "confidence": {"type": "number", "description": "0 to 1"},
        },
    ),
]


@dataclass
class Limits:
    max_steps: int = 35
    max_seconds: int = 600
    max_tokens: int = 160_000  # uncached tokens only; cache reads cost a tenth and would inflate the count
    max_cost_usd: float = 0.80


@dataclass
class Verdict:
    result: ResultKind = "error"
    reason: str = ""
    expected: str = ""
    actual: str = ""
    confidence: float = 0.5
    failure_step: int | None = None
    steps: list[StepResult] = field(default_factory=list)


def case_brief(case: TestCase, role: str, start_url: str) -> str:
    data = {
        "id": case.id,
        "title": case.title,
        "technique": case.technique,
        "role": role or "signed out",
        "preconditions": case.preconditions,
        "test_data": case.test_data,
        "steps": [
            {"n": s.order, "action": s.action, "data": s.data, "expected": s.expected} for s in case.steps
        ],
        "expected_result": case.expected_result,
    }
    return (
        f"# Test case\n{json.dumps(data, ensure_ascii=False, indent=1)}\n\nSite under test: {start_url}\n"
        f"You are {'logged in as ' + role if role and role != 'public' else 'not logged in'}."
    )


class TestAgent:
    __test__ = False

    def __init__(
        self,
        ai: Any,
        actions: Actions,
        recorder: Recorder,
        case: TestCase,
        role: str,
        start_url: str,
        limits: Limits | None = None,
        effort: str = "low",
    ) -> None:
        self.ai = ai
        self.actions = actions
        self.recorder = recorder
        self.case = case
        self.role = role
        self.start_url = start_url
        self.limits = limits or Limits()
        self.effort = effort
        self.system = (PROMPTS_DIR / "agent.md").read_text(encoding="utf-8")
        self.brief = case_brief(case, role, start_url)
        self.history: list[str] = []
        self.recent: list[str] = []
        self.notes: list[str] = []

    def _history_text(self) -> str:
        if not self.history:
            return "Nothing done yet — start with the first step."
        lines = self.history[-14:]
        skipped = len(self.history) - len(lines)
        return ("(earlier steps omitted)\n" if skipped else "") + "\n".join(lines)

    def _turn(self, png: bytes, nudge: str = "") -> Any:
        snap = self.actions.snapshot
        page = snap.outline(max_elements=180) if snap else "(no page)"
        jpeg = base64.standard_b64encode(media.model_image(png)).decode("ascii")
        content = [
            {"type": "text", "text": self.brief, "cache_control": {"type": "ephemeral"}},
            {
                "type": "text",
                "text": f"# Done so far\n{self._history_text()}\n\n# Current page\n{page}{nudge}",
            },
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg}},
        ]
        return self.ai.messages(
            system=self.system,
            messages=[{"role": "user", "content": content}],
            tools=TOOLS,
            effort=self.effort,
            max_tokens=4000,
        )

    def run(self) -> Verdict:
        verdict = Verdict()
        started = time.monotonic()
        start = self.ai.usage.model_copy()
        nudge = ""
        png = self.recorder.current_png()
        while True:
            if len(verdict.steps) >= self.limits.max_steps:
                return self._stop(
                    verdict,
                    "error",
                    f"Step limit ({self.limits.max_steps}) reached before the test finished.",
                )
            if time.monotonic() - started > self.limits.max_seconds:
                return self._stop(verdict, "error", f"Time limit ({self.limits.max_seconds}s) reached.")
            used = self.ai.usage
            uncached = (used.input_tokens + used.output_tokens + used.cache_write_tokens) - (
                start.input_tokens + start.output_tokens + start.cache_write_tokens
            )
            if uncached > self.limits.max_tokens or used.cost_usd - start.cost_usd > self.limits.max_cost_usd:
                return self._stop(verdict, "error", "Token/cost limit for this test reached.")
            self.actions.observe()
            response = self._turn(png, nudge)
            call = next((b for b in response.content if getattr(b, "type", "") == "tool_use"), None)
            if call is None:
                nudge = "\n\nYou must call exactly one tool now."
                verdict.steps.append(
                    StepResult(
                        order=len(verdict.steps) + 1,
                        action="(no action)",
                        result="error",
                        observation="The agent answered without choosing an action.",
                    )
                )
                continue
            nudge = ""
            name, args = call.name, dict(call.input)
            note = str(args.pop("note", "")).strip()
            n = len(verdict.steps) + 1
            self.notes.append(note)
            if name == "finish":
                result = args.get("result", "error")
                verdict.result = result if result in ("pass", "fail", "blocked") else "error"
                verdict.reason = args.get("reason", "")
                verdict.expected = args.get("expected", "")
                verdict.actual = args.get("actual", "")
                verdict.confidence = float(args.get("confidence", 0.5))
                if verdict.result == "fail" and verdict.failure_step is None:
                    verdict.failure_step = n - 1 if n > 1 else None
                return verdict
            if name == "assert":
                passed = bool(args.get("passed"))
                rect, evidence = None, None
                index = int(args.get("index", -1))
                if (
                    index >= 0
                ):  # point at the evidence: scroll to it, then screenshot there so the box matches
                    seen = self.actions.do_read(index)
                    rect, evidence = seen.rect, seen.element
                    png = self.recorder.capture(n)
                step = StepResult(
                    order=n,
                    action="assert",
                    target=args.get("check", ""),
                    observation=args.get("observed", ""),
                    result="pass" if passed else "fail",
                    url=self.actions.session.current_url,
                    screenshot_before=self.recorder.last_shot,
                    screenshot_after=self.recorder.last_shot,
                    rect=rect,
                    locators=evidence.locators if evidence else None,
                )
                verdict.steps.append(step)
                if not passed and verdict.failure_step is None:
                    verdict.failure_step = n
                self.history.append(
                    f"{n}. ASSERT {'✓' if passed else '✗'} {args.get('check', '')} — saw: {args.get('observed', '')}"
                    + (f"\n   note: {note}" if note else "")
                )
                continue
            before = self.recorder.last_shot
            t0 = time.monotonic()
            outcome: Outcome = self.actions.run(name, args)
            png = self.recorder.capture(n)
            step = StepResult(
                order=n,
                action=name,
                target=outcome.element.describe() if outcome.element else str(args.get("url", "")),
                input=str(args.get("text") or args.get("option") or args.get("url") or ""),
                observation=outcome.observation[:600],
                result="pass" if outcome.ok else "error",
                url=self.actions.session.current_url,
                screenshot_before=before,
                screenshot_after=self.recorder.last_shot,
                duration_ms=int((time.monotonic() - t0) * 1000),
                locators=outcome.element.locators if outcome.element else None,
                rect=outcome.rect,
                blocked_reason=outcome.blocked_reason,
            )
            if outcome.blocked_reason:
                step.result = "blocked"
            verdict.steps.append(step)
            self.recorder.note_step(step)
            args_text = ", ".join(f"{k}={v!r}" for k, v in args.items())
            self.history.append(
                f"{n}. {name}({args_text}) → {outcome.observation[:300]}"
                + (f"\n   note: {note}" if note else "")
            )
            signature = f"{name}({args_text})"
            self.recent.append(signature)
            if self.recent[-6:].count(signature) >= 3:
                nudge = (
                    "\n\nYou have repeated the same action several times without progress. Try a different "
                    "approach (another element, the select tool, reloading), or finish with a verdict."
                )

    def _stop(self, verdict: Verdict, result: ResultKind, reason: str) -> Verdict:
        verdict.result, verdict.reason, verdict.confidence = result, reason, 0.3
        return verdict
