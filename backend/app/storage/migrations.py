"""schema_version upgrades for JSON written by older QA Pilot versions.

Register a step with `@migration("Run", 1)`: it receives the raw dict at version 1 and returns it at version 2.
`upgrade()` applies steps in order until the dict reaches the current SCHEMA_VERSION.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.storage.schemas import SCHEMA_VERSION

Migration = Callable[[dict[str, Any]], dict[str, Any]]
_REGISTRY: dict[tuple[str, int], Migration] = {}


def migration(model_name: str, from_version: int) -> Callable[[Migration], Migration]:
    def register(fn: Migration) -> Migration:
        _REGISTRY[(model_name, from_version)] = fn
        return fn

    return register


class MigrationError(RuntimeError):
    pass


def upgrade(model_name: str, data: dict[str, Any], target: int = SCHEMA_VERSION) -> dict[str, Any]:
    version = int(data.get("schema_version", 1))
    if version > target:
        raise MigrationError(
            f"{model_name} file has schema_version {version}, newer than this QA Pilot ({target}). Update QA Pilot."
        )
    while version < target:
        step = _REGISTRY.get((model_name, version))
        if step is None:
            raise MigrationError(f"No migration registered for {model_name} v{version} -> v{version + 1}")
        data = step(dict(data))
        version += 1
        data["schema_version"] = version
    return data
