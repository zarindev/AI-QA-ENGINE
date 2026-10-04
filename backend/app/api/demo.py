"""“Try with a demo app”: start the bundled clinic demo (if it is not running) and run QA Pilot against it."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import executor, repo
from app.core.logging import get_logger, register_secret
from app.core.paths import REPO_ROOT
from app.storage.schemas import Project, Role, Run, Scope, utcnow

router = APIRouter(prefix="/api/demo", tags=["demo"])
log = get_logger("api.demo")

CLINIC_NAME = "CarePoint Clinic (demo)"
CLINIC_URL = "http://localhost:8101"
CLINIC_SCRIPT = REPO_ROOT / "demo_targets" / "clinic_app" / "app.py"
# Demo-only accounts of the bundled demo app (also listed in the README and on its login page).
CLINIC_ROLES: list[tuple[str, str, str]] = [
    ("admin", "admin@carepoint.test", "Admin#2026"),
    ("doctor", "dr.lee@carepoint.test", "Doctor#2026"),
    ("receptionist", "reception@carepoint.test", "Front#2026"),
]
_processes: list[subprocess.Popen[bytes]] = []


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_clinic_running() -> bool:
    if _port_open(8101):
        return False
    proc = subprocess.Popen(
        [sys.executable, str(CLINIC_SCRIPT), "--reset"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _processes.append(proc)
    for _ in range(40):
        if _port_open(8101):
            return True
        time.sleep(0.25)
    raise HTTPException(500, "The clinic demo app did not start on port 8101.")


def stop_demo_processes() -> None:
    for proc in _processes:
        proc.terminate()


@router.post("/start", status_code=202)
def start_demo() -> dict[str, Any]:
    started = ensure_clinic_running()
    r = repo()
    project = next((p for p in r.list_projects() if p.name == CLINIC_NAME), None)
    if project is None:
        project = Project(
            slug=r.unique_slug(CLINIC_NAME),
            name=CLINIC_NAME,
            url=CLINIC_URL,
            environment="test",
            authorized_by="QA Pilot demo (bundled app)",
            authorized_at=utcnow(),
            scope=Scope(max_pages=30, max_depth=4),
        )
        secrets: dict[str, dict[str, str]] = {}
        for name, user, pw in CLINIC_ROLES:
            register_secret(pw)
            project.roles.append(Role(name=name, secret_ref=f"role:{name}"))
            secrets[f"role:{name}"] = {"username": user, "password": pw}
        r.create_project(project)
        r.save_secrets(project.slug, secrets)
    index = r.get_index(project.slug)
    if index.runs and executor().is_running(index.runs[0].id):
        return {"project": project.slug, "run": index.runs[0].id, "started_app": started}
    run = r.create_run(Run(id=r.new_run_id(project.slug), project_slug=project.slug, mode="safe"))
    executor().submit(run)
    return {"project": project.slug, "run": run.id, "started_app": started}
