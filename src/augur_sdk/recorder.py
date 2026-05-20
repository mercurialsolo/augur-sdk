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
        self._modelio_records: dict[str, dict[str, Any]] = {}
        # modelio is keyed by bundle-relative path (modelio/<step:04d>-<layer>-<seq>.json)
        self._modelio_seq_counter: dict[tuple[int | None, str], int] = {}
        # (step_index, layer) → next seq for path uniqueness
        self._modelio_hash_index: dict[str, str] = {}
        # prompt_hash → bundle-relative path (for record_modelio idempotency)

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

    def patch_step_verdict(
        self,
        step_index: int,
        *,
        status: str,
        reason: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> bool:
        """Replace the verdict on a previously-recorded step.

        Returns True if the step existed and was patched, False
        otherwise. Used by DebugSession.attach_verifier() so an
        external harness can add post-hoc verdicts to a step the
        producer left as unknown (#51)."""
        with self._lock:
            step = self._steps.get(step_index)
            if step is None:
                return False
            verdict: dict[str, Any] = {"status": status}
            if reason is not None:
                verdict["reason"] = reason
            if evidence_refs is not None:
                verdict["evidence_refs"] = evidence_refs
            step["verdict"] = verdict  # type: ignore[typeddict-item]
            return True

    def merge_step_verdict_score(
        self,
        step_index: int,
        *,
        score: float,
        comparator: str | None = None,
        components: dict[str, float] | None = None,
    ) -> bool:
        """Merge score-related fields into a step's existing verdict.

        Unlike `patch_step_verdict`, the categorical `status` and
        existing `reason`/`evidence_refs` are preserved. Used by
        DebugSession.set_score() (#59)."""
        with self._lock:
            step = self._steps.get(step_index)
            if step is None:
                return False
            verdict: dict[str, Any] = dict(step.get("verdict") or {"status": "unknown"})
            verdict["score"] = score
            if comparator is not None:
                verdict["comparator"] = comparator
            if components is not None:
                verdict["score_components"] = dict(components)
            step["verdict"] = verdict  # type: ignore[typeddict-item]
            return True

    def merge_step_costs(
        self,
        step_index: int,
        *,
        costs: dict[str, int | float],
    ) -> bool:
        """Merge a partial costs object into a step's existing costs.

        Existing keys are overwritten by the patch; absent keys are
        preserved. Used by DebugSession.set_step_costs() (#58)."""
        with self._lock:
            step = self._steps.get(step_index)
            if step is None:
                return False
            prior = step.get("costs") or {}
            existing: dict[str, Any] = dict(prior) if isinstance(prior, dict) else {}
            existing.update(costs)
            step["costs"] = existing  # type: ignore[typeddict-unknown-key]
            return True

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

    # -- modelio records (#56 producer side) --

    def reserve_modelio_path(
        self, *, step_index: int | None, layer: str
    ) -> str:
        """Allocate a unique modelio bundle-relative path.

        Convention: ``modelio/<step:04d>-<layer>-<seq>.json`` for
        step-scoped calls and ``modelio/run-<layer>-<seq>.json`` for
        run-scoped (step_index is None). Seq is per-(step, layer)
        monotonic starting at 0."""
        key = (step_index, layer)
        with self._lock:
            seq = self._modelio_seq_counter.get(key, 0)
            self._modelio_seq_counter[key] = seq + 1
        prefix = f"{step_index:04d}" if step_index is not None else "run"
        return f"modelio/{prefix}-{layer}-{seq}.json"

    def stage_modelio(
        self,
        relpath: str,
        record: dict[str, Any],
        *,
        prompt_hash: str | None = None,
    ) -> None:
        if not relpath.startswith("modelio/"):
            raise ValueError(f"modelio records must be under modelio/: {relpath!r}")
        with self._lock:
            self._modelio_records[relpath] = deepcopy(record)
            if prompt_hash is not None:
                self._modelio_hash_index[prompt_hash] = relpath

    def lookup_modelio_by_hash(self, prompt_hash: str) -> str | None:
        with self._lock:
            return self._modelio_hash_index.get(prompt_hash)

    def staged_modelio(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: deepcopy(v) for k, v in self._modelio_records.items()}

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
