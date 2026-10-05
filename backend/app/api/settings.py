"""Health, settings, API key onboarding and workspace helpers."""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import __version__
from app.ai.client import AIClient
from app.api.deps import repo
from app.browser.driver import chrome_available
from app.core.config import api_key_present, get_settings, set_env_value
from app.core.logging import register_secret
from app.storage.schemas import UserSettings

router = APIRouter(prefix="/api", tags=["settings"])

EDITABLE = {"ai", "browser", "crawl", "safety", "viewports", "privacy", "branding"}


def _masked_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return f"{key[:7]}…{key[-4:]}" if len(key) > 12 else ""


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "version": __version__,
        "api_key": api_key_present(),
        "api_key_hint": _masked_key(),
        "chrome": chrome_available(),
        "model": settings["ai"]["model"],
        "workspace": str(repo().root),
        "platform": platform.system(),
    }


class ApiKeyIn(BaseModel):
    key: str
    workspace_id: str = ""


@router.post("/settings/api-key")
def save_api_key(body: ApiKeyIn) -> dict[str, Any]:
    key = body.key.strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(400, "Anthropic API keys start with “sk-ant-”.")
    workspace = body.workspace_id.strip()
    if workspace and not workspace.startswith("wrkspc_"):
        raise HTTPException(400, "Workspace IDs start with “wrkspc_”.")
    register_secret(key)
    ok, message = AIClient.validate_key(key, workspace or None)
    if not ok:
        raise HTTPException(400, message)
    set_env_value("ANTHROPIC_API_KEY", key)
    set_env_value("ANTHROPIC_WORKSPACE_ID", workspace)
    return {"ok": True, "message": "API key saved to .env", "api_key_hint": _masked_key()}


@router.get("/settings")
def read_settings() -> dict[str, Any]:
    settings = get_settings()
    return {k: v for k, v in settings.items() if k in EDITABLE | {"server"}}


@router.put("/settings")
def write_settings(body: dict[str, Any]) -> dict[str, Any]:
    unknown = set(body) - EDITABLE
    if unknown:
        raise HTTPException(400, f"These settings cannot be changed here: {', '.join(sorted(unknown))}")
    path = repo().root / "settings.json"
    current: dict[str, Any] = {}
    if path.exists():
        current = repo().read_json(path)
    for section, values in body.items():
        if not isinstance(values, dict):
            raise HTTPException(400, f"'{section}' must be an object")
        current.setdefault(section, {}).update(values)
    repo().save_model(path, UserSettings(**current))
    return read_settings()


@router.delete("/settings")
def reset_settings() -> dict[str, Any]:
    """Danger zone: forget every change made in Settings (back to config/settings.yaml). Projects are untouched."""
    path = repo().root / "settings.json"
    if path.exists():
        path.unlink()
    return read_settings()


@router.post("/settings/open-workspace")
def open_workspace() -> dict[str, str]:
    """Open the workspace folder in Explorer / Finder / the file manager (local app, so this is the user's machine)."""
    folder = str(repo().root)
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError as exc:
        raise HTTPException(500, f"Could not open the folder: {exc}") from exc
    return {"opened": folder}
