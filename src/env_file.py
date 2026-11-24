"""Minimal .env loader for local runs.

GitHub Actions passes secrets as real environment variables, so this file is a
local convenience only. Existing environment variables always win: loading a
.env must never silently override a value the shell or CI already set.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Comments and blank lines are ignored."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        key, raw = match.group(1), match.group(2)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
            raw = raw[1:-1]
        else:
            raw = re.sub(r"\s+#.*$", "", raw).strip()
        values[key] = raw
    return values


def load_env_file(path: Path) -> list[str]:
    """Load ``path`` into os.environ, skipping keys that are already set.

    Returns the names that were actually applied. A missing file is not an
    error: CI has no .env and must keep working.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    applied: list[str] = []
    for key, value in parse_env_file(text).items():
        if key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied
