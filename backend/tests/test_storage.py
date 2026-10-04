from __future__ import annotations

import json
import threading

import pytest

from app.storage import migrations
from app.storage.repository import NotFoundError, Repository
from app.storage.schemas import (
    SCHEMA_VERSION,
    Finding,
    FindingsDoc,
    Project,
    Run,
    TestCase,
    TestSuite,
    utcnow,
)


def _project(repo: Repository, name: str = "Acme Clinic") -> Project:
    return repo.create_project(
        Project(
            slug=repo.unique_slug(name),
            name=name,
            url="https://clinic.example.test",
            authorized_by="tester",
            authorized_at=utcnow(),
        )
    )


def test_project_roundtrip_is_pretty_json_with_schema_version(repo):
    p = _project(repo)
    path = repo.project_dir(p.slug) / "project.json"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("{\n  ")  # pretty-printed, human readable
    data = json.loads(text)
    assert data["schema_version"] == SCHEMA_VERSION
    assert repo.get_project(p.slug) == p


def test_unique_slug_and_listing(repo):
    a = _project(repo, "Acme Clinic")
    b = _project(repo, "Acme Clinic")
    assert a.slug == "acme-clinic" and b.slug == "acme-clinic-2"
    assert [p.slug for p in repo.list_projects()] == ["acme-clinic", "acme-clinic-2"]
    with pytest.raises(FileExistsError):
        repo.create_project(a)


def test_atomic_write_leaves_no_temp_files(repo):
    p = _project(repo)
    for _ in range(5):
        repo.save_project(p)
    leftovers = [f.name for f in repo.project_dir(p.slug).iterdir() if f.name.endswith(".tmp")]
    assert leftovers == []


def test_concurrent_writers_never_corrupt_a_file(repo):
    p = _project(repo)
    run = repo.create_run(Run(id=repo.new_run_id(p.slug), project_slug=p.slug))
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            for i in range(20):
                repo.save_run_doc(
                    run,
                    "testcases.json",
                    TestSuite(cases=[TestCase(id=f"TC-T{n}-{i:03d}", title="x" * 500) for _ in range(20)]),
                )
                repo.load_run_doc(run, "testcases.json", TestSuite)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    suite = repo.load_run_doc(run, "testcases.json", TestSuite)
    assert len(suite.cases) == 20


def test_run_folders_index_and_relative_paths(repo):
    p = _project(repo)
    run = repo.create_run(Run(id=repo.new_run_id(p.slug), project_slug=p.slug, mode="safe"))
    rdir = repo.run_dir(p.slug, run.id)
    for sub in ("crawl", "executions", "artifacts/screenshots", "artifacts/videos", "replay", "exports"):
        assert (rdir / sub).is_dir()
    shot = repo.run_path(run, "artifacts/screenshots/a.png")
    assert repo.relative_to_run(run, shot) == "artifacts/screenshots/a.png"

    run.status = "completed"
    repo.save_run(run)
    repo.update_run_summary(p.slug, run.id, pages=12, findings=3)
    repo.save_run(run)  # a later save must keep counters written by other stages
    idx = repo.get_index(p.slug)
    assert idx.runs[0].id == run.id and idx.runs[0].status == "completed"
    assert idx.runs[0].pages == 12 and idx.runs[0].findings == 3
    # the index can always be rebuilt from the run folders
    (repo.project_dir(p.slug) / "index.json").unlink()
    assert repo.get_index(p.slug).runs[0].id == run.id


def test_secrets_are_encrypted_on_disk(repo):
    p = _project(repo)
    repo.update_secret(p.slug, "role:doctor", {"username": "doc@example.test", "password": "Sup3r-Secret!"})
    raw = (repo.project_dir(p.slug) / "secrets.enc").read_bytes()
    assert b"Sup3r-Secret!" not in raw and b"doc@example.test" not in raw
    assert repo.load_secrets(p.slug)["role:doctor"]["password"] == "Sup3r-Secret!"
    # nothing secret leaks into project.json
    assert "Sup3r-Secret!" not in (repo.project_dir(p.slug) / "project.json").read_text()


def test_wrong_secret_key_gives_clear_error(repo, monkeypatch):
    from cryptography.fernet import Fernet

    p = _project(repo)
    repo.update_secret(p.slug, "role:x", {"username": "u", "password": "pw-1234"})
    monkeypatch.setenv("QAP_SECRET_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="QAP_SECRET_KEY"):
        repo.load_secrets(p.slug)


def test_missing_documents_raise_not_found(repo):
    p = _project(repo)
    run = repo.create_run(Run(id="20260101-000000", project_slug=p.slug))
    assert not repo.has_run_doc(run, "bugs.json")
    with pytest.raises(NotFoundError):
        repo.load_run_doc(run, "bugs.json", FindingsDoc)


def test_migrations_upgrade_and_refuse_newer(repo, monkeypatch):
    @migrations.migration("FindingsDoc", 1)
    def _v1_to_v2(data):
        for f in data["findings"]:
            f["title"] = f.pop("name")
        return data

    old = {"schema_version": 1, "findings": [{"id": "F-001", "check": "js_error", "name": "Old title"}]}
    upgraded = migrations.upgrade("FindingsDoc", old, target=2)
    assert upgraded["schema_version"] == 2 and upgraded["findings"][0]["title"] == "Old title"
    Finding.model_validate(upgraded["findings"][0])

    with pytest.raises(migrations.MigrationError, match="newer"):
        migrations.upgrade("FindingsDoc", {"schema_version": 99, "findings": []})
    with pytest.raises(migrations.MigrationError, match="No migration"):
        migrations.upgrade("Run", {"schema_version": 1}, target=2)


def test_delete_project_and_portable_workspace(repo, tmp_path):
    import shutil

    p = _project(repo)
    run = repo.create_run(Run(id="20260101-000000", project_slug=p.slug))
    repo.update_secret(p.slug, "role:a", {"username": "a", "password": "pw-1234"})
    # zip/move the project folder to another workspace: it opens with no path fix-ups
    other = Repository(tmp_path / "elsewhere")
    shutil.copytree(repo.project_dir(p.slug), other.project_dir(p.slug))
    assert other.get_project(p.slug).url == p.url
    assert other.get_run(p.slug, run.id).id == run.id
    assert other.load_secrets(p.slug)["role:a"]["password"] == "pw-1234"
    repo.delete_project(p.slug)
    assert repo.list_projects() == []
