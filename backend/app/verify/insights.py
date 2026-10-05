"""Run insights: Quality Score, coverage heatmap, permission matrix, regression comparison.

Quality Score (0–100) — documented in docs/ARCHITECTURE.md:
  sub_score(category) = 100 × (passed / executed tests of that category)
                        − Σ open-bug penalties in that category (critical 25, major 12, minor 5, trivial 1),
                        clamped to 0–100. Categories with no executed tests are "not measured".
  Performance = 100 × (1 − share of explored pages slower than the threshold) − performance-bug penalties.
  overall = weighted mean of the measured sub-scores:
            Functional 30 · Permissions 20 · Data integrity 20 · UI 10 · Accessibility 10 · Performance 10.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.storage.schemas import Bug, CrawlResult, ResultsDoc, TestSuite

CATEGORY_OF = {
    "smoke": "functional",
    "crud": "functional",
    "e2e": "functional",
    "validation": "functional",
    "boundary": "functional",
    "equivalence": "functional",
    "negative": "functional",
    "state_transition": "functional",
    "business_rule": "functional",
    "permission": "permissions",
    "data_integrity": "data_integrity",
    "ui_responsive": "ui",
    "accessibility": "accessibility",
}
BUG_CATEGORY = {
    "permission": "permissions",
    "data_integrity": "data_integrity",
    "ui_responsive": "ui",
    "accessibility": "accessibility",
    "performance": "performance",
}
WEIGHTS = {
    "functional": 30,
    "permissions": 20,
    "data_integrity": 20,
    "ui": 10,
    "accessibility": 10,
    "performance": 10,
}
PENALTY = {"critical": 25, "major": 12, "minor": 5, "trivial": 1}
LABELS = {
    "functional": "Functional",
    "permissions": "Permissions",
    "data_integrity": "Data integrity",
    "ui": "UI",
    "accessibility": "Accessibility",
    "performance": "Performance",
}


class SubScore(BaseModel):
    key: str
    label: str
    score: float | None
    passed: int = 0
    executed: int = 0
    bugs: int = 0
    note: str = ""


class Quality(BaseModel):
    score: float | None
    grade: str
    sub_scores: list[SubScore]
    formula: str = (
        "weighted mean of measured sub-scores (Functional 30, Permissions 20, Data integrity 20, UI 10, "
        "Accessibility 10, Performance 10); each = pass rate − open-bug penalties"
    )


def _open(bug: Bug) -> bool:
    return bug.status not in ("rejected", "fixed")


def quality(results: ResultsDoc, bugs: list[Bug], crawl: CrawlResult | None, slow_ms: int = 3000) -> Quality:
    passed: dict[str, int] = {k: 0 for k in WEIGHTS}
    executed: dict[str, int] = {k: 0 for k in WEIGHTS}
    for r in results.results:
        cat = CATEGORY_OF.get(r.technique, "functional")
        if r.result in ("pass", "fail"):
            executed[cat] += 1
            passed[cat] += r.result == "pass"
    penalties: dict[str, float] = {k: 0.0 for k in WEIGHTS}
    bug_counts: dict[str, int] = {k: 0 for k in WEIGHTS}
    for b in bugs:
        if not _open(b):
            continue
        cat = BUG_CATEGORY.get(b.category, "functional")
        if b.category in (
            "calculation",
            "business_rule",
            "state_transition",
            "validation",
            "js_error",
            "broken_link",
        ):
            cat = "functional"
        penalties[cat] += PENALTY[b.severity]
        bug_counts[cat] += 1
    subs: list[SubScore] = []
    for key in WEIGHTS:
        if key == "performance":
            pages = [p for p in (crawl.pages if crawl else []) if p.load_time_ms]
            if not pages:
                subs.append(SubScore(key=key, label=LABELS[key], score=None, note="no timing data"))
                continue
            slow = sum(1 for p in pages if (p.load_time_ms or 0) > slow_ms)
            score = 100 * (1 - slow / len(pages)) - penalties[key]
            subs.append(
                SubScore(
                    key=key,
                    label=LABELS[key],
                    score=round(max(0, min(100, score)), 1),
                    passed=len(pages) - slow,
                    executed=len(pages),
                    bugs=bug_counts[key],
                    note=f"{slow} of {len(pages)} pages slower than {slow_ms / 1000:g}s",
                )
            )
            continue
        if executed[key] == 0:
            subs.append(
                SubScore(key=key, label=LABELS[key], score=None, bugs=bug_counts[key], note="not measured")
            )
            continue
        score = 100 * passed[key] / executed[key] - penalties[key]
        subs.append(
            SubScore(
                key=key,
                label=LABELS[key],
                score=round(max(0, min(100, score)), 1),
                passed=passed[key],
                executed=executed[key],
                bugs=bug_counts[key],
            )
        )
    measured = [s for s in subs if s.score is not None]
    total_w = sum(WEIGHTS[s.key] for s in measured)
    overall = round(sum(WEIGHTS[s.key] * (s.score or 0) for s in measured) / total_w, 1) if total_w else None
    grade = (
        "—"
        if overall is None
        else (
            "A"
            if overall >= 90
            else "B" if overall >= 75 else "C" if overall >= 60 else "D" if overall >= 40 else "F"
        )
    )
    return Quality(score=overall, grade=grade, sub_scores=subs)


# ---------------------------------------------------------------- coverage heatmap


CellState = Literal["pass", "fail", "warn", "untested"]


class HeatCell(BaseModel):
    module: str
    technique: str
    state: CellState
    total: int = 0
    passed: int = 0
    failed: int = 0
    other: int = 0
    cases: list[str] = Field(default_factory=list)


class Heatmap(BaseModel):
    modules: list[str]
    techniques: list[str]
    cells: list[HeatCell]


TECHNIQUE_ORDER = [
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


def heatmap(suite: TestSuite, results: ResultsDoc | None) -> Heatmap:
    by_id = {r.test_case_id: r for r in (results.results if results else [])}
    cells: dict[tuple[str, str], HeatCell] = {}
    for c in suite.cases:
        if c.status == "skipped":
            continue
        cell = cells.setdefault(
            (c.module, c.technique), HeatCell(module=c.module, technique=c.technique, state="untested")
        )
        cell.total += 1
        cell.cases.append(c.id)
        r = by_id.get(c.id)
        if r is None:
            continue
        if r.result == "pass":
            cell.passed += 1
        elif r.result == "fail":
            cell.failed += 1
        else:
            cell.other += 1
    for cell in cells.values():
        if cell.failed:
            cell.state = "fail"
        elif cell.other:
            cell.state = "warn"
        elif cell.passed == cell.total:
            cell.state = "pass"
        elif cell.passed:
            cell.state = "warn"
    modules = sorted({k[0] for k in cells})
    techniques = [t for t in TECHNIQUE_ORDER if any(k[1] == t for k in cells)]
    return Heatmap(modules=modules, techniques=techniques, cells=list(cells.values()))


# ---------------------------------------------------------------- permission matrix


class MatrixCell(BaseModel):
    role: str
    page: str
    expected: Literal["allow", "deny", "unknown"]
    observed: Literal["allow", "deny", "untested"]
    hole: bool = False  # expected deny, observed allow
    source: str = ""
    evidence: str = ""


class PermissionMatrixView(BaseModel):
    roles: list[str]
    pages: list[str]
    cells: list[MatrixCell]
    holes: int


def permission_matrix(
    crawl: CrawlResult, suite: TestSuite | None, executions: dict[str, Any]
) -> PermissionMatrixView:
    """Expected: a role that reached a screen through its own navigation is allowed; a screen only other roles
    reach is expected to be denied. Observed: the crawl (allow) and the direct-URL permission tests (allow/deny).
    """
    roles = [r.role for r in crawl.roles if r.role != "public" and r.login_ok]
    reached: dict[str, set[str]] = {r: set() for r in roles}
    for p in crawl.pages:
        if p.role in reached and not p.is_login_page and (p.status_code or 200) < 400:
            reached[p.role].add(p.url_template)
    pages = sorted({t for s in reached.values() for t in s})
    observed: dict[tuple[str, str], tuple[str, str]] = {}
    for case in (suite.cases if suite else []):
        if case.technique != "permission" or case.id not in executions:
            continue
        first = executions[case.id]
        for step in first.steps:
            if step.action == "navigate" and step.target in pages:
                verdict = "allow" if step.result == "fail" else "deny" if step.result == "pass" else ""
                if verdict:
                    observed[(first.role or case.role, step.target)] = (verdict, step.observation)
    cells = []
    for role in roles:
        for page in pages:
            expected: Literal["allow", "deny", "unknown"] = "allow" if page in reached[role] else "deny"
            if (role, page) in observed:
                obs, ev = observed[(role, page)]
            elif page in reached[role]:
                obs, ev = "allow", "Reached through the role's own navigation while exploring."
            else:
                obs, ev = "untested", ""
            cells.append(
                MatrixCell(
                    role=role,
                    page=page,
                    expected=expected,
                    observed=obs,  # type: ignore[arg-type]
                    hole=expected == "deny" and obs == "allow",
                    evidence=ev,
                    source="navigation" if page in reached[role] else "not in this role's menus",
                )
            )
    return PermissionMatrixView(roles=roles, pages=pages, cells=cells, holes=sum(c.hole for c in cells))


# ---------------------------------------------------------------- regression comparison


class ComparedBug(BaseModel):
    key: str
    title: str
    severity: str
    status: Literal["new", "fixed", "reappeared", "still_open"]
    current_id: str = ""
    base_id: str = ""


class Comparison(BaseModel):
    base_run: str
    current_run: str
    counts: dict[str, int]
    bugs: list[ComparedBug]


def _bug_key(b: Bug) -> str:
    return (b.symptom_key or b.title).lower().strip()


def compare(
    current_id: str, current: list[Bug], base_id: str, base: list[Bug], history: list[list[Bug]]
) -> Comparison:
    """history: bug lists of runs older than `base` (newest first) — a bug absent in base but seen earlier has
    *reappeared*."""
    cur = {_bug_key(b): b for b in current if _open(b)}
    old = {_bug_key(b): b for b in base if _open(b)}
    earlier = {_bug_key(b) for bugs in history for b in bugs}
    out = []
    for key, b in cur.items():
        if key in old:
            out.append(
                ComparedBug(
                    key=key,
                    title=b.title,
                    severity=b.severity,
                    status="still_open",
                    current_id=b.id,
                    base_id=old[key].id,
                )
            )
        else:
            out.append(
                ComparedBug(
                    key=key,
                    title=b.title,
                    severity=b.severity,
                    status="reappeared" if key in earlier else "new",
                    current_id=b.id,
                )
            )
    for key, b in old.items():
        if key not in cur:
            out.append(ComparedBug(key=key, title=b.title, severity=b.severity, status="fixed", base_id=b.id))
    counts = {s: sum(1 for b in out if b.status == s) for s in ("new", "fixed", "reappeared", "still_open")}
    return Comparison(base_run=base_id, current_run=current_id, counts=counts, bugs=out)
