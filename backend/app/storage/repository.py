"""File-based repository: Pydantic models <-> pretty-printed JSON under workspace/.

This module is the ONLY code that reads or writes workspace files. Everything else depends on the
`Repository` interface, so the storage backend could be swapped without touching the engine.

Guarantees
* Atomic writes: data goes to a temp file in the same folder, then `os.replace` swaps it in.
* Concurrent writers (threads in the job executor, or a second process) are serialized per file
  with an in-process lock plus a `filelock` lock kept in workspace/.locks/ (run folders stay clean).
* Every document carries `schema_version`; older files are upgraded on load (see migrations.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from filelock import FileLock
from pydantic import BaseModel

from app.core import crypto
from app.core.paths import slugify, to_relative, workspace_root
from app.storage import migrations
from app.storage.schemas import Document, Project, ProjectIndex, Run, RunSummary, utcnow

T = TypeVar("T", bound=BaseModel)

_thread_locks: dict[str, threading.RLock] = {}
_file_locks: dict[str, FileLock] = {}
_thread_locks_guard = threading.Lock()


class NotFoundError(LookupError):
    pass


def _thread_lock(key: str) -> threading.RLock:
    with _thread_locks_guard:
        lock = _thread_locks.get(key)
        if lock is None:
            lock = _thread_locks[key] = threading.RLock()
        return lock


def _file_lock(path: Path) -> FileLock:
    # One FileLock object per path: FileLock instances are re-entrant, separate instances on the same
    # file are not (nested locking from the same thread would deadlock).
    key = str(path)
    with _thread_locks_guard:
        lock = _file_locks.get(key)
        if lock is None:
            lock = _file_locks[key] = FileLock(key, timeout=30)
        return lock


class Repository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else workspace_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks_dir = self.root / ".locks"
        self._locks_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ low level

    @contextmanager
    def lock(self, path: Path) -> Iterator[None]:
        key = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
        with _thread_lock(key), _file_lock(self._locks_dir / f"{key}.lock"):
            yield

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def write_json(self, path: Path, data: Any) -> None:
        text = json.dumps(data, indent=2, ensure_ascii=False, default=_json_default) + "\n"
        with self.lock(path):
            self._atomic_write_bytes(path, text.encode("utf-8"))

    def read_json(self, path: Path) -> Any:
        if not path.exists():
            raise NotFoundError(str(path))
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def save_model(self, path: Path, model: BaseModel) -> None:
        self.write_json(path, model.model_dump(mode="json"))

    def load_model(self, path: Path, cls: type[T]) -> T:
        data = self.read_json(path)
        if issubclass(cls, Document) and isinstance(data, dict):
            data = migrations.upgrade(cls.__name__, data)
        return cls.model_validate(data)

    def write_bytes(self, path: Path, data: bytes) -> None:
        with self.lock(path):
            self._atomic_write_bytes(path, data)

    def write_text(self, path: Path, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def append_line(self, path: Path, line: str) -> None:
        """Append-only logs (events.jsonl). One line per call, serialized by the same per-file lock."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock(path), path.open("a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")

    # ------------------------------------------------------------------ projects

    @property
    def projects_dir(self) -> Path:
        d = self.root / "projects"
        d.mkdir(exist_ok=True)
        return d

    def project_dir(self, slug: str) -> Path:
        return self.projects_dir / slug

    def unique_slug(self, name: str) -> str:
        base = slugify(name)
        slug, n = base, 2
        while self.project_dir(slug).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug

    def create_project(self, project: Project) -> Project:
        pdir = self.project_dir(project.slug)
        if (pdir / "project.json").exists():
            raise FileExistsError(f"Project '{project.slug}' already exists")
        (pdir / "runs").mkdir(parents=True, exist_ok=True)
        self.save_project(project)
        self.save_model(pdir / "index.json", ProjectIndex(project_slug=project.slug))
        return project

    def save_project(self, project: Project) -> None:
        self.save_model(self.project_dir(project.slug) / "project.json", project)

    def get_project(self, slug: str) -> Project:
        return self.load_model(self.project_dir(slug) / "project.json", Project)

    def list_projects(self) -> list[Project]:
        out = []
        for pdir in sorted(self.projects_dir.iterdir()):
            if (pdir / "project.json").exists():
                try:
                    out.append(self.get_project(pdir.name))
                except (ValueError, migrations.MigrationError):
                    continue  # unreadable project folders are skipped, never fatal
        return out

    def delete_project(self, slug: str) -> None:
        pdir = self.project_dir(slug)
        if pdir.exists():
            shutil.rmtree(pdir)

    # ------------------------------------------------------------------ secrets

    def save_secrets(self, slug: str, secrets: dict[str, Any]) -> None:
        self.write_bytes(self.project_dir(slug) / "secrets.enc", crypto.encrypt_json(secrets))

    def load_secrets(self, slug: str) -> dict[str, Any]:
        path = self.project_dir(slug) / "secrets.enc"
        if not path.exists():
            return {}
        return crypto.decrypt_json(path.read_bytes())

    def update_secret(self, slug: str, key: str, value: Any) -> None:
        with self.lock(self.project_dir(slug) / "secrets.enc"):
            secrets = self.load_secrets(slug)
            secrets[key] = value
            self.save_secrets(slug, secrets)

    # ------------------------------------------------------------------ runs

    def runs_dir(self, slug: str) -> Path:
        return self.project_dir(slug) / "runs"

    def run_dir(self, slug: str, run_id: str) -> Path:
        return self.runs_dir(slug) / run_id

    def new_run_id(self, slug: str) -> str:
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id, n = base, 2
        while self.run_dir(slug, run_id).exists():
            run_id, n = f"{base}-{n}", n + 1
        return run_id

    def create_run(self, run: Run) -> Run:
        rdir = self.run_dir(run.project_slug, run.id)
        for sub in (
            "crawl",
            "executions",
            "artifacts/screenshots",
            "artifacts/videos",
            "artifacts/clips",
            "artifacts/logs",
            "replay",
            "exports",
        ):
            (rdir / sub).mkdir(parents=True, exist_ok=True)
        self.save_run(run)
        return run

    def save_run(self, run: Run) -> None:
        self.save_model(self.run_dir(run.project_slug, run.id) / "run.json", run)
        self._update_index(run)

    def get_run(self, slug: str, run_id: str) -> Run:
        return self.load_model(self.run_dir(slug, run_id) / "run.json", Run)

    def list_runs(self, slug: str) -> list[Run]:
        rdir = self.runs_dir(slug)
        if not rdir.exists():
            return []
        runs = []
        for d in sorted(rdir.iterdir(), reverse=True):
            if (d / "run.json").exists():
                runs.append(self.get_run(slug, d.name))
        return runs

    def run_path(self, run: Run, relative: str) -> Path:
        """Absolute path for a file inside a run folder (relative paths are what we store in JSON)."""
        return self.run_dir(run.project_slug, run.id) / relative

    def relative_to_run(self, run: Run, path: Path) -> str:
        return to_relative(path, self.run_dir(run.project_slug, run.id))

    def save_run_doc(self, run: Run, relative: str, model: BaseModel) -> None:
        self.save_model(self.run_path(run, relative), model)

    def load_run_doc(self, run: Run, relative: str, cls: type[T]) -> T:
        return self.load_model(self.run_path(run, relative), cls)

    def has_run_doc(self, run: Run, relative: str) -> bool:
        return self.run_path(run, relative).exists()

    # ------------------------------------------------------------------ index

    def get_index(self, slug: str) -> ProjectIndex:
        path = self.project_dir(slug) / "index.json"
        if not path.exists():
            return self.rebuild_index(slug)
        return self.load_model(path, ProjectIndex)

    def rebuild_index(self, slug: str) -> ProjectIndex:
        index = ProjectIndex(project_slug=slug, runs=[_summary(r) for r in self.list_runs(slug)])
        self.save_model(self.project_dir(slug) / "index.json", index)
        return index

    def update_run_summary(self, slug: str, run_id: str, **fields: Any) -> None:
        """Let later stages record counts (pages, bugs, score) in the index without re-reading every run."""
        path = self.project_dir(slug) / "index.json"
        with self.lock(path):
            index = self.get_index(slug)
            for summary in index.runs:
                if summary.id == run_id:
                    for key, value in fields.items():
                        setattr(summary, key, value)
            index.updated_at = utcnow()
            self.save_model(path, index)

    def _update_index(self, run: Run) -> None:
        path = self.project_dir(run.project_slug) / "index.json"
        with self.lock(path):
            index = (
                self.load_model(path, ProjectIndex)
                if path.exists()
                else ProjectIndex(project_slug=run.project_slug)
            )
            fresh = _summary(run)
            for i, summary in enumerate(index.runs):
                if summary.id == run.id:
                    # keep counters that other stages wrote via update_run_summary
                    keep = summary.model_dump(
                        include={"pages", "findings", "bugs", "quality_score", "domain"}
                    )
                    index.runs[i] = fresh.model_copy(update=keep)
                    break
            else:
                index.runs.insert(0, fresh)
            index.runs.sort(key=lambda s: s.id, reverse=True)
            index.updated_at = utcnow()
            self.save_model(path, index)


def _summary(run: Run) -> RunSummary:
    return RunSummary(
        id=run.id,
        mode=run.mode,
        status=run.status,
        stage=run.stage,
        started_at=run.started_at,
        finished_at=run.finished_at,
        cost_usd=round(run.token_usage.cost_usd, 4),
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")
