"""Everything a full QA report needs, loaded once from the run folder.

Exports never include credentials: they read only run documents (no secrets.enc), and role names are the only
account information shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.execute import privacy
from app.execute.stage import BUGS_FILE, RESULTS_FILE
from app.explore.stage import PAGES_FILE
from app.requirements.stage import REQUIREMENTS_FILE
from app.storage.repository import Repository
from app.storage.schemas import (
    Bug,
    BugsDoc,
    CrawlResult,
    Project,
    RequirementsDoc,
    ResultsDoc,
    Run,
    SiteProfile,
    TestCase,
    TestRunResult,
    TestSuite,
    utcnow,
)
from app.testdesign.stage import TESTCASES_FILE
from app.understand.stage import PROFILE_FILE
from app.verify import insights, store

SAFE_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class Branding:
    company_name: str = ""
    prepared_for: str = ""
    accent_color: str = "#2563EB"
    logo_path: str = ""

    @classmethod
    def from_settings(cls) -> Branding:
        b = get_settings().get("branding") or {}
        accent = str(b.get("accent_color") or "#2563EB")
        logo = str(b.get("logo_path") or "")
        return cls(
            company_name=str(b.get("company_name") or ""),
            prepared_for=str(b.get("prepared_for") or ""),
            accent_color=accent if SAFE_HEX.match(accent) else "#2563EB",
            logo_path=logo if logo and Path(logo).is_file() else "",
        )


@dataclass
class TraceRow:
    requirement: str  # BR-002 / WF-01 / "—"
    requirement_text: str
    story: str
    test_case: str
    test_title: str
    result: str
    bugs: list[str] = field(default_factory=list)


@dataclass
class ReportData:
    project: Project
    run: Run
    profile: SiteProfile | None
    req: RequirementsDoc | None
    suite: TestSuite | None
    results: ResultsDoc | None
    bugs: list[Bug]
    crawl: CrawlResult | None
    quality: insights.Quality | None
    heatmap: insights.Heatmap | None
    matrix: insights.PermissionMatrixView | None
    comparison: insights.Comparison | None
    branding: Branding
    privacy: bool
    generated: Any = field(default_factory=utcnow)

    # ---------------------------------------------------------------- helpers

    @property
    def open_bugs(self) -> list[Bug]:
        return [b for b in self.bugs if b.status not in ("rejected", "fixed")]

    @property
    def result_list(self) -> list[TestRunResult]:
        return self.results.results if self.results else []

    def result_of(self, case_id: str) -> TestRunResult | None:
        return next((r for r in self.result_list if r.test_case_id == case_id), None)

    def case(self, case_id: str) -> TestCase | None:
        base = case_id.split("@")[0]
        return next((c for c in (self.suite.cases if self.suite else []) if c.id == base), None)

    def counts(self) -> dict[str, int]:
        out = {k: 0 for k in ("pass", "fail", "blocked", "error")}
        for r in self.result_list:
            out[r.result] += 1
        return out

    def severity_counts(self) -> dict[str, int]:
        out = {k: 0 for k in ("critical", "major", "minor", "trivial")}
        for b in self.open_bugs:
            out[b.severity] += 1
        return out

    def traceability(self) -> list[TraceRow]:
        """Requirement → Story → Test case → Result → Bug, one row per (requirement, test case)."""
        rows: list[TraceRow] = []
        if not self.suite:
            return rows
        rules = {r.id: r.statement for r in (self.req.rules if self.req else [])}
        flows = {w.id: w.name for w in (self.req.workflows if self.req else [])}
        bugs_by_case: dict[str, list[str]] = {}
        for b in self.bugs:
            if b.status == "rejected":
                continue
            for tc in b.test_case_ids:
                bugs_by_case.setdefault(tc, []).append(b.id)
        run_ids = [r.test_case_id for r in self.result_list]
        for c in self.suite.cases:
            if c.status == "skipped":
                continue
            reqs = [(rid, rules.get(rid, "")) for rid in c.links.get("rules", [])] + [
                (wid, flows.get(wid, "")) for wid in c.links.get("workflows", [])
            ]
            stories = ", ".join(c.links.get("stories", [])) or "—"
            variants = [i for i in run_ids if i == c.id or i.startswith(c.id + "@")] or [c.id]
            for rid, text in reqs or [("—", "")]:
                for vid in variants:
                    res = self.result_of(vid)
                    rows.append(
                        TraceRow(
                            requirement=rid,
                            requirement_text=text,
                            story=stories,
                            test_case=vid,
                            test_title=c.title,
                            result=res.result if res else ("not run" if c.status == "approved" else c.status),
                            bugs=bugs_by_case.get(vid, []),
                        )
                    )
        return rows

    def evidence_bytes(self, repo: Repository, relative: str) -> bytes | None:
        """An evidence image as it may be shared: blurred when privacy blur is on for this project."""
        if not relative:
            return None
        path = repo.run_path(self.run, relative)
        if not path.exists():
            return None
        if self.privacy:  # no-op when nothing personal was detected (or the copy is already blurred)
            return privacy.blurred_bytes(path)
        return path.read_bytes()


def _load(repo: Repository, run: Run, path: str, cls: type) -> Any:
    return repo.load_run_doc(run, path, cls) if repo.has_run_doc(run, path) else None


def load(repo: Repository, project: Project, run: Run) -> ReportData:
    profile = _load(repo, run, PROFILE_FILE, SiteProfile)
    bugs_doc = _load(repo, run, BUGS_FILE, BugsDoc)
    return ReportData(
        project=project,
        run=run,
        profile=profile,
        req=_load(repo, run, REQUIREMENTS_FILE, RequirementsDoc),
        suite=_load(repo, run, TESTCASES_FILE, TestSuite),
        results=_load(repo, run, RESULTS_FILE, ResultsDoc),
        bugs=bugs_doc.bugs if bugs_doc else [],
        crawl=_load(repo, run, PAGES_FILE, CrawlResult),
        quality=store.quality(repo, run),
        heatmap=store.heatmap(repo, run),
        matrix=store.permission_matrix(repo, run),
        comparison=store.compare(repo, run),
        branding=Branding.from_settings(),
        privacy=privacy.privacy_enabled(project, profile.domain if profile else ""),
    )
