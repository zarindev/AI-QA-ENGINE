"""QA Pilot command line.

python cli.py run https://www.saucedemo.com --role standard:standard_user:secret_sauce --i-am-authorized
python cli.py review <project-slug> --confirm-rules 0.8 --approve all     # what a reviewer does in the UI
python cli.py execute <project-slug> --viewport desktop --viewport mobile
python cli.py export <project-slug> --kind qa_report_pdf --kind qa_xlsx
python cli.py projects
python cli.py runs <project-slug>
python cli.py report <project-slug> <run-id>
"""

from __future__ import annotations

import getpass
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import typer  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn  # noqa: E402
from rich.table import Table  # noqa: E402

from app.ai.client import AIClient  # noqa: E402
from app.browser import auth  # noqa: E402
from app.browser.driver import chrome_available  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.logging import register_secret, setup_logging  # noqa: E402
from app.explore import urls  # noqa: E402
from app.explore.stage import FINDINGS_FILE, PAGES_FILE  # noqa: E402
from app.jobs import pipeline  # noqa: E402
from app.jobs.run_state import RunTracker, heartbeat, mark_interrupted_runs  # noqa: E402
from app.reports.html_basic import REPORT_FILE, render_crawl_report  # noqa: E402
from app.storage.repository import NotFoundError, Repository  # noqa: E402
from app.storage.schemas import (  # noqa: E402
    CrawlResult,
    FindingsDoc,
    Project,
    Role,
    Run,
    Scope,
    SiteProfile,
    utcnow,
)
from app.understand.stage import PROFILE_FILE  # noqa: E402

app = typer.Typer(add_completion=False, no_args_is_help=True, help="QA Pilot — AI website QA engine (local).")
console = Console()

SEVERITY_STYLE = {"critical": "bold red", "major": "yellow", "minor": "cyan", "trivial": "dim"}


def _wait_for_enter(_session: object) -> None:
    input("Press Enter once you are logged in… ")


def _parse_role(spec: str) -> tuple[str, str, str]:
    parts = spec.split(":", 2)
    if len(parts) != 3 or not all(parts):
        raise typer.BadParameter(f"Role must look like NAME:USERNAME:PASSWORD, got '{spec}'")
    return parts[0], parts[1], parts[2]


def _find_project(repo: Repository, url: str) -> Project | None:
    target = urls.normalize(url)
    return next((p for p in repo.list_projects() if urls.normalize(p.url) == target), None)


