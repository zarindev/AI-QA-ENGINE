"""PDF QA reports: the full report, a bug-only report and a single-bug report (HTML → PDF with Chrome).

Two audiences: the cover and executive summary are written in plain language for business readers; bug pages and
appendices carry the technical detail. Evidence images are embedded (blurred when privacy blur is on), so the HTML
next to each PDF is self-contained too.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import __version__
from app.core.paths import TEMPLATES_DIR
from app.execute import media
from app.reports.data import ReportData
from app.reports.pdf import html_to_pdf
from app.storage.repository import Repository
from app.storage.schemas import Bug

REPORT_PDF = "exports/qa_report.pdf"
BUGS_PDF = "exports/bug_report.pdf"
SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "trivial": 3}

Kind = Literal["full", "bugs", "single"]
HEAT_LABELS = {
    "smoke": "Smoke",
    "crud": "CRUD",
    "e2e": "E2E",
    "validation": "Valid.",
    "boundary": "Bound.",
    "equivalence": "Equiv.",
    "negative": "Neg.",
    "state_transition": "State",
    "permission": "Perm.",
    "data_integrity": "Data",
    "business_rule": "Rules",
    "ui_responsive": "Resp.",
    "accessibility": "A11y",
}

_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html", "j2"]))


def bug_pdf_path(bug_id: str) -> str:
    return f"exports/bugs/{bug_id}.pdf"


def _data_uri(raw: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def executive_summary(d: ReportData) -> tuple[str, str, list[str]]:
    """(cover headline, lead paragraph, bullet points) — deterministic, from the numbers only."""
    counts, sev = d.counts(), d.severity_counts()
    pages = len(d.crawl.pages) if d.crawl else 0
    roles = [r for r in (d.profile.roles if d.profile else []) if r != "public"]
    open_bugs = d.open_bugs
    serious = sev["critical"] + sev["major"]
    if not d.result_list:
        headline = "Exploration and test design finished; tests have not been run yet."
    elif sev["critical"]:
        headline = f"{_plural(sev['critical'], 'critical issue')} should be fixed before release."
    elif serious:
        headline = f"No critical issues; {_plural(sev['major'], 'major issue')} to fix."
    else:
        headline = "No critical or major issues found."
    lead = (
        f"QA Pilot explored {_plural(pages, 'page')} of {d.project.name}"
        + (f" as {_plural(len(roles), 'signed-in role')} ({', '.join(roles)})" if roles else "")
        + f" and ran {_plural(len(d.result_list), 'test')}: {counts['pass']} passed and {counts['fail']} failed. "
        + f"It reports {_plural(len(open_bugs), 'open bug')}"
        + (f", of which {serious} {'is' if serious == 1 else 'are'} critical or major." if open_bugs else ".")
    )
    points: list[str] = []
    top = sorted(open_bugs, key=lambda b: (SEVERITY_RANK[b.severity], b.priority))[:3]
    for b in top:
        points.append(f"{b.severity.capitalize()}: {b.title} ({b.id}).")
    if d.quality and d.quality.score is not None:
        measured = [s for s in d.quality.sub_scores if s.score is not None]
        weakest = min(measured, key=lambda s: s.score or 0) if measured else None
        points.append(
            f"Quality score {d.quality.score:g}/100 (grade {d.quality.grade})"
            + (f"; weakest area: {weakest.label} ({weakest.score:.0f})." if weakest else ".")
        )
    if d.matrix and d.matrix.holes:
        points.append(
            f"{_plural(d.matrix.holes, 'permission hole')}: a role can open a screen it should not."
        )
    if counts["blocked"]:
        points.append(
            f"{_plural(counts['blocked'], 'test')} could not run"
            + (" because Safe Mode never submits or deletes data." if d.run.mode == "safe" else ".")
        )
    review = sum(1 for b in d.bugs if b.status == "needs_review")
    if review:
        points.append(f"{_plural(review, 'bug')} need a person's review (flaky or low confidence).")
    if d.comparison:
        c = d.comparison.counts
        points.append(
            f"Since run {d.comparison.base_run}: {c['fixed']} fixed, {c['new']} new, {c['reappeared']} reappeared."
        )
    return headline, lead, points


def _images(repo: Repository, d: ReportData, bugs: list[Bug]) -> dict[str, str]:
    out = {}
    for b in bugs:
        raw = d.evidence_bytes(repo, b.annotated_screenshot or b.screenshot)
        if raw:
            out[b.id] = _data_uri(media.to_jpeg(raw, quality=72))
    return out


def _logo(d: ReportData) -> str:
    if not d.branding.logo_path:
        return ""
    path = Path(d.branding.logo_path)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return _data_uri(path.read_bytes(), mime) if mime.startswith("image/") else ""


def render(repo: Repository, d: ReportData, kind: Kind, bugs: list[Bug] | None = None) -> str:
    chosen = bugs if bugs is not None else [b for b in d.bugs if b.status != "rejected"]
    chosen = sorted(chosen, key=lambda b: (SEVERITY_RANK[b.severity], b.id))
    headline, lead, points = executive_summary(d)
    ctx: dict[str, Any] = {
        "d": d,
        "kind": kind,
        "title": {"full": "QA report", "bugs": "Bug report", "single": "Bug report"}[kind],
        "accent": d.branding.accent_color,
        "logo": _logo(d),
        "bugs": chosen,
        "images": _images(repo, d, chosen),
        "counts": d.counts(),
        "sev": d.severity_counts(),
        "headline": headline,
        "summary_lead": lead,
        "summary_points": points,
        "heat": {(c.module, c.technique): c for c in (d.heatmap.cells if d.heatmap else [])},
        "trace": d.traceability() if kind == "full" else [],
        "short": HEAT_LABELS,
        "version": __version__,
    }
    return _env.get_template("qa_report.html.j2").render(**ctx)


def export(repo: Repository, d: ReportData, kind: Kind, bug_id: str | None = None) -> Path:
    if kind == "single":
        bug = next((b for b in d.bugs if b.id == bug_id), None)
        if bug is None:
            raise KeyError(bug_id)
        rel = bug_pdf_path(bug.id)
        html = render(repo, d, "single", [bug])
    else:
        rel = REPORT_PDF if kind == "full" else BUGS_PDF
        html = render(repo, d, kind)
    pdf = repo.run_path(d.run, rel)
    return html_to_pdf(repo, html, pdf.with_suffix(".html"), pdf)
