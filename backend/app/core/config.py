"""Settings: config/settings.yaml (defaults) deep-merged with workspace/settings.json (user overrides) and .env."""

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from typing import Any

import yaml
from dotenv import load_dotenv

from app.core.paths import CONFIG_FILE, ENV_FILE, workspace_root


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_env() -> None:
    load_dotenv(ENV_FILE, override=False)


@lru_cache(maxsize=1)
def _defaults() -> dict[str, Any]:
    with CONFIG_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get_settings() -> dict[str, Any]:
    """Return the effective settings. Cheap enough to call per request (local scale)."""
    load_env()
    settings = _defaults()
    user_file = workspace_root() / "settings.json"
    if user_file.exists():
        try:
            user = json.loads(user_file.read_text(encoding="utf-8"))
            user.pop("schema_version", None)
            settings = _deep_merge(settings, user)
        except (OSError, json.JSONDecodeError):
            pass  # a broken user file must never stop the app; defaults still apply
    settings = copy.deepcopy(settings)
    env_model = os.environ.get("QAP_MODEL", "").strip()
    if env_model:
        settings["ai"]["model"] = env_model
    return settings


def api_key_present() -> bool:
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def set_env_value(key: str, value: str) -> None:
    """Write or replace one KEY=value line in .env (used for the API key and the generated secret key)."""
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            found = True
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value
