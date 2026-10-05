"""Export the approved tests as a stand-alone pytest + Selenium suite (Page Object Model).

- Recorded tests come from the replay scripts (`replay/<TC>.json`) of the agent runs: every click / type / select
  uses the multi-strategy locator QA Pilot recorded, grouped into one page object per module.
- Assertions are concrete text, never AI: for a test that passed, quoted text and amounts the agent saw that are on
  the final page; for a test that failed, the expected values that were missing — so the exported test keeps
  failing until the bug is fixed.
- Rule-based tests (smoke, permission, responsive, accessibility) are re-implemented in plain Selenium.
- Credentials are never written: tests read QAP_<ROLE>_USERNAME / QAP_<ROLE>_PASSWORD from the environment.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from app import __version__
from app.core.paths import APP_DIR
from app.reports.data import ReportData
from app.storage.repository import Repository
from app.storage.schemas import Execution, ExecutionsDoc, LocatorSet, ReplayScript, TestCase

SUITE_DIR = "exports/pytest_suite"
SUITE_ZIP = "exports/pytest_suite.zip"
STATIC = APP_DIR / "reports" / "pytest_suite"
FIXTURE = APP_DIR / "execute" / "fixtures" / "qap-test-upload.txt"
VIEWPORTS = {"tablet": (768, 1024), "mobile": (390, 844), "desktop": (1440, 900)}

ERROR_PAGE = re.compile(
    r"Internal Server Error|Traceback \(most recent call last\)|\b(Fatal error|Parse error):|SQLSTATE\[|"
    r"Uncaught \w*Exception|\b(404|Page) Not Found\b|Something went wrong|\[object Object\]|\bNaN\b",
    re.I,
)
# Browser-native validation bubbles are not page text, so they cannot be asserted with Selenium.
NATIVE = re.compile(
    r"^(please (fill|select|enter|include|match|use)|value must|constraints not satisfied)", re.I
)
NEGATED = re.compile(
    r"\b(no|not|never|without|hidden|absent|disappears?|instead of|rather than|nor|cannot|can't|isn't|aren't)\b[^.;]*$",
    re.I,
)
QUOTED = re.compile(r"[“\"]([^”\"\n]{2,80})[”\"]")
MONEY = re.compile(r"(?<![\w.])\$?\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)")


def _slug(text: str, n: int = 40) -> str:
    return re.sub(r"_+", "_", re.sub(r"\W", "_", text.lower())).strip("_")[:n].strip("_") or "x"


def _const(text: str) -> str:
    c = re.sub(r"_+", "_", re.sub(r"\W", "_", text.upper())).strip("_")[:40].strip("_")
    return c if c and not c[0].isdigit() else f"EL_{c}"


def _class(module: str) -> str:
    return "".join(p.capitalize() for p in re.split(r"\W+", module) if p) + "Page" if module else "AppPage"


def _path(url: str, base: str) -> str:
    u, b = urlparse(url), urlparse(base)
    if u.netloc and u.netloc != b.netloc:
        return url
    return (u.path or "/") + (f"?{u.query}" if u.query else "")


def expectations(case: TestCase, ex: Execution | None) -> tuple[list[str], str]:
    """Concrete strings to assert, and a note on where they came from."""
    if ex is None:
        return [], ""
    # Older runs did not store the final page text; then what the agent quoted in its last check stands in.
    asserts = [st.observation for st in ex.steps if st.action == "assert"]
    page = ex.final_page_text or (asserts[-1] if asserts else "")
    if not page:
        return [], ""
    sources = [ex.expected, case.expected_result] if ex.result == "fail" else [ex.actual, ex.expected]
    found: list[str] = []
    for text in sources:
        text = text or ""
        matches = [(m.start(1), m.group(1)) for m in QUOTED.finditer(text)]
        matches += [(m.start(), m.group(0)) for m in MONEY.finditer(text)]
        for pos, m in sorted(matches):
            s = m.strip().strip(".").strip()
            if len(s) < 2 or NATIVE.match(s) or any(s in f or f in s for f in found):
                continue
            if NEGATED.search(text[max(0, pos - 45) : pos]):
                continue  # "no 'Hand over car' button" — asserting the text would invert the check
            on_page = s in page
            if (ex.result == "fail" and not on_page) or (ex.result != "fail" and on_page):
                found.append(s)
    note = (
        "values QA Pilot expected but did not find (the test fails until the bug is fixed)"
        if ex.result == "fail"
        else "text QA Pilot saw on the final page"
    )
    return found[:4], note


@dataclass
class PageObject:
    module: str
    locators: dict[str, LocatorSet] = field(default_factory=dict)

    def name_for(self, loc: LocatorSet, target: str) -> str:
        for name, existing in self.locators.items():
            if existing == loc:
                return name
        label = re.findall(r"\"([^\"]+)\"", target)
        base = _const(
            " ".join(
                x
                for x in (
                    (
                        label[0]
                        if label
                        else (loc.text or loc.label or loc.aria_label or loc.name or loc.id or "element")
                    ),
                    loc.tag,
                )
                if x
            )
        )
        name, n = base, 2
        while name in self.locators:
            name, n = f"{base}_{n}", n + 1
        self.locators[name] = loc
        return name

    def source(self) -> str:
        lines = [
            '"""Locators recorded by QA Pilot for the ' + (self.module or "app") + ' module."""',
            "",
            "from pages.base import BasePage, Loc",
            "",
            "",
            f"class {_class(self.module)}(BasePage):",
        ]
        if not self.locators:
            lines.append("    pass")
        for name, loc in self.locators.items():
            fields = ", ".join(f"{k}={v!r}" for k, v in loc.model_dump().items() if v)
            lines.append(f"    {name} = Loc({fields})")
        return "\n".join(lines) + "\n"


def _clean(text: str) -> str:
    return text.replace('"""', "'''").replace("\\", "/")


