"""Projects: list, create (with authorization record and encrypted role credentials), delete, manual login."""

from __future__ import annotations

import threading
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import executor, get_project_or_404, repo
from app.browser.driver import BrowserSession
from app.core.config import get_settings
from app.core.logging import get_logger, register_secret
from app.storage.schemas import Project, Role, Scope, utcnow

router = APIRouter(prefix="/api/projects", tags=["projects"])
log = get_logger("api.projects")


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    login_strategy: Literal["credentials", "manual_session"] = "credentials"
    username: str = ""
    password: str = ""
    login_url: str = ""


class ProjectIn(BaseModel):
    name: str = ""
    url: str
    environment: Literal["production", "staging", "test"] = "production"
    authorized: bool = False
    authorized_by: str = Field(min_length=1, max_length=80)
    roles: list[RoleIn] = Field(default_factory=list)
    max_pages: int = Field(40, ge=1, le=500)
    max_depth: int = Field(4, ge=0, le=10)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)


def project_card(project: Project) -> dict[str, Any]:
    index = repo().get_index(project.slug)
    latest = index.runs[0] if index.runs else None
    return {
        **project.model_dump(mode="json"),
        "latest_run": latest.model_dump(mode="json") if latest else None,
        "runs": len(index.runs),
        "running": bool(latest and executor().is_running(latest.id)),
    }


@router.get("")
def list_projects() -> list[dict[str, Any]]:
    return [project_card(p) for p in repo().list_projects()]


@router.post("", status_code=201)
def create_project(body: ProjectIn) -> dict[str, Any]:
    if not body.authorized:
        raise HTTPException(400, "Confirm that you own this website or are authorized to test it.")
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = urlparse(url).hostname
    if not host:
        raise HTTPException(400, "That does not look like a website address.")
    r = repo()
    names = [role.name.strip().lower() for role in body.roles]
    if len(set(names)) != len(names) or "public" in names:
        raise HTTPException(400, "Role names must be unique and cannot be 'public'.")
    project = Project(
        slug=r.unique_slug(body.name or host),
        name=body.name or host,
        url=url,
        environment=body.environment,
        authorized_by=body.authorized_by,
        authorized_at=utcnow(),
        scope=Scope(
            max_pages=body.max_pages,
            max_depth=body.max_depth,
            include_patterns=body.include_patterns,
            exclude_patterns=body.exclude_patterns,
        ),
    )
    secrets: dict[str, Any] = {}
    for role in body.roles:
        name = role.name.strip().lower()
        if role.login_strategy == "credentials":
            if not role.username or not role.password:
                raise HTTPException(
                    400, f"Role '{name}' needs a username and password (or use manual login)."
                )
            register_secret(role.password)
            secrets[f"role:{name}"] = {"username": role.username, "password": role.password}
            project.roles.append(Role(name=name, secret_ref=f"role:{name}", login_url=role.login_url))
        else:
            project.roles.append(
                Role(
                    name=name,
                    login_strategy="manual_session",
                    secret_ref=f"session:{name}",
                    login_url=role.login_url,
                )
            )
    r.create_project(project)
    if secrets:
        r.save_secrets(project.slug, secrets)
    return project_card(project)


@router.get("/{slug}")
def get_project(slug: str) -> dict[str, Any]:
    return project_card(get_project_or_404(slug))


@router.delete("/{slug}", status_code=204)
def delete_project(slug: str) -> None:
    get_project_or_404(slug)
    latest = repo().get_index(slug).runs
    if latest and executor().is_running(latest[0].id):
        raise HTTPException(409, "Stop the running run before deleting the project.")
    repo().delete_project(slug)


# ---------------------------------------------------------------- manual session capture (2FA / SSO)

_captures: dict[str, dict[str, Any]] = {}


@router.post("/{slug}/roles/{role}/manual-session")
def start_manual_session(slug: str, role: str) -> dict[str, str]:
    """Open a visible Chrome at the project's login page. The user logs in, then calls .../finish."""
    project = get_project_or_404(slug)
    key = f"{slug}:{role}"
    if key in _captures:
        raise HTTPException(409, "A login window is already open for this role.")
    done = threading.Event()
    state: dict[str, Any] = {"done": done, "status": "opening", "error": ""}
    _captures[key] = state
    target = next((r.login_url for r in project.roles if r.name == role and r.login_url), "") or project.url

    def worker() -> None:
        s = get_settings()["browser"]
        try:
            with BrowserSession(
                headless=False, width=s["window_width"], height=s["window_height"]
            ) as session:
                session.navigate(target)
                state["status"] = "waiting"
                if not done.wait(timeout=15 * 60):
                    state.update(status="timeout", error="No confirmation within 15 minutes.")
                    return
                saved = session.export_session()
            repo().update_secret(slug, f"session:{role}", saved)
            state["status"] = "saved"
        except Exception as exc:
            log.warning("manual session capture failed: %s", exc)
            state.update(status="error", error=str(exc))

    threading.Thread(target=worker, daemon=True, name=f"manual-login-{key}").start()
    return {
        "status": "opening",
        "message": "A Chrome window is opening. Log in there, then click “I'm logged in”.",
    }


@router.post("/{slug}/roles/{role}/manual-session/finish")
def finish_manual_session(slug: str, role: str) -> dict[str, str]:
    state = _captures.get(f"{slug}:{role}")
    if not state:
        raise HTTPException(404, "No login window is open for this role.")
    state["done"].set()
    for _ in range(100):
        if state["status"] in ("saved", "error", "timeout"):
            break
        threading.Event().wait(0.1)
    _captures.pop(f"{slug}:{role}", None)
    if state["status"] != "saved":
        raise HTTPException(500, state["error"] or "Could not save the session.")
    return {"status": "saved"}
