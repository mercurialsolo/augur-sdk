"""Event recorder.

Accumulates StepTrace + DecisionEvent + Observation records in memory while
a session is active. The bundle writer drains the recorder when the session
closes.

Recorder operations are intentionally append-only and idempotent on
step_index: re-recording a step with the same index replaces the prior
record (last-write-wins). This is the path adapters use when a step starts
in `running` state and is later updated with the post-action result.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from copy import deepcopy
from typing import Any

from augur_sdk.models import DecisionEvent, StepTrace


class EventRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._steps: dict[int, StepTrace] = {}
        self._events_by_step: dict[int | None, list[DecisionEvent]] = defaultdict(list)
        self._observation_bytes: dict[str, bytes] = {}
        # observation_bytes is keyed by bundle-relative path

    # -- steps --

    def record_step(self, step: StepTrace) -> None:
        if "step_index" not in step:
            raise ValueError("step is missing 'step_index'")
        with self._lock:
            self._steps[step["step_index"]] = deepcopy(dict(step))  # type: ignore[assignment]

    def get_step(self, step_index: int) -> StepTrace | None:
        with self._lock:
            return deepcopy(self._steps.get(step_index))

    def all_steps(self) -> list[StepTrace]:
        with self._lock:
            return [deepcopy(self._steps[i]) for i in sorted(self._steps)]

    # -- events --

    def record_event(self, event: DecisionEvent) -> None:
        if "ts" not in event:
            raise ValueError("event is missing 'ts'")
        with self._lock:
            self._events_by_step[event.get("step_index")].append(deepcopy(dict(event)))  # type: ignore[arg-type]

    def events_for_step(self, step_index: int | None) -> list[DecisionEvent]:
        with self._lock:
            return [deepcopy(e) for e in self._events_by_step.get(step_index, [])]

    def all_events_grouped(self) -> dict[int | None, list[DecisionEvent]]:
        with self._lock:
            return {k: [deepcopy(e) for e in v] for k, v in self._events_by_step.items()}

    # -- observation bytes --

    def stage_observation_bytes(self, relpath: str, data: bytes) -> None:
        if not relpath.startswith("screenshots/"):
            raise ValueError(f"observation bytes must be under screenshots/: {relpath!r}")
        with self._lock:
            self._observation_bytes[relpath] = data

    def staged_observations(self) -> dict[str, bytes]:
        with self._lock:
            return dict(self._observation_bytes)

    # -- snapshot for tests --

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "steps": [deepcopy(self._steps[i]) for i in sorted(self._steps)],
                "events": {
                    k: [deepcopy(e) for e in v] for k, v in self._events_by_step.items()
                },
                "observation_bytes_count": len(self._observation_bytes),
            }


__all__ = ["EventRecorder"]
