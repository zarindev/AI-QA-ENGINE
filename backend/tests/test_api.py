from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from .conftest import requires_chrome


@pytest.fixture
def client(isolated_workspace):
    from app.api import deps

    deps.repo.cache_clear()
    deps.executor.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    deps.executor().shutdown()
    deps.repo.cache_clear()
    deps.executor.cache_clear()


def _project(client, url, **kw):
    body = {"url": url, "authorized": True, "authorized_by": "pytest", "environment": "test", **kw}
    return client.post("/api/projects", json=body)


def test_health_and_settings(client):
    h = client.get("/api/health").json()
    assert h["api_key"] is False and h["model"] == "claude-sonnet-5-5"
    r = client.put("/api/settings", json={"crawl": {"max_pages": 12}})
    assert r.status_code == 200 and r.json()["crawl"]["max_pages"] == 12
    assert client.get("/api/settings").json()["crawl"]["max_pages"] == 12
    assert client.put("/api/settings", json={"server": {"port": 1}}).status_code == 400
    assert client.post("/api/settings/api-key", json={"key": "not-a-key"}).status_code == 400


def test_project_requires_authorization_and_hides_secrets(client, isolated_workspace):
    body = {"url": "shop.example.test", "authorized": False, "authorized_by": "me"}
    assert client.post("/api/projects", json=body).status_code == 400
    r = _project(
        client,
        "shop.example.test",
        name="Shop",
        roles=[
            {"name": "Admin", "username": "a@x.test", "password": "pw-secret-1"},
            {"name": "staff", "login_strategy": "manual_session"},
        ],
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["url"] == "https://shop.example.test" and p["authorized_by"] == "pytest"
    assert [x["name"] for x in p["roles"]] == ["admin", "staff"]
    assert "pw-secret-1" not in r.text
    for f in isolated_workspace.rglob("*.json"):
        assert "pw-secret-1" not in f.read_text()
    assert _project(client, "x.test", roles=[{"name": "a", "username": "u"}]).status_code == 400
    assert (
        _project(client, "x.test", roles=[{"name": "public", "username": "u", "password": "p"}]).status_code
        == 400
    )
    assert [x["slug"] for x in client.get("/api/projects").json()] == ["shop"]
    assert client.get("/api/projects/nope").status_code == 404


def test_full_mode_rules(client):
    slug = _project(client, "prod.example.test", environment="production").json()["slug"]
    assert client.post(f"/api/projects/{slug}/runs", json={"mode": "full"}).status_code == 400
    slug2 = _project(client, "stage.example.test", environment="staging").json()["slug"]
    r = client.post(f"/api/projects/{slug2}/runs", json={"mode": "full"})
    assert r.status_code == 400 and "Confirm" in r.json()["detail"]


def test_spa_fallback_and_api_404(client):
    assert client.get("/api/nothing-here").status_code == 404
    assert client.get("/projects/abc").status_code in (200, 503)  # index.html once the UI is built


@pytest.mark.browser
@requires_chrome
def test_run_pipeline_end_to_end(client, fixture_site, settings):
    client.put("/api/settings", json={"crawl": {"rate_limit_s": 0}})
    slug = _project(
        client,
        f"{fixture_site}/index.html",
        name="Fixture Clinic",
        max_pages=15,
        roles=[
            {
                "name": "doctor",
                "username": "doc@example.test",
                "password": "Sup3r-Secret!",
                "login_url": f"{fixture_site}/login.html",
            }
        ],
    ).json()["slug"]
    run = client.post(f"/api/projects/{slug}/runs", json={"mode": "safe"})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    assert client.post(f"/api/projects/{slug}/runs", json={}).status_code == 409  # one run at a time
    deadline = time.time() + 240
    state = {}
    while time.time() < deadline:
        state = client.get(f"/api/projects/{slug}/runs/{run_id}").json()
        if not state["running"] and state["status"] != "pending":
            break
        time.sleep(1)
    assert state["status"] == "completed", state.get("error")
    assert all(v for k, v in state["available"].items() if k not in ("results", "bugs"))
    assert (
        state["stages"]["understand"]["status"] == "done"
        and state["stages"]["execute"]["status"] == "skipped"
    )

    profile = client.get(f"/api/projects/{slug}/runs/{run_id}/profile").json()
    # A 9-page fixture has too little evidence for a confident offline verdict; healthcare must still rank first.
    assert profile["method"] == "heuristic" and next(iter(profile["domain_scores"])) == "healthcare"
    model = client.get(f"/api/projects/{slug}/runs/{run_id}/model").json()
    kinds = {n["type"] for n in model["nodes"]}
    assert {"role", "page"} <= kinds and model["edges"]
    graph = client.get(f"/api/projects/{slug}/runs/{run_id}/model?view=graph").json()
    assert graph["schema_version"] == 1 and graph["stats"]["page"] >= 5

    pages = client.get(f"/api/projects/{slug}/runs/{run_id}/pages").json()
    first = pages["pages"][0]
    assert "elements" not in first and first["element_count"] >= 1
    detail = client.get(f"/api/projects/{slug}/runs/{run_id}/pages/{first['id']}").json()
    assert "elements" in detail
    shot = client.get(f"/api/projects/{slug}/runs/{run_id}/files/{first['thumbnail']}")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/projects/{slug}/runs/{run_id}/files/../../project.json").status_code == 404
    findings = client.get(f"/api/projects/{slug}/runs/{run_id}/findings").json()["findings"]
    assert any(f["check"] == "js_error" for f in findings)

    with client.stream("GET", f"/api/projects/{slug}/runs/{run_id}/events") as events:
        body = "".join(chunk for chunk in events.iter_text())
    assert "event: history" in body and "run_completed" in body and "event: state" in body
    listing = client.get(f"/api/projects/{slug}/runs").json()
    assert listing[0]["id"] == run_id and listing[0]["domain"] == profile["domain"]

    # Execute: rule-runner cases need no AI. Agent cases are reported as blocked without an API key.
    base = f"/api/projects/{slug}/runs/{run_id}"
    cases = client.get(f"{base}/testcases").json()["cases"]
    chosen = [c["id"] for c in cases if c["technique"] in ("smoke", "permission", "ui_responsive")][:6]
    chosen += [c["id"] for c in cases if c["technique"] == "crud"][:1]
    assert client.post(f"{base}/execute", json={"case_ids": chosen}).status_code == 202
    deadline = time.time() + 300
    while time.time() < deadline and client.get(base).json()["running"]:
        time.sleep(1)
    state = client.get(base).json()
    assert state["status"] == "completed", state.get("error")
    results = {r["test_case_id"]: r for r in client.get(f"{base}/results").json()["results"]}
    assert set(results) == set(chosen)
    crud = next(r for r in results.values() if r["technique"] == "crud")
    assert crud["result"] == "blocked"  # Safe Mode run + no AI key
    smoke = [r for r in results.values() if r["technique"] == "smoke"]
    assert smoke and any(r["result"] == "fail" for r in smoke)  # about.html throws a JS error
    failed = [r for r in results.values() if r["result"] == "fail"]
    assert all(r["reproducibility"] == "3/3" for r in failed)  # re-run twice by the rule runner
    bugs = client.get(f"{base}/bugs").json()["bugs"]
    assert bugs and all(
        b["id"].startswith("BUG-") and b["steps_to_reproduce"] and b["expected"] for b in bugs
    )
    js = next(b for b in bugs if b["category"] == "js_error")
    assert (
        js["annotated_screenshot"]
        and client.get(f"{base}/files/{js['annotated_screenshot']}").status_code == 200
    )
    ex = client.get(f"{base}/executions/{failed[0]['test_case_id']}").json()
    assert len(ex["attempts"]) == 3 and ex["attempts"][0]["steps"][0]["screenshot_after"].endswith(".jpg")
    upd = client.patch(f"{base}/bugs/{js['id']}", json={"status": "confirmed"}).json()
    assert upd["status"] == "confirmed"
