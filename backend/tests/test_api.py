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
    assert all(state["available"].values())
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
