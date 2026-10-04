from __future__ import annotations

from app.explore import urls
from app.explore.checks import FindingCollector, check_page
from app.storage.schemas import ConsoleEntry, NetworkEvent, PageRecord


def test_normalize_drops_tracking_and_fragments():
    n = urls.normalize("HTTPS://Shop.Example.test:443/items/?utm_source=x&b=2&a=1#top", ["utm_source"])
    assert n == "https://shop.example.test/items/?a=1&b=2"
    assert urls.normalize("http://h.test:8080/a") == "http://h.test:8080/a"


def test_templates_group_record_pages():
    assert (
        urls.template("https://h.test/patients/12")
        == urls.template("https://h.test/patients/13")
        == "/patients/{id}"
    )
    assert urls.template("https://h.test/item?id=4") == "/item?id={id}"
    assert urls.template("https://h.test/o/550e8400-e29b-41d4-a716-446655440000") == "/o/{uuid}"
    assert urls.template("https://h.test/p/blue-shirt-1234") == "/p/{slug}"
    assert urls.template("https://h.test/reports/2026-01-31") == "/reports/{date}"


def test_scope():
    s = urls.Scope("https://app.example.test/", exclude=[r"\.pdf$"])
    assert s.allows("https://app.example.test/x")
    assert not s.allows("https://evil.test/x")
    assert not s.allows("https://app.example.test/manual.pdf")
    assert not s.allows("mailto:a@b.test")
    only = urls.Scope("https://app.example.test/", include=[r"/admin/"])
    assert only.allows("https://app.example.test/admin/users") and not only.allows(
        "https://app.example.test/blog"
    )


def _page(**kw) -> PageRecord:
    base = dict(id="PG-0001", url="https://h.test/a", url_template="/a", role="public", status_code=200)
    base.update(kw)
    return PageRecord(**base)


def test_check_page_detects_common_problems():
    page = _page(
        status_code=500,
        load_time_ms=4500,
        text_excerpt="Traceback (most recent call last): File x",
        console=[
            ConsoleEntry(level="error", message="Uncaught TypeError: x is undefined"),
            ConsoleEntry(level="error", message="https://h.test/a.png - Failed to load resource: 404"),
        ],
        failed_requests=[
            NetworkEvent(url="https://h.test/api/list", status=500, resource_type="XHR"),
            NetworkEvent(
                url="https://cdn.other.test/lib.js",
                error="net::ERR_NAME_NOT_RESOLVED",
                resource_type="Script",
            ),
            NetworkEvent(url="https://h.test/favicon.ico", status=404, resource_type="Other"),
        ],
    )
    raws = check_page(
        page, broken_images=["https://h.test/logo.png"], overflow_x=300, slow_page_ms=3000, site_host="h.test"
    )
    by_check = {r.check: r for r in raws}
    assert by_check["http_error"].severity == "critical"
    assert by_check["js_error"].severity == "major"
    assert (
        sum(r.check == "js_error" for r in raws) == 1
    )  # "Failed to load resource" is left to the network check
    assert {r.severity for r in raws if r.check == "failed_request"} == {"major", "trivial"}
    assert any("Third-party" in r.title for r in raws) and any("favicon" in r.title for r in raws)
    for check in ("broken_image", "slow_page", "horizontal_overflow", "error_text"):
        assert check in by_check


def test_auth_required_is_trivial_not_a_bug():
    raws = check_page(_page(status_code=401), broken_images=[], overflow_x=0, slow_page_ms=3000)
    assert [(r.check, r.severity) for r in raws] == [("auth_required", "trivial")]


def test_collector_deduplicates_symptoms_across_pages():
    c = FindingCollector()
    err = ConsoleEntry(level="error", message="Uncaught ReferenceError: foo is not defined at line 12")
    for i, role in enumerate(["public", "admin", "admin"]):
        p = _page(
            id=f"PG-{i}",
            url=f"https://h.test/p{i}",
            role=role,
            console=[ConsoleEntry(level="error", message=err.message.replace("12", str(i + 30)))],
        )
        c.add(p, check_page(p, broken_images=[], overflow_x=0, slow_page_ms=3000))
    findings = c.findings()
    assert len(findings) == 1
    assert findings[0].data["occurrences"] == 3 and findings[0].role == "admin, public"
    assert findings[0].id == "F-001"


def test_mixed_content_and_shared_overflow_are_single_symptoms():
    c = FindingCollector()
    msg = (
        "https://h.test/{p} - Mixed Content: The page at 'https://h.test/{p}' was loaded over HTTPS, but requested "
        "an insecure stylesheet 'http://fonts.example.test/css'. This request has been blocked."
    )
    for i in range(3):
        p = _page(
            id=f"PG-{i}",
            url=f"https://h.test/brand/{i}x",
            url_template=f"/brand/{i}x",
            console=[ConsoleEntry(level="error", message=msg.format(p=i))],
        )
        c.add(p, check_page(p, broken_images=[], overflow_x=488, slow_page_ms=3000))
    checks = sorted((f.check, f.data["occurrences"]) for f in c.findings())
    assert checks == [("horizontal_overflow", 3), ("mixed_content", 3)]


def test_405_and_403_links_are_not_broken():
    c = FindingCollector()
    src = _page()
    c.add_broken_link(src, "https://h.test/api/create", 405)
    c.add_broken_link(src, "https://h.test/admin", 403)
    c.add_broken_link(src, "https://h.test/gone", 404)
    assert [f.data["status"] for f in c.findings()] == [404]


def test_error_text_not_double_reported_on_error_status():
    raws = check_page(
        _page(status_code=404, text_excerpt="Page not found."),
        broken_images=[],
        overflow_x=0,
        slow_page_ms=3000,
    )
    assert [r.check for r in raws] == ["http_error"]
