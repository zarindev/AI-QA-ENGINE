"""Warn before secrets are committed: API keys, private keys, .env files, encrypted secret stores, workspace data.

Used by the git pre-commit hook (.githooks/pre-commit, enabled by setup) and by CI (`--all` scans the whole tree).
Exit code 1 when something looks secret; bypass a false alarm with `git commit --no-verify` after checking.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[a-z]{2,5}\d{0,2}-[A-Za-z0-9_\-]{20,}"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "Fernet secret key": re.compile(r"QAP_SECRET_KEY\s*=\s*[A-Za-z0-9_\-]{43}="),
}
FORBIDDEN_FILES = re.compile(r"(^|/)(\.env|.*\.enc|secrets\.json)$|^workspace/(?!\.gitkeep$)")
SKIP = re.compile(r"\.(png|jpe?g|gif|webp|mp4|pdf|xlsx|zip|ico|woff2?)$|^backend/app/static/assets/")


def staged() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return [p for p in out.stdout.splitlines() if p]


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT)
    return [p for p in out.stdout.splitlines() if p]


def scan(paths: list[str]) -> list[str]:
    problems = []
    for rel in paths:
        if FORBIDDEN_FILES.search(rel):
            problems.append(f"{rel}: this file must never be committed")
            continue
        path = ROOT / rel
        if SKIP.search(rel) or not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{rel}: looks like it contains a {name}")
    return problems


def main() -> int:
    problems = scan(tracked() if "--all" in sys.argv else staged())
    if problems:
        print("QA Pilot secret check — commit blocked:")
        for p in problems:
            print("  ✗", p)
        print("Remove the secret (keys belong in .env, credentials in the encrypted workspace store).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
