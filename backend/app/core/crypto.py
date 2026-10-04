"""Fernet encryption for role credentials and saved sessions (workspace/<project>/secrets.enc)."""

from __future__ import annotations

import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import load_env, set_env_value
from app.core.logging import get_logger, register_secret

log = get_logger("crypto")


def _fernet() -> Fernet:
    load_env()
    key = os.environ.get("QAP_SECRET_KEY", "").strip()
    if not key:
        key = Fernet.generate_key().decode("ascii")
        set_env_value("QAP_SECRET_KEY", key)
        log.info("Generated a new QAP_SECRET_KEY and saved it to .env")
    return Fernet(key.encode("ascii"))


def encrypt_json(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data, sort_keys=True).encode("utf-8"))


def decrypt_json(token: bytes) -> dict[str, Any]:
    try:
        data = json.loads(_fernet().decrypt(token).decode("utf-8"))
    except InvalidToken as exc:
        raise ValueError(
            "Could not decrypt secrets.enc — QAP_SECRET_KEY in .env does not match the key it was saved with."
        ) from exc
    _register_nested(data)
    return data


# Values under these keys are identifiers, not secrets. Redacting a username such as "Admin" would also
# scrub every "Admin" menu label from captured pages and starve the AI of context.
_NOT_SECRET_KEYS = {
    "username",
    "origin",
    "url",
    "saved_at",
    "name",
    "path",
    "domain",
    "sameSite",
    "expiry",
    "secure",
    "httpOnly",
}


def _register_nested(value: Any, key: str = "") -> None:
    """Passwords, cookie values and storage values are secrets: make sure none can reach logs or JSON."""
    if key in _NOT_SECRET_KEYS:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _register_nested(v, str(k))
    elif isinstance(value, list):
        for v in value:
            _register_nested(v)
    elif isinstance(value, str):
        register_secret(value)
