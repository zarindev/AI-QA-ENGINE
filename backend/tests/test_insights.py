from __future__ import annotations

import io

import pytest
from PIL import Image

from app.execute import privacy
from app.execute.stage import expand_viewports
from app.storage.schemas import (
    Bug,
    CrawlResult,
    Execution,
    PageRecord,
    ResultsDoc,
    RoleCrawlSummary,
    StepResult,
    TestCase,
    TestRunResult,
    TestSuite,
)
from app.verify import insights
from app.verify.rule_check import UnsafeExpression, safe_eval


def _res(cid, technique, result, module="Billing"):
    return TestRunResult(test_case_id=cid, technique=technique, result=result, module=module)


def test_quality_score_formula():
    results = ResultsDoc(
        results=[
            _res("TC-1", "crud", "pass"),
            _res("TC-2", "crud", "fail"),
            _res("TC-3", "permission", "pass"),
            _res("TC-4", "accessibility", "blocked"),  # blocked tests are not measured
        ]
    )
    bugs = [
        Bug(id="BUG-001", title="Total wrong", severity="major", category="calculation"),
        Bug(id="BUG-002", title="Rejected", severity="critical", category="permission", status="rejected"),
    ]
    crawl = CrawlResult(
        start_url="http://x.test",
        pages=[
            PageRecord(id=f"p{i}", url=f"http://x.test/{i}", url_template=f"/{i}", load_time_ms=ms)
            for i, ms in enumerate([500, 800, 4000, 900])
        ],
    )
    q = insights.quality(results, bugs, crawl, slow_ms=3000)
    sub = {s.key: s for s in q.sub_scores}
    assert sub["functional"].score == 38.0  # 50 % pass rate − 12 for the open major bug
    assert sub["permissions"].score == 100.0  # the rejected critical bug does not count
    assert sub["performance"].score == 75.0  # 1 of 4 pages slow
    assert sub["accessibility"].score is None and sub["ui"].score is None
    # weighted over measured categories only: (30·38 + 20·100 + 10·75) / 60
    assert q.score == round((30 * 38 + 20 * 100 + 10 * 75) / 60, 1) and q.grade == "C"


def test_heatmap_states():
    suite = TestSuite(
        cases=[
            TestCase(id="TC-1", title="a", module="Billing", technique="crud"),
            TestCase(id="TC-2", title="b", module="Billing", technique="crud"),
            TestCase(id="TC-3", title="c", module="Patients", technique="validation"),
            TestCase(id="TC-4", title="d", module="Patients", technique="permission"),
        ]
    )
    results = ResultsDoc(
        results=[
            _res("TC-1", "crud", "pass"),
            _res("TC-2", "crud", "fail"),
            _res("TC-3", "validation", "pass"),
        ]
    )
    heat = insights.heatmap(suite, results)
    cells = {(c.module, c.technique): c.state for c in heat.cells}
    assert cells == {
        ("Billing", "crud"): "fail",
        ("Patients", "validation"): "pass",
        ("Patients", "permission"): "untested",
    }
    assert heat.modules == ["Billing", "Patients"] and heat.techniques == ["crud", "validation", "permission"]


def test_permission_matrix_finds_holes():
    crawl = CrawlResult(
        start_url="http://x.test",
        roles=[RoleCrawlSummary(role="admin", login_ok=True), RoleCrawlSummary(role="doctor", login_ok=True)],
        pages=[
            PageRecord(id="1", role="admin", url="http://x.test/reports", url_template="/reports"),
            PageRecord(id="2", role="admin", url="http://x.test/patients", url_template="/patients"),
            PageRecord(id="3", role="doctor", url="http://x.test/patients", url_template="/patients"),
        ],
    )
    suite = TestSuite(
        cases=[TestCase(id="TC-P1", title="doctor /reports", technique="permission", role="doctor")]
    )
    ex = Execution(
        test_case_id="TC-P1",
        result="fail",
        role="doctor",
        steps=[
            StepResult(
                order=1, action="navigate", target="/reports", result="fail", observation="Report opened"
            )
        ],
    )
    view = insights.permission_matrix(crawl, suite, {"TC-P1": ex})
    cell = {(c.role, c.page): c for c in view.cells}
    assert cell[("doctor", "/reports")].hole and cell[("doctor", "/reports")].observed == "allow"
    assert cell[("admin", "/reports")].expected == "allow" and not cell[("admin", "/reports")].hole
    assert view.holes == 1