@app.command()
def run(
    url: str = typer.Argument(..., help="Start URL of the site to test"),
    name: str = typer.Option("", help="Project name (defaults to the host name)"),
    env: str = typer.Option("production", help="production | staging | test"),
    mode: str = typer.Option("safe", help="safe (default) | full — full is only allowed for staging/test"),
    role: list[str] = typer.Option([], "--role", "-r", help="NAME:USERNAME:PASSWORD (repeatable)"),
    manual_login: list[str] = typer.Option(
        [], "--manual-login", help="Role name to log in by hand in a visible browser (2FA/SSO)"
    ),
    login_url: str = typer.Option("", help="Login page URL if it is not the start URL"),
    max_pages: int = typer.Option(None, help="Max pages per role"),
    max_depth: int = typer.Option(None, help="Max link depth"),
    headed: bool = typer.Option(False, "--headed", help="Show the browser while crawling"),
    authorized_by: str = typer.Option("", help="Your name, recorded with the authorization confirmation"),
    i_am_authorized: bool = typer.Option(
        False, "--i-am-authorized", help="Confirm you own the site or are authorized to test it"
    ),
    confirm_full: bool = typer.Option(
        False, "--confirm-full-mode", help="Second confirmation required for Full Mode"
    ),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Explore, understand, model, write requirements and design tests (stages 1–5); writes an HTML crawl report."""
    import logging

    setup_logging(logging.DEBUG if verbose else logging.INFO, Repository().root / "logs" / "qa-pilot.log")
    settings = get_settings()
    if env not in ("production", "staging", "test"):
        raise typer.BadParameter("--env must be production, staging or test")
    if mode not in ("safe", "full"):
        raise typer.BadParameter("--mode must be safe or full")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not chrome_available():
        console.print(
            "[red]Google Chrome was not found.[/] Install it from https://www.google.com/chrome/ and try again."
        )
        raise typer.Exit(2)

    # ---- authorization (Section 9): required, timestamped in project.json
    if not i_am_authorized:
        console.print(f"[bold]Target:[/] {url}")
        if not typer.confirm("I own this website or am authorized to test it", default=False):
            console.print("[red]Authorization not confirmed — nothing was done.[/]")
            raise typer.Exit(1)
    who = authorized_by or getpass.getuser()

    if mode == "full":
        if env not in ("staging", "test"):
            console.print("[red]Full Mode is only allowed for environments marked staging or test.[/]")
            raise typer.Exit(1)
        if not confirm_full and not typer.confirm(
            "Full Mode may create, change or delete data on this site. Continue?", default=False
        ):
            raise typer.Exit(1)

    repo = Repository()
    mark_interrupted_runs(repo)
    project = _find_project(repo, url)
    if project is None:
        host = urlparse(url).hostname or "site"
        project = Project(
            slug=repo.unique_slug(name or host),
            name=name or host,
            url=url,
            environment=env,  # type: ignore[arg-type]
            authorized_by=who,
            authorized_at=utcnow(),
            scope=Scope(
                max_pages=max_pages or settings["crawl"]["max_pages"],
                max_depth=max_depth or settings["crawl"]["max_depth"],
            ),
        )
        repo.create_project(project)
        console.print(f"Created project [bold]{project.slug}[/]")
    else:
        project.authorized_by, project.authorized_at, project.environment = who, utcnow(), env  # type: ignore[assignment]
        console.print(f"Using existing project [bold]{project.slug}[/]")

    # ---- roles: credentials go to secrets.enc only, never project.json
    roles = {r.name: r for r in project.roles}
    for spec in role:
        rname, user, pw = _parse_role(spec)
        register_secret(pw)
        ref = f"role:{rname}"
        roles[rname] = Role(name=rname, login_strategy="credentials", secret_ref=ref, login_url=login_url)
        repo.update_secret(project.slug, ref, {"username": user, "password": pw})
    for rname in manual_login:
        console.print(
            f"[bold]Manual login for role '{rname}':[/] a Chrome window will open. Log in, then press Enter here."
        )
        saved = auth.capture_manual_session(
            login_url or url,
            _wait_for_enter,
            width=settings["browser"]["window_width"],
            height=settings["browser"]["window_height"],
        )
        repo.update_secret(project.slug, f"session:{rname}", saved)
        roles[rname] = Role(name=rname, login_strategy="manual_session", secret_ref=f"session:{rname}")
    project.roles = list(roles.values())
    if max_pages:
        project.scope.max_pages = max_pages
    if max_depth:
        project.scope.max_depth = max_depth
    repo.save_project(project)

    run_obj = repo.create_run(Run(id=repo.new_run_id(project.slug), project_slug=project.slug, mode=mode))  # type: ignore[arg-type]
    tracker = RunTracker(repo, run_obj)
    if not AIClient.available():
        console.print(
            "[yellow]No ANTHROPIC_API_KEY set:[/] exploring with heuristics and classifying offline."
        )

    try:
        with Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as bar:
            task = bar.add_task("Exploring", total=100)
            tracker.listeners.append(
                lambda e: (
                    bar.update(
                        task,
                        completed=e.get("overall", bar.tasks[0].completed),
                        description=(e.get("message") or "Working")[:70],
                    )
                    if e["type"] in ("progress", "stage_done")
                    else None
                )
            )
            with heartbeat(tracker):
                pipeline.execute(repo, tracker, {"headless": not headed and settings["browser"]["headless"]})
    except KeyboardInterrupt:
        tracker.cancel()
        console.print("[yellow]Cancelled.[/]")
        raise typer.Exit(130) from None

    if tracker.run.status != "completed":
        console.print(f"[red]Run {tracker.run.status}:[/] {tracker.run.error}")
        raise typer.Exit(1)
    crawl = repo.load_run_doc(run_obj, PAGES_FILE, CrawlResult)
    findings = repo.load_run_doc(run_obj, FINDINGS_FILE, FindingsDoc)
    profile = repo.load_run_doc(run_obj, PROFILE_FILE, SiteProfile)
    _print_summary(crawl, findings)
    console.print(
        f"\n[bold]Detected:[/] {profile.domain} · {profile.sub_type} "
        f"({profile.confidence:.0%}, {'Claude' if profile.method == 'ai' else 'offline heuristic'})"
    )
    console.print(f"Entities: {', '.join(e.name for e in profile.entities) or '—'}")
    report = repo.run_path(run_obj, REPORT_FILE)
    console.print(f"\n[bold green]Done.[/] Workspace: {repo.run_dir(project.slug, run_obj.id)}")
    console.print(f"Report: {report}")
    if open_report:
        webbrowser.open(report.as_uri())


def _print_summary(crawl: CrawlResult, findings: FindingsDoc) -> None:
    roles = Table(title="Roles", show_lines=False)
    for col in ("Role", "Login", "Pages", "Note"):
        roles.add_column(col)
    for r in crawl.roles:
        status = "-" if r.login_ok is None else ("[green]ok[/]" if r.login_ok else "[red]failed[/]")
        roles.add_row(r.role, status, str(r.pages), r.login_message)
    console.print(roles)
    table = Table(title=f"Findings ({len(findings.findings)})")
    for col in ("ID", "Severity", "Title", "Page", "Seen"):
        table.add_column(col, overflow="fold")
    for f in findings.findings[:40]:
        table.add_row(
            f.id,
            f"[{SEVERITY_STYLE[f.severity]}]{f.severity}[/]",
            f.title,
            f.page_url,
            str(f.data.get("occurrences", 1)),
        )
    console.print(table)
    if crawl.blocked_actions:
        console.print(
            f"Safe Mode blocked {len(crawl.blocked_actions)} action(s), e.g. "
            + "; ".join(f"{b['target']} ({b['reason']})" for b in crawl.blocked_actions[:3])
        )


def _latest_run(repo: Repository, slug: str, run_id: str | None) -> Run:
    try:
        repo.get_project(slug)
        if run_id:
            return repo.get_run(slug, run_id)
        runs = repo.list_runs(slug)
    except NotFoundError as exc:
        console.print(f"[red]Not found:[/] {exc}")
        raise typer.Exit(1) from exc
    if not runs:
        console.print(f"[red]{slug} has no runs yet.[/] Start one with `cli.py run <url>`.")
        raise typer.Exit(1)
    return runs[0]


@app.command()
def review(
    slug: str,
    run_id: str = typer.Option(None, "--run", help="Run id (default: latest)"),
    confirm_rules: float = typer.Option(
        None, help="Confirm proposed business rules with at least this confidence (0–1), then redesign tests"
    ),
    approve: str = typer.Option(
        None, help="'all' approves every draft test case; or a comma-separated list of techniques"
    ),
) -> None:
    """Do the review step from the command line: confirm rules, redesign tests, approve test cases."""
    from app.requirements.stage import REQUIREMENTS_FILE
    from app.storage.schemas import RequirementsDoc, TestSuite
    from app.testdesign.stage import TESTCASES_FILE, design_suite

    repo = Repository()
    run_obj = _latest_run(repo, slug, run_id)
    if confirm_rules is not None:

        def confirm(doc: RequirementsDoc) -> int:
            n = 0
            for rule in doc.rules:
                if rule.status == "proposed" and rule.confidence >= confirm_rules:
                    rule.status, n = "confirmed", n + 1
            return n

        n = repo.update_run_doc(run_obj, REQUIREMENTS_FILE, RequirementsDoc, confirm)
        console.print(f"Confirmed {n} business rules (confidence ≥ {confirm_rules:.0%}). Redesigning tests…")
        ai = AIClient(usage=run_obj.token_usage) if AIClient.available() else None
        suite = design_suite(
            repo,
            run_obj,
            repo.load_run_doc(run_obj, PAGES_FILE, CrawlResult),
            repo.load_run_doc(run_obj, PROFILE_FILE, SiteProfile),
            repo.load_run_doc(run_obj, REQUIREMENTS_FILE, RequirementsDoc),
            ai,
        )
        repo.save_run(run_obj)  # keeps the Claude usage of the redesign
        console.print(f"{len(suite.cases)} test cases designed.")
    if approve:
        wanted = None if approve == "all" else {t.strip() for t in approve.split(",")}

        def approve_cases(suite: TestSuite) -> int:
            n = 0
            for case in suite.cases:
                if case.status == "draft" and (wanted is None or case.technique in wanted):
                    case.status, n = "approved", n + 1
            return n

        n = repo.update_run_doc(run_obj, TESTCASES_FILE, TestSuite, approve_cases)
        console.print(f"Approved {n} test cases.")


@app.command()
def execute(
    slug: str,
    run_id: str = typer.Option(None, "--run", help="Run id (default: latest)"),
    viewport: list[str] = typer.Option(["desktop"], help="desktop | tablet | mobile (repeatable)"),
    resume: bool = typer.Option(False, help="Keep tests that already finished; run the rest"),
    headed: bool = typer.Option(False, "--headed", help="Show the browsers"),
) -> None:
    """Run the approved test cases (stage 6) and verify failures into bug reports (stage 7)."""
    from app.execute.stage import execute_job

    repo = Repository()
    setup_logging(log_file=repo.root / "logs" / "qa-pilot.log")
    run_obj = _latest_run(repo, slug, run_id)
    tracker = RunTracker(repo, run_obj)
    tracker.listeners.append(
        lambda e: (
            console.print(f"[dim]{e.get('message', '')[:110]}[/]")
            if e["type"] in ("progress", "stage_done") and e.get("message")
            else None
        )
    )
    try:
        with heartbeat(tracker):
            execute_job(repo, tracker, {"resume": resume, "viewports": viewport, "headless": not headed})
    except KeyboardInterrupt:
        tracker.cancel()
        console.print("[yellow]Cancelled — resume later with --resume.[/]")
        raise typer.Exit(130) from None
    run_obj = repo.get_run(slug, run_obj.id)
    summary = next((s for s in repo.get_index(slug).runs if s.id == run_obj.id), None)
    console.print(
        f"[bold]{run_obj.status}[/] · {run_obj.stages['execute'].message} · {run_obj.stages['verify'].message}"
        + (f" · quality {summary.quality_score:g}" if summary and summary.quality_score is not None else "")
    )
    if run_obj.status != "completed":
        raise typer.Exit(1)


EXPORT_KINDS = [
    "qa_report_pdf",
    "qa_xlsx",
    "bugs_pdf",
    "jira_csv",
    "trello_csv",
    "traceability_csv",
    "pytest_zip",
]


@app.command()
def export(
    slug: str,
    run_id: str = typer.Option(None, "--run", help="Run id (default: latest)"),
    kind: list[str] = typer.Option(None, help=f"Repeatable: {', '.join(EXPORT_KINDS)} (default: all)"),
) -> None:
    """Write reports into the run's exports/ folder."""
    from app.reports import csv_export, pytest_export, qa_report, qa_workbook
    from app.reports import data as report_data

    repo = Repository()
    run_obj = _latest_run(repo, slug, run_id)
    d = report_data.load(repo, repo.get_project(slug), run_obj)
    for k in kind or EXPORT_KINDS:
        if k == "qa_xlsx":
            path = qa_workbook.export(repo, d)
        elif k == "pytest_zip":
            path = pytest_export.export(repo, d)
        elif k.endswith("_csv"):
            path = csv_export.export(repo, d, k.removesuffix("_csv"))
        elif k in ("qa_report_pdf", "bugs_pdf"):
            path = qa_report.export(repo, d, "full" if k == "qa_report_pdf" else "bugs")
        else:
            console.print(f"[red]Unknown kind {k}[/]")
            raise typer.Exit(2)
        console.print(f"{k}: {path}")


@app.command()
def projects() -> None:
    """List projects in the workspace."""
    repo = Repository()
    table = Table(title="Projects")
    for col in ("Slug", "Name", "URL", "Env", "Roles", "Runs"):
        table.add_column(col)
    for p in repo.list_projects():
        table.add_row(
            p.slug,
            p.name,
            p.url,
            p.environment,
            ", ".join(r.name for r in p.roles) or "-",
            str(len(repo.get_index(p.slug).runs)),
        )
    console.print(table)


@app.command()
def runs(slug: str) -> None:
    """List runs of a project."""
    repo = Repository()
    table = Table(title=f"Runs · {slug}")
    for col in ("Run", "Mode", "Status", "Stage", "Pages", "Findings", "Cost $"):
        table.add_column(col)
    for s in repo.get_index(slug).runs:
        table.add_row(s.id, s.mode, s.status, s.stage, str(s.pages), str(s.findings), f"{s.cost_usd:.3f}")
    console.print(table)


@app.command()
def report(slug: str, run_id: str, open_report: bool = typer.Option(False, "--open")) -> None:
    """Re-render the HTML crawl report of an existing run."""
    repo = Repository()
    try:
        project, run_obj = repo.get_project(slug), repo.get_run(slug, run_id)
        crawl = repo.load_run_doc(run_obj, PAGES_FILE, CrawlResult)
        findings = repo.load_run_doc(run_obj, FINDINGS_FILE, FindingsDoc)
    except NotFoundError as exc:
        console.print(f"[red]Not found:[/] {exc}")
        raise typer.Exit(1) from exc
    path = render_crawl_report(repo, project, run_obj, crawl, findings)
    console.print(f"Report: {path}")
    if open_report:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    app()
