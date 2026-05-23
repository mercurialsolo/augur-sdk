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

    def on_side_effect(
        self, raw_action: Any, step_index: int
    ) -> dict[str, Any] | None:
        """Optional hook for auto-detecting irreversible action types (#11).

        When the adapter recognises a known irreversible action shape
        (form_submit, non-idempotent API verb), it returns a dict
        with at least ``resource`` and ``action`` keys; the SDK will
        feed it through ``session.declare_side_effect()``. Return
        ``None`` for actions that don't need ledger tracking.

        Producers MAY still call ``declare_side_effect()`` directly;
        this hook is purely opt-in convenience.
        """
        ...

    # ── intervention hooks (#12) ──────────────────────────────────────
    # Adapters that don't implement these hooks see the SDK call
    # signatures degrade to no-ops — unsupported commands are logged
    # and dropped, never raised.

    def on_pause(self) -> None:
        """Pause the runner. The SDK will keep polling for commands."""
        ...

    def on_resume(self) -> None:
        """Resume from a paused state."""
        ...

    def on_kill(self) -> None:
        """Kill the runner. The SDK aborts every pending side-effect
        declaration (#11) on the runner's behalf before invoking this
        hook."""
        ...

    def on_inject_hint(self, hint_text: str) -> None:
        """Inject an operator hint into the agent's next planner turn."""
        ...

    def on_action_override(
        self, coordinates: dict[str, float], *, provenance: str
    ) -> None:
        """Operator-supplied click/type coordinates. The SDK guarantees
        ``provenance="human_override"`` so the trajectory clearly shows
        the override was not grounder output (preserves SPEC §4)."""
        ...


__all__ = ["Adapter"]
