"""Stage ⑤ Test design: rules-based cases + Claude-designed cases → one reviewed suite (testcases.json).

Regeneration keeps every case a person approved, edited or wrote, and replaces the rest. Ids are
`TC-<MOD>-NNN`, where MOD is a short code for the module (PAT for Patient, BIL for Billing…).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.paths import PROMPTS_DIR
from app.requirements.generator import profile_brief
from app.storage.schemas import (
    CrawlResult,
    RequirementsDoc,
    SiteProfile,
    TestCase,
    TestStep,
    TestSuite,
)
from app.testdesign.rules_based import Draft, RulesBasedDesigner
from app.understand import summary as summ
from app.understand.classifier import singular
from app.understand.packs import get_pack

log = get_logger("design")


# ---------------------------------------------------------------- AI schema


class AIParam(BaseModel):
    name: str
    value: str


class AIStep(BaseModel):
    action: str
    data: str
    expected: str


class AITestCase(BaseModel):
    title: str
    module: str
    technique: Literal[
        "e2e",
        "state_transition",
        "business_rule",
        "data_integrity",
        "negative",
        "validation",
        "permission",
        "crud",
        "boundary",
    ]
    priority: Literal["P1", "P2", "P3", "P4"]
    role: str
    preconditions: list[str]
    test_data: list[AIParam]
    steps: list[AIStep]
    expected_result: str
    story_ids: list[str]
    rule_ids: list[str]
    workflow_ids: list[str]
    pages: list[str]
    requires_full_mode: bool


class AISuite(BaseModel):
    cases: list[AITestCase]


CaseType = Literal["functional", "negative", "security", "ui", "accessibility", "performance"]
TYPE_FOR: dict[str, CaseType] = {
    "e2e": "functional",
    "state_transition": "functional",
    "business_rule": "functional",
    "data_integrity": "functional",
    "negative": "negative",
    "validation": "negative",
    "permission": "security",
    "crud": "functional",
    "boundary": "negative",
}


def _ai_context(crawl: CrawlResult, profile: SiteProfile, req: RequirementsDoc, existing: list[Draft]) -> str:
    confirmed = [r for r in req.rules if r.status in ("confirmed", "edited")]
    parts = [
        "# Site profile\n" + profile_brief(profile),
        "# Screens\n" + summ.render(crawl, summ.summarize(crawl)),
        "# User stories\n"
        + json.dumps(
            [
                s.model_dump(include={"id", "role", "story", "acceptance_criteria"})
                for s in req.stories
                if s.status != "rejected"
            ],
            ensure_ascii=False,
        ),
        "# Workflows\n" + json.dumps([w.model_dump() for w in req.workflows], ensure_ascii=False),
        "# CONFIRMED business rules (design business_rule cases only for these)\n"
        + (
            json.dumps(
                [
                    r.model_dump(include={"id", "statement", "condition", "category", "entity"})
                    for r in confirmed
                ],
                ensure_ascii=False,
            )
            if confirmed
            else "None confirmed yet — do not design business_rule cases."
        ),
        "# Cases the rules-based generator already wrote (do not duplicate)\n"
        + "\n".join(f"- [{d.case.technique}] {d.case.title}" for d in existing),
    ]
    pack = get_pack(profile.domain)
    if pack:
        parts.append("# Typical edge cases in this industry\n" + "; ".join(pack.edge_cases))
    return "\n\n".join(parts)


def ai_cases(
    ai: Any, crawl: CrawlResult, profile: SiteProfile, req: RequirementsDoc, existing: list[Draft]
) -> list[Draft]:
    system = (PROMPTS_DIR / "test_design.md").read_text(encoding="utf-8")
    suite: AISuite = ai.structured(
        system=system,
        content=_ai_context(crawl, profile, req, existing),
        schema=AISuite,
        purpose="design test cases",
        effort="medium",
        max_tokens=48000,
    )
    out = []
    for c in suite.cases:
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
        out.append(
            Draft(
                TestCase(
                    id="",
                    title=c.title,
                    module=c.module,
                    technique=c.technique,
                    type=TYPE_FOR[c.technique],  # type: ignore[arg-type]
                    priority=c.priority,
                    role=c.role,
                    preconditions=c.preconditions,
                    test_data={p.name: p.value for p in c.test_data},
                    steps=[
                        TestStep(order=i, action=s.action, data=s.data, expected=s.expected)
                        for i, s in enumerate(c.steps, 1)
                    ],
                    expected_result=c.expected_result,
                    links=links,
                    source="ai",
                    requires_full_mode=c.requires_full_mode,
                ),
                module=c.module or "General",
                key=f"ai:{c.technique}:{c.title.lower()}",
            )
        )
    return out


# ---------------------------------------------------------------- assembly


# Modules created by the rules-based designer itself get fixed, readable codes.
FIXED_CODES = {"Accessibility": "A11Y", "Access": "ACC", "UI": "UI", "Smoke": "SMK"}


def module_code(name: str, taken: dict[str, str]) -> str:
    """Stable 3–4 letter code per module name; collisions get a digit."""
    if name in taken:
        return taken[name]
    if name in FIXED_CODES and FIXED_CODES[name] not in taken.values():
        taken[name] = FIXED_CODES[name]
        return taken[name]
    words = re.findall(r"[A-Za-z]+", name) or ["GEN"]
    base = (words[0][:3] if len(words) == 1 else "".join(w[0] for w in words[:3]) + words[-1][1:2]).upper()
    base = base.ljust(3, "X")[:4]
    code, n = base, 2
    used = set(taken.values())
    while code in used:
        code, n = f"{base[:3]}{n}", n + 1
    taken[name] = code
    return code


_P1_WORDS = re.compile(
    r"pay|price|invoice|bill|refund|total|vat|tax|fee|revenue|profit|discount|money|"
    r"prescri|medic|dosage|permission|cannot open|direct url|another user",
    re.I,
)


def assign_priority(case: TestCase) -> None:
    """Rules-based cases get a sensible default; money, medical and permission cases are raised to P1."""
    if case.source == "generated" and _P1_WORDS.search(f"{case.title} {case.expected_result}"):
        if case.technique in ("permission", "crud", "business_rule", "e2e"):
            case.priority = "P1"


def _module_key(name: str) -> str:
    return " ".join(singular(w) for w in name.lower().split())


def assemble(drafts: list[Draft], keep: list[TestCase]) -> TestSuite:
    """Give ids to new drafts, keep reviewed cases as they are, and drop near-duplicates."""
    codes: dict[str, str] = {}
    counters: dict[str, int] = {}
    for case in keep:
        m = re.match(r"TC-([A-Z0-9]+)-(\d+)$", case.id)
        if m:
            counters[m.group(1)] = max(counters.get(m.group(1), 0), int(m.group(2)))
            codes.setdefault(case.module, m.group(1))
    kept_titles = {c.title.lower() for c in keep}
    # "Appointments" (Claude) and "Appointment" (rules-based) are one module: same code, same group.
    canonical: dict[str, str] = {}
    for c in keep:
        canonical.setdefault(_module_key(c.module), c.module)
    cases = list(keep)
    seen_keys: set[str] = set()
    for d in drafts:
        if d.key in seen_keys or d.case.title.lower() in kept_titles:
            continue
        seen_keys.add(d.key)
        case = d.case
        name = case.module or d.module
        case.module = canonical.setdefault(_module_key(name), name)
        code = module_code(case.module, codes)
        counters[code] = counters.get(code, 0) + 1
        case.id = f"TC-{code}-{counters[code]:03d}"
        assign_priority(case)
        cases.append(case)
    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    cases.sort(key=lambda c: (c.module, order[c.priority], c.id))
    return TestSuite(cases=cases)


def design(
    crawl: CrawlResult,
    profile: SiteProfile,
    req: RequirementsDoc,
    ai: Any = None,
    previous: TestSuite | None = None,
) -> TestSuite:
    keep = [
        c
        for c in (previous.cases if previous else [])
        if c.edited or c.status != "draft" or c.source in ("user", "plain_english")
    ]
    drafts = RulesBasedDesigner(crawl, profile).all()
    if ai is not None and ai.available():
        drafts += ai_cases(ai, crawl, profile, req, drafts)
    return assemble(drafts, keep)


# ---------------------------------------------------------------- estimate


class Estimate(BaseModel):
    cases: int
    steps: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    minutes: float
    blocked_in_safe_mode: int


def estimate(cases: list[TestCase], model_price: tuple[float, float], safe_mode: bool = False) -> Estimate:
    """Rough budget for running cases with the browser agent: each step is one Claude turn with a screenshot and
    the page's element list (~4.5k input tokens, ~350 output), ~9 s of browser time, plus 30 % for re-runs."""
    runnable = [c for c in cases if not (safe_mode and c.requires_full_mode)]
    steps = sum(max(2, len(c.steps)) * len(c.viewports) for c in runnable)
    turns = int(steps * 1.3)
    inp, out = turns * 4500, turns * 350
    cost = (inp * model_price[0] + out * model_price[1]) / 1e6
    return Estimate(
        cases=len(runnable),
        steps=steps,
        input_tokens=inp,
        output_tokens=out,
        cost_usd=round(cost, 2),
        minutes=round(turns * 9 / 60, 1),
        blocked_in_safe_mode=len(cases) - len(runnable),
    )
