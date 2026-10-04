"""Stage ④ Requirements: user stories, workflows (state machines) and business rules, reverse-engineered.

Claude is the primary path. Without an API key a transparent fallback derives stories from entities and roles,
workflow states from status dropdowns, and rules from form attributes plus the domain pack (all low confidence).
Every rule starts as `proposed`; only rules the user confirms drive business-rule tests.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.paths import PROMPTS_DIR
from app.storage.schemas import (
    BusinessRule,
    CrawlResult,
    PageRecord,
    RequirementsDoc,
    SiteProfile,
    Transition,
    UserStory,
    Workflow,
    WorkflowStep,
)
from app.understand import summary as summ
from app.understand.packs import get_pack

log = get_logger("requirements")

_INFO_PAGES = re.compile(r"help|terms|policy|faq|guide|about|rules|how it works|pricing", re.I)
_STATUS_LABEL = re.compile(r"\bstatus\b|\bstate\b|\bstage\b", re.I)


# ---------------------------------------------------------------- AI output schema


class AIStory(BaseModel):
    role: str
    feature: str
    module: str
    story: str
    acceptance_criteria: list[str]


class AIStep(BaseModel):
    action: str
    role: str
    page: str
    state_after: str


class AITransition(BaseModel):
    from_state: str
    to_state: str
    action: str
    allowed: bool
    role: str


class AIWorkflow(BaseModel):
    name: str
    entity: str
    description: str
    roles: list[str]
    steps: list[AIStep]
    states: list[str]
    transitions: list[AITransition]


class AIRule(BaseModel):
    statement: str
    condition: str
    category: Literal[
        "calculation", "validation", "permission", "state", "data_integrity", "scheduling", "other"
    ]
    entity: str
    source: str
    confidence: float


class AIRequirements(BaseModel):
    stories: list[AIStory]
    workflows: list[AIWorkflow]
    rules: list[AIRule]


# ---------------------------------------------------------------- context


def info_pages(crawl: CrawlResult, limit_chars: int = 6000) -> str:
    """Full text of help / terms / policy pages: they often state the business rules outright."""
    out, seen, used = [], set(), 0
    for page in crawl.pages:
        name = f"{page.title} {page.url_template} {' '.join(page.headings[:2])}"
        if page.url_template in seen or not _INFO_PAGES.search(name) or (page.status_code or 200) >= 400:
            continue
        seen.add(page.url_template)
        text = page.text_excerpt[:2500]
        out.append(f"### {page.url_template} — {page.title}\n{text}")
        used += len(text)
        if used > limit_chars:
            break
    return "\n\n".join(out)


def profile_brief(profile: SiteProfile) -> str:
    data = {
        "domain": profile.domain,
        "sub_type": profile.sub_type,
        "summary": profile.summary,
        "roles": [{"name": r.name, "description": r.description} for r in profile.role_details]
        or profile.roles,
        "modules": profile.modules,
        "features": [
            {"name": f.name, "module": f.module, "roles": f.roles, "pages": f.pages} for f in profile.features
        ],
        "entities": [
            {
                "name": e.name,
                "fields": [f.model_dump() for f in e.fields],
                "relations": e.relations,
                "operations": e.operations,
                "pages": e.pages,
            }
            for e in profile.entities
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def build_context(crawl: CrawlResult, profile: SiteProfile) -> str:
    pack = get_pack(profile.domain)
    parts = [
        "# Site profile\n" + profile_brief(profile),
        "# Screens\n" + summ.render(crawl, summ.summarize(crawl)),
    ]
    info = info_pages(crawl)
    if info:
        parts.append("# Help, terms and policy pages (full text)\n" + info)
    if pack:
        parts.append(
            "# Domain pack hints (typical for this industry; verify against the screens)\n"
            + pack.prompt_hint()
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------- AI path


def generate_with_ai(ai: Any, crawl: CrawlResult, profile: SiteProfile) -> RequirementsDoc:
    system = (PROMPTS_DIR / "requirements.md").read_text(encoding="utf-8")
    result: AIRequirements = ai.structured(
        system=system,
        content=build_context(crawl, profile),
        schema=AIRequirements,
        purpose="reverse-engineer requirements",
        effort="medium",
        max_tokens=32000,
    )
    doc = RequirementsDoc(method="ai")
    for i, s in enumerate(result.stories, 1):
        doc.stories.append(
            UserStory(
                id=f"US-{i:03d}",
                role=s.role,
                feature=s.feature,
                module=s.module,
                story=s.story,
                acceptance_criteria=s.acceptance_criteria,
            )
        )
    for i, w in enumerate(result.workflows, 1):
        doc.workflows.append(
            Workflow(
                id=f"WF-{i:02d}",
                name=w.name,
                entity=w.entity,
                description=w.description,
                roles=w.roles,
                steps=[
                    WorkflowStep(
                        order=j, action=s.action, role=s.role, page=s.page, state_after=s.state_after
                    )
                    for j, s in enumerate(w.steps, 1)
                ],
                states=w.states,
                transitions=[Transition(**t.model_dump()) for t in w.transitions],
            )
        )
    for i, r in enumerate(result.rules, 1):
        doc.rules.append(
            BusinessRule(
                id=f"BR-{i:03d}",
                statement=r.statement,
                condition=r.condition,
                category=r.category,
                entity=r.entity,
                source=r.source,
                confidence=max(0.0, min(1.0, r.confidence)),
            )
        )
    return doc


# ---------------------------------------------------------------- heuristic fallback


def _entity_for_page(profile: SiteProfile, template: str) -> str:
    for e in profile.entities:
        if template in e.pages:
            return e.name
    return ""


def _status_options(page: PageRecord) -> list[str]:
    for e in page.elements:
        if e.tag == "select" and _STATUS_LABEL.search(f"{e.label} {e.name}") and e.options:
            return [
                o for o in e.options if o.lower() not in ("", "all", "any", "—", "-", "select…", "select...")
            ]
    return []


_VERB = {
    "create": "add new",
    "read": "view",
    "update": "edit",
    "delete": "remove",
    "list": "browse",
    "search": "search",
}


def generate_heuristic(crawl: CrawlResult, profile: SiteProfile) -> RequirementsDoc:
    doc = RequirementsDoc(method="heuristic")
    role_pages: dict[str, set[str]] = {}
    for p in crawl.pages:
        role_pages.setdefault(p.role, set()).add(p.url_template)

    n = 0
    for entity in profile.entities:
        for role in profile.roles:
            if not set(entity.pages) & role_pages.get(role, set()):
                continue
            ops = [op for op in entity.operations if op in _VERB]
            if not ops:
                continue
            n += 1
            verbs = ", ".join(_VERB[o] for o in ops)
            doc.stories.append(
                UserStory(
                    id=f"US-{n:03d}",
                    role=role,
                    feature=f"Manage {entity.name.lower()}s",
                    module=entity.name,
                    story=f"As a {role}, I want to {verbs} {entity.name.lower()} records, so that the information stays current.",
                    acceptance_criteria=[
                        f"The {entity.name.lower()} list loads without errors for the {role} role"
                    ]
                    + [f"Required field “{f.name}” is enforced" for f in entity.fields if f.required][:3],
                )
            )

    w = 0
    for page in crawl.pages:
        states = _status_options(page)
        entity_name = _entity_for_page(profile, page.url_template)
        if len(states) >= 2 and entity_name and not any(wf.entity == entity_name for wf in doc.workflows):
            w += 1
            doc.workflows.append(
                Workflow(
                    id=f"WF-{w:02d}",
                    name=f"{entity_name} lifecycle",
                    entity=entity_name,
                    states=states,
                    description="States read from the status filter; transitions need confirming.",
                    transitions=[
                        Transition(from_state=a, to_state=b, action=f"move to {b}")
                        for a, b in zip(states, states[1:], strict=False)
                    ],
                )
            )

    r = 0
    for entity in profile.entities:
        for f in entity.fields:
            if f.required or f.validation:
                r += 1
                cond = "; ".join(x for x in [("required" if f.required else ""), f.validation] if x)
                doc.rules.append(
                    BusinessRule(
                        id=f"BR-{r:03d}",
                        statement=f"{entity.name} “{f.name}” must satisfy: {cond}",
                        condition=cond,
                        category="validation",
                        entity=entity.name,
                        source=", ".join(entity.pages[:2]),
                        confidence=0.9,
                    )
                )
    pack = get_pack(profile.domain)
    if pack:
        for rule in pack.critical_rules:
            r += 1
            doc.rules.append(
                BusinessRule(
                    id=f"BR-{r:03d}",
                    statement=rule,
                    category="other",
                    source=f"domain pack: {pack.name}",
                    confidence=0.4,
                )
            )
    return doc
