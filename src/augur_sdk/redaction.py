"""Redaction pipeline.

Spec §13, policy id `default-pii-v1`. See `docs/redaction-policy.md` for the
normative spec. This module ships the reference implementation: regex-based
string scrubbing plus a drop-keys allowlist.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_POLICY_ID = "default-pii-v1"

_DROP_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)

_MASK_KEYS = frozenset(
    {
        "token",
        "api_key",
        "apikey",
        "ssn",
        "credit_card",
        "card_number",
        "cvv",
    }
)


_REGEX_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")),
    (
        "api_key",
        re.compile(r"(?i)(api[_-]?key|x-api-key)\s*[:=]\s*[A-Za-z0-9._\-]+"),
    ),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("cookie_header", re.compile(r"(?i)cookie\s*:\s*[^\r\n]+")),
    ("set_cookie", re.compile(r"(?i)set-cookie\s*:\s*[^\r\n]+")),
    ("email", re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")),
    ("password_kv", re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
]


def _redact_string(s: str) -> str:
    out = s
    for kind, pat in _REGEX_PATTERNS:
        out = pat.sub(f"***REDACTED:{kind}***", out)
    return out


@dataclass
class RedactionPolicy:
    """A redaction policy.

    Custom policies SHOULD subclass this and override `id`. The default
    `apply()` walks a JSON-serializable structure, dropping keys in
    `drop_keys`, masking keys in `mask_keys`, and running every registered
    `redactor` over string values.
    """

    id: str = DEFAULT_POLICY_ID
    drop_keys: frozenset[str] = _DROP_KEYS
    mask_keys: frozenset[str] = _MASK_KEYS
    redactors: list[Callable[[str], str]] = field(default_factory=list)
    droppers: list[Callable[[str, Any], bool]] = field(default_factory=list)

    def add_redactor(self, fn: Callable[[str], str]) -> None:
        """Add a string-level redactor. Runs after the built-in regex set."""
        self.redactors.append(fn)

    def add_dropper(self, fn: Callable[[str, Any], bool]) -> None:
        """Add a (key, value) -> bool dropper. Return True to drop the field."""
        self.droppers.append(fn)

    def apply(self, value: Any, *, key: str | None = None) -> Any:
        """Walk `value`, returning a redacted copy."""
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                klow = k.lower()
                if klow in self.drop_keys or any(d(k, v) for d in self.droppers):
                    continue
                if klow in self.mask_keys:
                    out[k] = "***REDACTED:mask***"
                    continue
                out[k] = self.apply(v, key=klow)
            return out
        if isinstance(value, list):
            return [self.apply(v, key=key) for v in value]
        if isinstance(value, str):
            redacted = _redact_string(value)
            for r in self.redactors:
                redacted = r(redacted)
            return redacted
        return value


class DefaultRedactionPolicy(RedactionPolicy):
    """`default-pii-v1`. The shipped baseline."""

    def __init__(self) -> None:
        super().__init__(id=DEFAULT_POLICY_ID)


__all__ = [
    "DEFAULT_POLICY_ID",
    "DefaultRedactionPolicy",
    "RedactionPolicy",
]
