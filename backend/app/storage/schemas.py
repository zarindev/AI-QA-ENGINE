"""Pydantic v2 models for every file QA Pilot writes. See docs/STORAGE.md for the on-disk layout.

Top-level documents (one JSON file each) inherit `Document` and carry `schema_version`.
Paths stored in these models are always relative to the run (or project) folder, with forward slashes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Document(Model):
    schema_version: int = SCHEMA_VERSION


# --------------------------------------------------------------------------- project

Environment = Literal["production", "staging", "test"]
RunMode = Literal["safe", "full"]


class Role(Model):
    name: str
    login_strategy: Literal["credentials", "manual_session", "none"] = "credentials"
    secret_ref: str = ""  # key inside secrets.enc; never the secret itself
    login_url: str = ""
    description: str = ""


class Scope(Model):
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_pages: int = 40
    max_depth: int = 4
    viewports: list[str] = Field(default_factory=lambda: ["desktop"])


class Project(Document):
    slug: str
    name: str
    url: str
    environment: Environment = "production"
    authorized_by: str
    authorized_at: datetime
    authorization_statement: str = "I own this website or am authorized to test it."
    created_at: datetime = Field(default_factory=utcnow)
    roles: list[Role] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    privacy_blur: bool | None = None  # None = decide from detected domain
    notes: str = ""


# --------------------------------------------------------------------------- run

RunStatus = Literal["pending", "running", "completed", "failed", "interrupted", "cancelled"]
Stage = Literal["explore", "understand", "model", "requirements", "design", "execute", "verify", "report"]
STAGES: list[str] = [
    "explore",
    "understand",
    "model",
    "requirements",
    "design",
    "execute",
    "verify",
    "report",
]


class TokenUsage(Model):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    requests: int = 0
    cached_responses: int = 0
    cost_usd: float = 0.0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


class StageState(Model):
    status: Literal["pending", "running", "done", "skipped", "failed"] = "pending"
    progress: float = 0.0
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Run(Document):
    id: str
    project_slug: str
    mode: RunMode = "safe"
    status: RunStatus = "pending"
    stage: str = "explore"
    stages: dict[str, StageState] = Field(default_factory=lambda: {s: StageState() for s in STAGES})
    progress: float = 0.0
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    options: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    demo: bool = False


# --------------------------------------------------------------------------- crawl


class LocatorSet(Model):
    """Several independent ways to find the same element again. Used by the replayer for self-healing."""

    id: str = ""
    name: str = ""
    test_id: str = ""
    aria_label: str = ""
    text: str = ""
    label: str = ""
    placeholder: str = ""
    css: str = ""
    xpath: str = ""
    tag: str = ""


class Element(Model):
    index: int
    tag: str
    type: str = ""
    role: str = ""
    label: str = ""
    text: str = ""
    name: str = ""
    placeholder: str = ""
    href: str = ""
    value: str = ""
    required: bool = False
    disabled: bool = False
    pattern: str = ""
    min: str = ""
    max: str = ""
    minlength: int | None = None
    maxlength: int | None = None
    options: list[str] = Field(default_factory=list)
    form_index: int | None = None
    in_viewport: bool = True
    attributes: dict[str, str] = Field(default_factory=dict)
    locators: LocatorSet = Field(default_factory=LocatorSet)

    def describe(self) -> str:
        """One line for the AI: `[12] button "Save Patient"`."""
        kind = self.tag if not self.type or self.tag != "input" else f"input:{self.type}"
        if self.role and self.role not in (self.tag, "textbox"):
            kind = f"{kind}[{self.role}]"
        label = (
            self.label
            or self.text
            or self.placeholder
            or self.name
            or self.value
            or self.locators.test_id
            or self.attributes.get("id", "")
            or self.attributes.get("class", "")
        )
        extra = []
        if self.required:
            extra.append("required")
        if self.disabled:
            extra.append("disabled")
        if self.href and self.tag == "a":
            extra.append(f"href={self.href}")
        if self.options:
            more = f" (+{len(self.options) - 25} more)" if len(self.options) > 25 else ""
            extra.append("options=" + "|".join(o[:40] for o in self.options[:25]) + more)
        suffix = f" ({', '.join(extra)})" if extra else ""
        return f'[{self.index}] {kind} "{label[:80]}"{suffix}'


FormPurpose = Literal["login", "search", "filter", "create", "edit", "contact", "other"]


class Form(Model):
    index: int
    action: str = ""
    method: str = "get"
    purpose: FormPurpose = "other"
    field_indices: list[int] = Field(default_factory=list)
    submit_index: int | None = None
    heading: str = ""


class Table(Model):
    headers: list[str] = Field(default_factory=list)
    row_count: int = 0
    caption: str = ""


class NetworkEvent(Model):
    url: str
    method: str = "GET"
    status: int | None = None
    resource_type: str = ""
    error: str = ""


class ConsoleEntry(Model):
    level: str
    message: str
    source: str = ""


class PageRecord(Model):
    id: str
    role: str = "public"
    url: str
    url_template: str
    title: str = ""
    status_code: int | None = None
    depth: int = 0
    discovered_from: str = ""
    discovered_via: Literal["seed", "link", "click", "redirect", "login"] = "link"
    load_time_ms: int | None = None
    screenshot: str = ""
    thumbnail: str = ""
    headings: list[str] = Field(default_factory=list)
    text_excerpt: str = ""
    elements: list[Element] = Field(default_factory=list)
    forms: list[Form] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    console: list[ConsoleEntry] = Field(default_factory=list)
    failed_requests: list[NetworkEvent] = Field(default_factory=list)
    is_login_page: bool = False
    crawled_at: datetime = Field(default_factory=utcnow)


Severity = Literal["critical", "major", "minor", "trivial"]


class Finding(Model):
    """Result of an automatic check (stage ① / ⑦ layer 1). Becomes a Bug once verified."""

    id: str
    check: str
    severity: Severity = "minor"
    title: str
    detail: str = ""
    page_url: str = ""
    page_id: str = ""
    role: str = "public"
    evidence: list[str] = Field(default_factory=list)  # relative artifact paths
    data: dict[str, Any] = Field(default_factory=dict)


class RoleCrawlSummary(Model):
    role: str
    login_ok: bool | None = None
    login_message: str = ""
    pages: int = 0
    blocked_actions: int = 0


class CrawlResult(Document):
    start_url: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    roles: list[RoleCrawlSummary] = Field(default_factory=list)
    pages: list[PageRecord] = Field(default_factory=list)
    blocked_actions: list[dict[str, str]] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)  # pages the browser could not capture


class FindingsDoc(Document):
    findings: list[Finding] = Field(default_factory=list)


# --------------------------------------------------------------------------- understand / model


class Evidence(Model):
    claim: str
    source: str = ""  # page url or element description
    weight: float = 0.5


class EntityField(Model):
    name: str
    type: str = "string"
    required: bool = False
    validation: str = ""


class Entity(Model):
    name: str
    fields: list[EntityField] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)
    operations: list[Literal["create", "read", "update", "delete", "list", "search"]] = Field(
        default_factory=list
    )


class Feature(Model):
    id: str
    name: str
    module: str = ""
    description: str = ""
    roles: list[str] = Field(default_factory=list)
    pages: list[str] = Field(default_factory=list)


class RoleProfile(Model):
    name: str
    description: str = ""
    observed: bool = False  # True when we crawled the site as this role


class SiteProfile(Document):
    domain: str
    sub_type: str = ""
    confidence: float = 0.0
    summary: str = ""
    method: Literal["ai", "heuristic"] = "ai"
    domain_scores: dict[str, float] = Field(
        default_factory=dict
    )  # heuristic keyword scores, for transparency
    roles: list[str] = Field(default_factory=list)
    role_details: list[RoleProfile] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    domain_pack: str = ""


class WorkflowStep(Model):
    order: int
    action: str
    role: str = ""
    page: str = ""
    state_after: str = ""


class Transition(Model):
    from_state: str
    to_state: str
    action: str = ""
    allowed: bool = True  # False = a transition the app must refuse (e.g. cancelled -> completed)
    role: str = ""


class Workflow(Model):
    id: str  # WF-01
    name: str
    entity: str = ""
    description: str = ""
    roles: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)


RuleStatus = Literal["proposed", "confirmed", "edited", "rejected"]


RuleCategory = Literal[
    "calculation", "validation", "permission", "state", "data_integrity", "scheduling", "other"
]


class BusinessRule(Model):
    id: str  # BR-001
    statement: str
    condition: str = ""  # testable formula or condition
    category: RuleCategory = "other"
    entity: str = ""
    source: str = ""  # where the rule was seen or why it is assumed (page, help text, domain knowledge)
    confidence: float = 0.5
    status: RuleStatus = "proposed"
    notes: str = ""


class UserStory(Model):
    id: str  # US-001
    role: str
    feature: str = ""
    module: str = ""
    story: str  # As a <role>, I want ..., so that ...
    acceptance_criteria: list[str] = Field(default_factory=list)
    status: RuleStatus = "proposed"


class PermissionCell(Model):
    role: str
    page: str
    action: str = "view"
    expected: Literal["allow", "deny", "unknown"] = "unknown"
    observed: Literal["allow", "deny", "untested"] = "untested"
    evidence: str = ""


class RequirementsDoc(Document):
    method: Literal["ai", "heuristic"] = "ai"
    generated_at: datetime = Field(default_factory=utcnow)
    stories: list[UserStory] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    rules: list[BusinessRule] = Field(default_factory=list)


class PermissionMatrix(Document):
    roles: list[str] = Field(default_factory=list)
    cells: list[PermissionCell] = Field(default_factory=list)


# --------------------------------------------------------------------------- tests / execution / bugs

Technique = Literal[
    "smoke",
    "crud",
    "e2e",
    "validation",
    "boundary",
    "equivalence",
    "negative",
    "state_transition",
    "permission",
    "data_integrity",
    "business_rule",
    "ui_responsive",
    "accessibility",
]
Priority = Literal["P1", "P2", "P3", "P4"]


class TestStep(Model):
    __test__ = False
    order: int
    action: str
    data: str = ""
    expected: str = ""


class TestCase(Model):
    __test__ = False  # not a pytest class
    id: str  # TC-<MOD>-001
    title: str
    module: str = ""
    technique: Technique = "smoke"
    type: Literal["functional", "negative", "security", "ui", "accessibility", "performance"] = "functional"
    priority: Priority = "P3"
    role: str = ""
    preconditions: list[str] = Field(default_factory=list)
    test_data: dict[str, Any] = Field(default_factory=dict)
    steps: list[TestStep] = Field(default_factory=list)
    expected_result: str = ""
    # traceability: {"stories": ["US-003"], "rules": ["BR-002"], "workflows": ["WF-01"], "pages": ["/patients"]}
    links: dict[str, list[str]] = Field(default_factory=dict)
    status: Literal["draft", "approved", "skipped"] = "draft"
    source: Literal["generated", "ai", "user", "plain_english"] = "generated"
    requires_full_mode: bool = False  # creates/changes data, so Safe Mode runs report it as blocked
    viewports: list[str] = Field(default_factory=lambda: ["desktop"])
    edited: bool = False  # a person changed it; regeneration keeps it


class TestSuite(Document):
    __test__ = False
    generated_at: datetime = Field(default_factory=utcnow)
    cases: list[TestCase] = Field(default_factory=list)


ResultKind = Literal["pass", "fail", "blocked", "error"]


class StepResult(Model):
    order: int
    action: str  # tool name: click, type, select, navigate, assert, finish, ... or a rule-runner check
    target: str = ""  # human description of the element, e.g. `button "Save patient"`
    input: str = ""
    observation: str = ""  # what the agent / runner saw, or the assertion evidence
    result: ResultKind = "pass"
    url: str = ""
    screenshot_before: str = ""
    screenshot_after: str = ""
    duration_ms: int = 0
    locators: LocatorSet | None = None  # for replay scripts and self-healing
    rect: dict[str, float] | None = None  # element box in the after-screenshot, for annotation
    blocked_reason: str = ""


class AutoFinding(Model):
    """Something the automatic checks noticed while a test ran (JS error, failed request, error page…)."""

    check: str
    severity: Severity = "minor"
    title: str
    detail: str = ""
    url: str = ""
    step: int | None = None


class Execution(Document):
    test_case_id: str
    attempt: int = 1
    result: ResultKind
    reason: str = ""
    expected: str = ""
    actual: str = ""
    confidence: float = 0.8
    method: Literal["agent", "replay", "replay_healed", "rule"] = "agent"
    role: str = ""
    viewport: str = "desktop"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    steps: list[StepResult] = Field(default_factory=list)
    failure_step: int | None = None
    auto_findings: list[AutoFinding] = Field(default_factory=list)
    final_page_text: str = ""  # visible text of the last page, for business-rule recalculation
    rule_checks: list[dict[str, Any]] = Field(
        default_factory=list
    )  # Python recalculations of confirmed rules
    video: str = ""
    console_log: str = ""
    network_log: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class ExecutionsDoc(Document):
    """executions/<TC-ID>.json — every attempt of one test case (first run + re-runs)."""

    test_case_id: str
    attempts: list[Execution] = Field(default_factory=list)


class ReplayStep(Model):
    action: str
    locators: LocatorSet | None = None
    input: str = ""
    url: str = ""
    target: str = ""


class ReplayScript(Document):
    """replay/<TC-ID>.json — the actions of a recorded agent run, replayable without AI."""

    test_case_id: str
    role: str = ""
    steps: list[ReplayStep] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)  # what the agent asserted, re-judged after a replay
    recorded_result: ResultKind = "pass"


class TestRunResult(Model):
    """One line per test case in results.json (attempts are in executions/<TC-ID>.json)."""

    __test__ = False
    test_case_id: str
    title: str = ""
    module: str = ""
    technique: str = ""
    priority: Priority = "P3"
    role: str = ""
    result: ResultKind
    reproducibility: str = ""  # "3/3" for confirmed failures, "1/3" flaky
    flaky: bool = False
    reason: str = ""
    method: str = ""
    viewport: str = "desktop"
    duration_ms: int = 0
    cost_usd: float = 0.0
    bug_ids: list[str] = Field(default_factory=list)


class ResultsDoc(Document):
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    mode: RunMode = "safe"
    results: list[TestRunResult] = Field(default_factory=list)


class BugEnvironment(Model):
    browser: str = ""
    os: str = ""
    viewport: str = ""
    url: str = ""
    role: str = ""
    date_time: str = ""


class Bug(Model):
    id: str  # BUG-001
    title: str
    summary: str = ""
    module: str = ""
    severity: Severity = "minor"
    severity_reason: str = ""
    priority: Priority = "P3"
    confidence: float = 0.5
    environment: BugEnvironment = Field(default_factory=BugEnvironment)
    preconditions: list[str] = Field(default_factory=list)
    steps_to_reproduce: list[str] = Field(default_factory=list)
    expected: str = ""
    actual: str = ""
    evidence: list[str] = Field(default_factory=list)
    reproducibility: str = ""  # "3/3"
    links: dict[str, list[str]] = Field(default_factory=dict)
    status: Literal["new", "needs_review", "confirmed", "rejected", "fixed"] = "new"
    category: str = ""
    symptom_key: str = ""
    test_case_ids: list[str] = Field(default_factory=list)
    screenshot: str = ""
    annotated_screenshot: str = ""
    clip: str = ""
    video: str = ""
    console: list[str] = Field(default_factory=list)
    network: list[str] = Field(default_factory=list)
    source: Literal["test", "automatic_check"] = "test"
    created_at: datetime = Field(default_factory=utcnow)


class BugsDoc(Document):
    bugs: list[Bug] = Field(default_factory=list)


# --------------------------------------------------------------------------- index / settings


class RunSummary(Model):
    id: str
    mode: RunMode = "safe"
    status: RunStatus = "pending"
    stage: str = "explore"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    pages: int = 0
    findings: int = 0
    bugs: int = 0
    quality_score: float | None = None
    domain: str = ""
    cost_usd: float = 0.0


class ProjectIndex(Document):
    project_slug: str
    runs: list[RunSummary] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utcnow)


class UserSettings(Document):
    """workspace/settings.json — only keys the user changed; merged over config/settings.yaml."""

    model_config = ConfigDict(extra="allow")