def test_regression_compare():
    def bug(i, key, status="new"):
        return Bug(id=f"BUG-{i:03d}", title=key, symptom_key=key, status=status)

    current = [bug(1, "a"), bug(2, "b"), bug(3, "c")]
    base = [bug(1, "a"), bug(2, "d")]
    older = [[bug(1, "c")]]
    cmp = insights.compare("r2", current, "r1", base, older)
    status = {b.key: b.status for b in cmp.bugs}
    assert status == {"a": "still_open", "b": "new", "c": "reappeared", "d": "fixed"}
    assert cmp.counts == {"new": 1, "fixed": 1, "reappeared": 1, "still_open": 1}


def test_safe_eval_allows_arithmetic_and_refuses_code():
    assert safe_eval("pays == round(fee * (1 - pct / 100), 2)", {"pays": 60.0, "fee": 120.0, "pct": 50.0})
    assert not safe_eval("pays == fee * 0.5", {"pays": 120.0, "fee": 120.0})
    assert safe_eval("total == 10.004", {"total": 10.0})  # 2-decimal money tolerance
    for bad in ("__import__('os').system('x')", "fee.real", "[1, 2]", "2 ** 10", "missing > 1"):
        with pytest.raises((UnsafeExpression, SyntaxError)):
            safe_eval(bad, {"fee": 1.0})


def test_privacy_blur_changes_only_the_marked_region(tmp_path):
    img = Image.new("RGB", (200, 100), (255, 255, 255))
    for x in range(20, 80, 4):  # a striped "name" so blurring is visible
        for y in range(20, 40):
            img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    path = tmp_path / "shot.png"
    path.write_bytes(buf.getvalue())
    privacy.sidecar(path).write_text(
        '{"width": 100, "rects": [{"x": 10, "y": 10, "width": 40, "height": 20}]}', encoding="utf-8"
    )
    # screenshot is 200px wide; the sidecar says the viewport was 100px (device pixel ratio 2) → rect is scaled
    out = Image.open(io.BytesIO(privacy.blurred_bytes(path))).convert("RGB")
    assert out.getpixel((20, 30)) != (0, 0, 0)  # inside: blurred
    assert out.getpixel((150, 80)) == (255, 255, 255)  # outside: untouched
    privacy.sidecar(path).unlink()
    assert privacy.blurred_bytes(path, 100) == path.read_bytes()  # no regions → original bytes


def test_privacy_default_follows_domain_unless_set():
    class P:
        privacy_blur = None

    assert privacy.privacy_enabled(P(), "healthcare") is True
    assert privacy.privacy_enabled(P(), "ecommerce") is False
    P.privacy_blur = False
    assert privacy.privacy_enabled(P(), "healthcare") is False


def test_viewport_expansion():
    cases = [
        TestCase(id="TC-1", title="Create invoice", technique="crud"),
        TestCase(id="TC-2", title="Layout", technique="ui_responsive", viewports=["tablet", "mobile"]),
    ]
    out = expand_viewports(cases, ["desktop", "mobile"])
    assert [c.id for c in out] == ["TC-1", "TC-1@mobile", "TC-2"]
    assert out[1].viewports == ["mobile"] and out[1].title == "Create invoice (mobile)"
    assert [c.id for c in expand_viewports(cases, ["tablet"])] == ["TC-1@tablet"]
