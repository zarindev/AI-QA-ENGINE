"""Filesystem locations. Everything is derived from the repo root so the app runs from any cwd."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
APP_DIR = BACKEND_DIR / "app"
CONFIG_FILE = REPO_ROOT / "config" / "settings.yaml"
ENV_FILE = REPO_ROOT / ".env"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "reports" / "templates"
DOMAIN_PACKS_DIR = APP_DIR / "understand" / "domain_packs"
PROMPTS_DIR = APP_DIR / "ai" / "prompts"


def workspace_root() -> Path:
    """The workspace folder. Overridable with QAP_WORKSPACE (read lazily so tests can redirect it)."""
    override = os.environ.get("QAP_WORKSPACE", "").strip()
    root = Path(override).expanduser() if override else REPO_ROOT / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


def slugify(text: str, max_len: int = 60) -> str:
    """ASCII, lowercase, dash-separated slug that is safe as a folder name on Windows and POSIX."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].strip("-")) or "project"


def to_relative(path: Path, base: Path) -> str:
    """Store paths inside JSON relative to the run/project folder, always with forward slashes."""
    return Path(os.path.relpath(path, base)).as_posix()
