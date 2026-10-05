"""CSV exports: bugs for Jira and Trello import, and the traceability matrix.

Jira: *System → External system import → CSV*; map Summary, Issue Type, Priority, Description, Labels, Component.
Trello: the CSV columns follow Trello's card import (Card Name, Card Description, Labels); Trello Free imports via
Power-Ups such as *CSV to Trello*. Files are UTF-8 with a BOM so Excel opens them correctly.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.reports.data import ReportData
from app.storage.repository import Repository
from app.storage.schemas import Bug

JIRA_CSV = "exports/bugs_jira.csv"
TRELLO_CSV = "exports/bugs_trello.csv"
TRACE_CSV = "exports/traceability.csv"

JIRA_PRIORITY = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n").writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _description(b: Bug, wiki: bool) -> str:
    h = (lambda t: f"h3. {t}") if wiki else (lambda t: f"**{t}**")
    parts = [b.summary, ""]
    if b.preconditions:
        parts += [h("Preconditions"), *[f"* {p}" if wiki else f"- {p}" for p in b.preconditions], ""]
    if b.steps_to_reproduce:
        parts += [
            h("Steps to reproduce"),
            *[f"# {s}" if wiki else f"{i}. {s}" for i, s in enumerate(b.steps_to_reproduce, 1)],
            "",
        ]
    parts += [h("Expected"), b.expected, "", h("Actual"), b.actual, ""]
    env = b.environment
    parts += [
        h("Environment"),
        f"{env.browser} · {env.os} · {env.viewport} · role: {env.role}",
        f"URL: {env.url}",
        f"Reproducibility: {b.reproducibility or '—'} · severity: {b.severity} ({b.severity_reason})",
        f"Test cases: {', '.join(b.test_case_ids) or '—'}",
        f"Evidence (in the QA Pilot run folder): {b.annotated_screenshot or b.screenshot or '—'}"
        + (f", {b.clip}" if b.clip else ""),
    ]
    return "\n".join(p for p in parts if p is not None).strip()


def _label(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def jira_csv(d: ReportData) -> bytes:
    rows = [
        ["Summary", "Issue Type", "Priority", "Description", "Labels", "Labels", "Component", "External ID"]
    ]
    for b in d.bugs:
        if b.status == "rejected":
            continue
        rows.append(
            [
                b.title,
                "Bug",
                JIRA_PRIORITY[b.priority],
                _description(b, wiki=True),
                "qa-pilot",
                f"severity-{b.severity}",
                b.module,
                f"{d.run.id}/{b.id}",
            ]
        )
    return _csv(rows)


def trello_csv(d: ReportData) -> bytes:
    rows = [["Card Name", "Card Description", "Labels", "List Name"]]
    for b in d.bugs:
        if b.status == "rejected":
            continue
        labels = ",".join(x for x in (b.severity, b.priority, _label(b.module)) if x)
        rows.append(
            [
                f"[{b.id}] {b.title}",
                _description(b, wiki=False),
                labels,
                "Bugs — " + b.status.replace("_", " "),
            ]
        )
    return _csv(rows)


def trace_csv(d: ReportData) -> bytes:
    rows = [["Requirement", "Statement", "Stories", "Test case", "Test", "Result", "Bugs"]]
    for t in d.traceability():
        rows.append(
            [
                t.requirement,
                t.requirement_text,
                t.story,
                t.test_case,
                t.test_title,
                t.result,
                " ".join(t.bugs),
            ]
        )
    return _csv(rows)


def export(repo: Repository, d: ReportData, kind: str) -> Path:
    rel, data = {
        "jira": (JIRA_CSV, jira_csv),
        "trello": (TRELLO_CSV, trello_csv),
        "traceability": (TRACE_CSV, trace_csv),
    }[kind]
    path = repo.run_path(d.run, rel)
    repo.write_bytes(path, data(d))
    return path
