"""Adapter base class (issue #7, spec §6).

An adapter maps a CUA framework into Augur records. Hooks are optional unless
the adapter has something to translate. See docs/adapter-authoring.md for the
contract.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from augur_sdk.models import DecisionEvent, Observation, StepTrace


class Adapter(Protocol):
    """Adapter contract. Implementations need only define the methods they use."""

    name: ClassVar[str]
    SUPPORTED_SCHEMA_RANGE: ClassVar[tuple[str, str]]

    def on_run_start(
        self, *, run_id: str, client_version: str
    ) -> dict[str, str] | None:
        """Called once at the start of a run. Return tags merged into DebugSession.tags."""
        ...

    def on_step(self, raw_step: Any) -> StepTrace | None:
        """Translate a framework-native step record."""
        ...

    def on_action(self, raw_action: Any, step_index: int) -> dict[str, Any]:
        """Translate a framework-native action payload."""
        ...

    def on_decision(
        self, raw_event: Any, step_index: int | None
    ) -> DecisionEvent:
        """Translate a framework-native decision/event record."""
        ...

    def on_observation(self, raw_obs: Any, step_index: int) -> Observation:
        """Translate a framework-native observation record."""
        ...

    def on_run_end(self, *, status: str) -> None:
        """Called once at run end. Default: no-op."""
        ...


__all__ = ["Adapter"]
