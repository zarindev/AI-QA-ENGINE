"""Gherkin export: one .feature file per module, one Scenario per test case (approved cases by default)."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from app.core.paths import slugify
from app.storage.repository import Repository
from app.storage.schemas import Run, TestCase, TestSuite

GHERKIN_DIR = "exports/gherkin"
GHERKIN_ZIP = "exports/gherkin.zip"


def _line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def scenario(case: TestCase) -> str:
    tags = [f"@{case.id}", f"@{case.priority}", f"@{case.technique}"]
    if case.requires_full_mode:
        tags.append("@full_mode")
    lines = ["  " + " ".join(tags), f"  Scenario: {_line(case.title)}"]
    givens = [
        f"I am logged in as {case.role}" if case.role and case.role != "public" else "I am not logged in"
    ]
    givens += [_line(p) for p in case.preconditions]
    lines.append(f"    Given {givens[0]}")
    lines += [f"    And {g}" for g in givens[1:]]
    first_when = True
    for step in case.steps:
        action = _line(step.action) + (f' "{step.data}"' if step.data and len(step.data) < 120 else "")
        if re.match(r"^log in as", step.action, re.I):
            continue  # already in Given
        keyword = "When" if first_when else "And"  # a new When after every Then
        lines.append(f"    {keyword} {action}")
        first_when = False
        if step.expected:
            lines.append(f"    Then {_line(step.expected)}")
            first_when = True
    lines.append(f"    Then {_line(case.expected_result)}")
    return "\n".join(lines)


def features(suite: TestSuite, statuses: tuple[str, ...] = ("approved",)) -> dict[str, str]:
    by_module: dict[str, list[TestCase]] = {}
    for case in suite.cases:
        if case.status in statuses:
            by_module.setdefault(case.module or "General", []).append(case)
    out = {}
    for module, cases in sorted(by_module.items()):
        body = [f"Feature: {module}", f"  Test cases designed by QA Pilot for the {module} module.", ""]
        body += [scenario(c) + "\n" for c in cases]
        out[f"{slugify(module)}.feature"] = "\n".join(body)
    return out


def export(repo: Repository, run: Run, suite: TestSuite, statuses: tuple[str, ...] = ("approved",)) -> Path:
    files = features(suite, statuses)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            repo.write_text(repo.run_path(run, f"{GHERKIN_DIR}/{name}"), text)
            zf.writestr(name, text)
    path = repo.run_path(run, GHERKIN_ZIP)
    repo.write_bytes(path, buf.getvalue())
    return path
