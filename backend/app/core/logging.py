"""Logging with secret redaction. Registered secrets are scrubbed from every log record."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Any string registered here (passwords, API keys, cookies) is replaced with *** in logs."""
    if value and len(value) >= 4:
        with _lock:
            _secrets.add(value)


def redact(text: str) -> str:
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, "***")
    return text


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact(message)
        record.args = ()
        return True


_configured = False


def setup_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    global _configured
    root = logging.getLogger("qap")
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        )
        handler.addFilter(_RedactingFilter())
        root.addHandler(handler)
        root.setLevel(level)
        root.propagate = False
        # Selenium/urllib3 are noisy at INFO.
        for noisy in ("selenium", "urllib3", "httpx", "httpx2", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _configured = True
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        fh.addFilter(_RedactingFilter())
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"qap.{name}")
