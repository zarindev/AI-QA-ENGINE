"""Plain-English test authoring: "Test that a receptionist cannot delete a doctor" → a structured test case."""

from __future__ import annotations

from typing import Any

from app.requirements.generator import profile_brief
from app.storage.schemas import CrawlResult, SiteProfile, TestCase, TestStep
from app.testdesign.generator import TYPE_FOR, AITestCase
from app.understand import summary as summ

SYSTEM = (
    "You turn a tester's plain-English request into one precise test case for the web application described. "
    "Use the role names and URL templates exactly as given; write concrete steps (screen, field, value, button) and "
    "the expected observation for every checking step. Test data must be fake (names start with QAP_, emails end "
    "with @example.test). Set requires_full_mode to true if the test creates, changes or deletes data. "
    "If the request is ambiguous, choose the most useful interpretation and state your assumption as a precondition."
)


def from_plain_english(
    ai: Any, text: str, crawl: CrawlResult, profile: SiteProfile, role_hint: str = ""
) -> TestCase:
    content = (
        f"# Site profile\n{profile_brief(profile)}\n\n# Screens\n{summ.render(crawl, summ.summarize(crawl))}\n\n"
        f"# Request\n{text.strip()}" + (f"\n(Preferred role: {role_hint})" if role_hint else "")
    )
    c: AITestCase = ai.structured(
        system=SYSTEM,
        content=content,
        schema=AITestCase,
        purpose="plain-English test",
        effort="low",
        max_tokens=8000,
        use_cache=False,
    )
    links = {
        k: v
        for k, v in (
            ("stories", c.story_ids),
            ("rules", c.rule_ids),
            ("workflows", c.workflow_ids),
            ("pages", c.pages),
        )
        if v
    }
    return TestCase(
        id="",
        title=c.title,
        module=c.module or "General",
        technique=c.technique,  # type: ignore[arg-type]
        type=TYPE_FOR[c.technique],
        priority=c.priority,
        role=c.role,
        preconditions=[f"Requested as: “{text.strip()}”", *c.preconditions],
        test_data={p.name: p.value for p in c.test_data},
        steps=[
            TestStep(order=i, action=s.action, data=s.data, expected=s.expected)
            for i, s in enumerate(c.steps, 1)
        ],
        expected_result=c.expected_result,
        links=links,
        source="plain_english",
        requires_full_mode=c.requires_full_mode,
    )
