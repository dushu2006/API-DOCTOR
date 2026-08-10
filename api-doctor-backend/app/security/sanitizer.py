"""Secret sanitisation.

Any payload destined for the frontend, browser, logs, or an LLM prompt must be
passed through :func:`sanitize` / :func:`redact_text`. Only keys / patterns are
replaced — we never reveal the actual secret values.
"""

from __future__ import annotations

import os
import re
from typing import Any

from app.core.config import settings

_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization|cookie|jwt|"
    r"database[_-]?url|passwd|credential|signing[_-]?key)"
)

# Value patterns for common secret shapes.
_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),      # OpenAI/NVIDIA style
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),        # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"rnd_[A-Za-z0-9]{20,}"),        # Render key
    re.compile(r"AKIA[0-9A-Z]{16}"),            # AWS access key
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),# Slack token
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),  # JWT
]

_PLACEHOLDER = "<SECRET_PRESENT>"


def _env_values() -> list[str]:
    values: list[str] = []
    for key in _SECRET_KEY_PATTERN.findall(" ".join(os.environ.keys())):
        v = os.environ.get(key.upper(), "")
        if v:
            values.append(v)
    # Also the configured secrets themselves.
    for attr in ("NVIDIA_API_KEY", "GITHUB_TOKEN", "RENDER_API_KEY"):
        v = getattr(settings, attr, "")
        if v:
            values.append(v)
    return values


def redact_text(text: str) -> str:
    """Replace known/patterned secret values in a text blob."""
    if not text:
        return text
    out = text
    for pat in _VALUE_PATTERNS:
        out = pat.sub(_PLACEHOLDER, out)
    for value in _env_values():
        if value and len(value) >= 6:
            out = out.replace(value, _PLACEHOLDER)
    return out


def sanitize(obj: Any, in_place: bool = False) -> Any:
    """Recursively sanitise a nested structure (dicts/lists/strs)."""
    if in_place and isinstance(obj, dict):
        _sanitize_in_place(obj)
        return obj
    return _sanitize(obj)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            str(k): (_PLACEHOLDER if _is_secret_key(str(k)) else _sanitize(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize(v) for v in obj)
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def _sanitize_in_place(obj: dict) -> None:
    for k in list(obj.keys()):
        v = obj[k]
        if _is_secret_key(str(k)):
            obj[k] = _PLACEHOLDER
        elif isinstance(v, dict):
            _sanitize_in_place(v)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    _sanitize_in_place(item)
                elif isinstance(item, str):
                    v[i] = redact_text(item)
        elif isinstance(v, str):
            obj[k] = redact_text(v)


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_PATTERN.search(key))


__all__ = ["sanitize", "redact_text"]
