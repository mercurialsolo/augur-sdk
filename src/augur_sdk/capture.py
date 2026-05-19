"""Capture mode (spec §7).

Modes are ordered. `resolve_capture_mode()` lets callers ask "is screenshot
capture active?" by checking `mode >= CaptureMode.SCREENSHOTS`.
"""

from __future__ import annotations

import os
from enum import StrEnum


class CaptureMode(StrEnum):
    OFF = "off"
    METADATA = "metadata"
    TRACE = "trace"
    SCREENSHOTS = "screenshots"
    VIDEO = "video"
    MODEL_IO = "model_io"
    DISPATCH = "dispatch"
    REPLAY = "replay"
    FULL = "full"

    @property
    def rank(self) -> int:
        return _ORDER.index(self)

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, CaptureMode):
            return NotImplemented
        return self.rank >= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, CaptureMode):
            return NotImplemented
        return self.rank > other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, CaptureMode):
            return NotImplemented
        return self.rank <= other.rank

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, CaptureMode):
            return NotImplemented
        return self.rank < other.rank


# `full` is the widest and conceptually superset of all. We rank named modes
# in the order spec §7 lists them, then put `full` at the top.
_ORDER: list[CaptureMode] = [
    CaptureMode.OFF,
    CaptureMode.METADATA,
    CaptureMode.TRACE,
    CaptureMode.SCREENSHOTS,
    CaptureMode.VIDEO,
    CaptureMode.MODEL_IO,
    CaptureMode.DISPATCH,
    CaptureMode.REPLAY,
    CaptureMode.FULL,
]


_ENV_VAR = "AUGUR_CAPTURE_MODE"


def resolve_capture_mode(
    explicit: CaptureMode | str | None = None,
    *,
    env: os._Environ[str] | None = None,
) -> CaptureMode:
    """Resolve the effective capture mode.

    Precedence (spec §7):
        1. explicit argument (per-run / CLI flag)
        2. AUGUR_CAPTURE_MODE env var
        3. default = OFF
    """
    environ = env if env is not None else os.environ
    if explicit is not None:
        return _coerce(explicit)
    env_value = environ.get(_ENV_VAR)
    if env_value:
        return _coerce(env_value)
    return CaptureMode.OFF


def _coerce(value: CaptureMode | str) -> CaptureMode:
    if isinstance(value, CaptureMode):
        return value
    try:
        return CaptureMode(value.lower())
    except ValueError as exc:
        raise ValueError(
            f"unknown capture mode: {value!r}. valid: {[m.value for m in CaptureMode]}"
        ) from exc


__all__ = ["CaptureMode", "resolve_capture_mode"]
