"""Secret redaction for logs and reports.

Every log line and every generated report passes through here. A token must
never reach the Actions log, an artifact, or a committed file.
"""

from __future__ import annotations

import logging
import re
from typing import Mapping, Sequence

SECRET_ENV_NAMES = (
    "GEMINI_API_KEY",
    "BUFFER_API_KEY",
    "BUFFER_ACCESS_TOKEN",
    "BUFFER_CLIENT_SECRET",
    "GH_TOKEN",
    "GITHUB_TOKEN",
)

_PATTERNS = (
    re.compile(r"(?i)(x-goog-api-key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(key=)[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{6,}"),
    re.compile(r"(?i)(access_token=)[A-Za-z0-9_\-\.]{6,}"),
)

_SECRETS: tuple[str, ...] = ()


def collect_secrets(environ: Mapping[str, str]) -> tuple[str, ...]:
    values = []
    for name in SECRET_ENV_NAMES:
        value = environ.get(name, "")
        if len(value) >= 6:
            values.append(value)
    return tuple(values)


def set_secrets(values: Sequence[str]) -> None:
    global _SECRETS
    _SECRETS = tuple(v for v in values if len(v) >= 6)


def redact(text: str) -> str:
    if not text:
        return text
    cleaned = text
    for secret in _SECRETS:
        cleaned = cleaned.replace(secret, "***")
    for pattern in _PATTERNS:
        cleaned = pattern.sub(r"\1***", cleaned)
    return cleaned


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