def _docstring(case: TestCase, ex: Execution | None, bugs: list[str]) -> list[str]:
    out = [f'    """{_clean(case.id)} · {_clean(case.title)}', ""]
    if case.expected_result:
        out.append(f"    Expected: {_clean(case.expected_result)}")
    if ex is not None:
        out.append(f"    QA Pilot result: {ex.result}" + (f" ({', '.join(bugs)})" if bugs else ""))
        if ex.result == "fail" and ex.actual:
            out.append(f"    Seen: {_clean(ex.actual[:240])}")
    out.append('    """')
    return out


def _test(
    case: TestCase,
    script: ReplayScript | None,
    ex: Execution | None,
    page: PageObject,
    base: str,
    bugs: list[str],
) -> list[str]:
    marks = []
    if case.technique in ("smoke", "permission", "ui_responsive", "accessibility"):
        marks.append(case.technique.replace("ui_", ""))
    if case.requires_full_mode:
        marks.append("full_mode")
    head = [f"@pytest.mark.{m}" for m in marks]
    fixtures = "driver, base_url, login" + (", viewport" if case.technique == "ui_responsive" else "")
    head.append(f"def test_{_slug(case.id, 20)}_{_slug(case.title)}({fixtures}):")
    body = _docstring(case, ex, bugs)
    body.append(f"    page = {_class(page.module)}(driver, base_url)")
    role = script.role if script and script.role else case.role
    urls = [s.data for s in case.steps if s.data.startswith(("http://", "https://"))]

    if case.technique == "smoke" and script is None:
        body.append(f"    login({role!r})")
        for u in urls:
            body += [f"    page.open({_path(u, base)!r})", "    page.assert_no_error_page()"]
            if role not in ("", "public"):
                body.append("    assert not page.has_login_form(), 'redirected to the login page'")
    elif case.technique == "permission" and script is None:
        body.append(f"    login({role!r})")
        for u in urls:
            p = _path(u, base)
            body += [
                f"    page.open({p!r})",
                f"    refused, why = page.access_refused({urlparse(u).path or '/'!r})",
                f"    assert refused, f'{p} should be refused for {role or 'a signed-out visitor'} but {{why}}'",
            ]
    elif case.technique == "ui_responsive" and script is None:
        body.append(f"    login({role!r})")
        for vp in [v for v in case.viewports if v in VIEWPORTS and v != "desktop"] or ["mobile"]:
            w, h = VIEWPORTS[vp]
            body.append(f"    viewport({w}, {h})")
            for u in urls:
                body += [
                    f"    page.open({_path(u, base)!r})",
                    f"    assert page.overflow_x() <= 4, f'{_path(u, base)} is {{page.overflow_x()}}px wider than {w}px'",
                ]
    elif case.technique == "accessibility" and script is None:
        body += [
            "    axe_mod = pytest.importorskip('axe_selenium_python')",
            f"    login({role!r})",
            "    problems = []",
        ]
        for u in urls:
            body += [
                f"    page.open({_path(u, base)!r})",
                "    axe = axe_mod.Axe(driver)",
                "    axe.inject()",
                "    problems += [f\"{v['id']}: {v['help']}\" for v in axe.run()['violations'] if v['impact'] in ('critical', 'serious')]",
            ]
        body.append("    assert not problems, problems")
    elif script is not None and script.steps:
        body.append(f"    login({role!r})")
        for s in script.steps:
            if s.action == "navigate":
                body.append(f"    page.open({_path(s.url or s.input, base)!r})")
            elif s.action == "scroll":
                body.append(f"    page.scroll({(s.input or 'down')!r})")
            elif s.locators is not None:
                name = page.name_for(s.locators, s.target)
                if s.action == "type":
                    body.append(f"    page.type(page.{name}, {s.input!r})")
                elif s.action == "select":
                    body.append(f"    page.select(page.{name}, {s.input!r})")
                elif s.action in ("click", "check", "upload"):
                    body.append(f"    page.{s.action}(page.{name})")
        recorded = (
            ex.final_page_text or " ".join([*(st.observation for st in ex.steps[-2:]), ex.actual])
            if ex is not None
            else ""
        )
        shown = ERROR_PAGE.search(recorded)
        if shown:  # e.g. a refusal test that ends on "Page not found" — that page is the expected outcome
            body.append(f"    # the recorded final page showed “{shown.group(0)}”, as this test expects")
        else:
            body.append("    page.assert_no_error_page()")
        expected, note = expectations(case, ex)
        if expected:
            body.append(f"    # {note}")
            body.append("    page.assert_contains(" + ", ".join(repr(e) for e in expected) + ")")
        for check in (script.checks or [])[:3]:
            body.append(f"    # check by eye: {check[:150]}")
    else:
        body.append(
            "    pytest.skip('Not recorded yet: run this test in QA Pilot first, then export again.')"
        )
        for st in case.steps:
            body.append(f"    # {st.order}. {st.action}" + (f" [{st.data}]" if st.data else ""))
    return head + body


def _first(repo: Repository, d: ReportData, case_id: str) -> Execution | None:
    path = f"executions/{case_id}.json"
    if not repo.has_run_doc(d.run, path):
        return None
    attempts = repo.load_run_doc(d.run, path, ExecutionsDoc).attempts
    return attempts[0] if attempts else None


def build(repo: Repository, d: ReportData) -> dict[str, str | bytes]:
    """{relative path: content} for the whole suite."""
    files: dict[str, str | bytes] = {}
    base = d.project.url
    cases = [c for c in (d.suite.cases if d.suite else []) if c.status == "approved"]
    by_module: dict[str, list[TestCase]] = {}
    for c in cases:
        by_module.setdefault(c.module or "App", []).append(c)
    bugs_of: dict[str, list[str]] = {}
    for b in d.bugs:
        if b.status != "rejected":
            for tc in b.test_case_ids:
                bugs_of.setdefault(tc, []).append(b.id)

    recorded = 0
    for module, mcases in sorted(by_module.items()):
        page = PageObject(module)
        tests: list[list[str]] = []
        for c in mcases:
            script = (
                repo.load_run_doc(d.run, f"replay/{c.id}.json", ReplayScript)
                if repo.has_run_doc(d.run, f"replay/{c.id}.json")
                else None
            )
            recorded += script is not None
            tests.append(_test(c, script, _first(repo, d, c.id), page, base, bugs_of.get(c.id, [])))
        mod = _slug(module, 30)
        files[f"pages/{mod}.py"] = page.source()
        header = [
            f'"""{module} — generated by QA Pilot {__version__} from run {d.run.id} of {d.project.name}."""',
            "",
            "import pytest",
            "",
            f"from pages.{mod} import {_class(module)}",
        ]
        files[f"tests/test_{mod}.py"] = (
            "\n".join(header + [line for t in tests for line in ["", "", *t]]) + "\n"
        )

    login_paths = {
        r.name: _path(r.login_url, base) if r.login_url else "/"
        for r in d.project.roles
        if r.login_strategy == "credentials"
    }
    files["site_config.py"] = (
        '"""Where the site lives. Override with QAP_BASE_URL or `pytest --site URL`."""\n\n'
        f"DEFAULT_BASE_URL = {base.rstrip('/')!r}\n"
        f"LOGIN_PATHS = {login_paths!r}\n"
    )
    files["conftest.py"] = (STATIC / "conftest.py").read_text("utf-8")
    files["pages/__init__.py"] = ""
    files["tests/__init__.py"] = ""
    files["pages/base.py"] = (STATIC / "base.py").read_text("utf-8")
    files["pages/login.py"] = (STATIC / "login.py").read_text("utf-8")
    files["fixtures/qap-test-upload.txt"] = FIXTURE.read_bytes()
    files["requirements.txt"] = "selenium==4.50.0\npytest>=8.0\naxe-selenium-python==3.0.0\n"
    files["pytest.ini"] = (
        "[pytest]\ntestpaths = tests\naddopts = -ra\nmarkers =\n"
        "    smoke: page opens without errors\n    permission: a role must not open a screen\n"
        "    responsive: no horizontal scrolling on small screens\n    accessibility: axe-core critical/serious checks\n"
        "    full_mode: creates or changes data — run only against a test environment\n"
    )
    env_lines = [
        "# Copy to .env and fill in. Never commit .env.",
        f"QAP_BASE_URL={base.rstrip('/')}",
        "QAP_HEADLESS=1",
    ]
    for role in login_paths:
        key = re.sub(r"\W+", "_", role).strip("_").upper()
        env_lines += [f"QAP_{key}_USERNAME=", f"QAP_{key}_PASSWORD="]
    files[".env.example"] = "\n".join(env_lines) + "\n"
    files[".gitignore"] = ".env\n__pycache__/\n.pytest_cache/\n"
    files["README.md"] = _readme(d, len(cases), recorded, sorted(by_module), list(login_paths))
    return files


def _readme(d: ReportData, total: int, recorded: int, modules: list[str], roles: list[str]) -> str:
    keys = [re.sub(r"\W+", "_", r).strip("_").upper() for r in roles]
    env_win = "\n".join(f"set QAP_{k}_USERNAME=...\nset QAP_{k}_PASSWORD=..." for k in keys[:2])
    env_unix = "\n".join(f"export QAP_{k}_USERNAME=... QAP_{k}_PASSWORD=..." for k in keys[:2])
    return f"""# {d.project.name} — automated test suite

Generated by **QA Pilot {__version__}** from run `{d.run.id}` against {d.project.url}.
{total} approved test cases in {len(modules)} modules; {recorded} were recorded by QA Pilot's browser agent and
replay its exact actions, the rest are rule-based checks re-implemented in Selenium (or skipped when they have not
been recorded yet).

## Run it

Needs Python 3.10+ and Google Chrome.

```
python -m venv .venv
.venv\\Scripts\\activate          # Windows
source .venv/bin/activate        # macOS / Linux
pip install -r requirements.txt
```

Credentials are **not** included. Put them in a `.env` file (copy `.env.example`) or set them in the shell:

```
{env_win or 'rem no signed-in roles'}
```
```
{env_unix or '# no signed-in roles'}
```

Then:

```
pytest                         # everything
pytest -m "not full_mode"      # skip tests that create or change data
pytest --site https://staging.example.com
QAP_HEADLESS=0 pytest -k TC_PAT_001     # watch one test in a visible browser
```

## Layout

| Path | What it is |
|---|---|
| `pages/base.py` | Base page: multi-strategy locators (`Loc`), click / type / select / upload, text and error checks |
| `pages/login.py` | Generic login form handler |
| `pages/<module>.py` | One page object per module with the locators QA Pilot recorded |
| `tests/test_<module>.py` | One test per test case; the docstring links the test case and any bug |
| `site_config.py` | Base URL and each role's login page |

## Good to know

- Tests marked `full_mode` create, edit or delete records (named `QAP_…`, fake data). Run them only against a test
  or staging environment, and reset its data between runs when a test needs a clean state.
- A test for a bug QA Pilot found asserts the *expected* value, so it fails until the bug is fixed.
- `# check by eye:` comments are the checks QA Pilot judged visually; they are not automated here.
"""


def export(repo: Repository, d: ReportData) -> Path:
    files = build(repo, d)
    folder = repo.run_path(d.run, SUITE_DIR)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, content in sorted(files.items()):
            data = content.encode("utf-8") if isinstance(content, str) else content
            repo.write_bytes(folder / rel, data)
            z.writestr(f"qa_pilot_suite/{rel}", data)
    path = repo.run_path(d.run, SUITE_ZIP)
    repo.write_bytes(path, buf.getvalue())
    return path
