"""Event recorder.

Accumulates StepTrace + DecisionEvent + Observation records in memory while
a session is active. The bundle writer drains the recorder when the session
closes.

Steps are keyed by ``step_id`` (since 0.3.0). Multiple steps may share the
same ``step_index`` — that's how brain-loop iterations under a canonical step
are addressed. The first ``step_id`` to land for a given ``step_index`` is the
canonical step; subsequent emissions with new ``step_id``s are iterations and
bump the canonical step's ``step_iterations`` counter (per
``step_trace.schema.json`` and augur-sdk#31). Re-recording a step under its
own ``step_id`` is still last-write-wins (the common ``running``→``succeeded``
update path).
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
        self._steps_by_id: dict[str, StepTrace] = {}
        # step_id → StepTrace. Insertion order preserved.
        self._step_ids_by_index: dict[int, list[str]] = {}
        # step_index → ordered list of step_ids that share it.
        # First entry is the canonical step; rest are iterations.
        self._events_by_step: dict[int | None, list[DecisionEvent]] = defaultdict(list)
        self._observation_bytes: dict[str, bytes] = {}
        # observation_bytes is keyed by bundle-relative path
        self._modelio_records: dict[str, dict[str, Any]] = {}
        # modelio is keyed by bundle-relative path (modelio/<step:04d>-<layer>-<seq>.json)
        self._modelio_seq_counter: dict[tuple[int | None, str], int] = {}
        # (step_index, layer) → next seq for path uniqueness
        self._modelio_hash_index: dict[str, str] = {}
        # prompt_hash → bundle-relative path (for record_modelio idempotency)
        self._eval_candidates: dict[int, dict[str, Any]] = {}
        # step_index → tag record (mark_for_eval, #16)
        self._outcomes: list[dict[str, Any]] = []
        # finalize_outcome records (#18)
        self._reasoning: list[dict[str, Any]] = []
        # record_reasoning records (#14)
        self._side_effects: dict[str, dict[str, Any]] = {}
        # side_effect_id → record (#11)

    # -- steps --

    def _canonical_locked(self, step_index: int) -> StepTrace | None:
        ids = self._step_ids_by_index.get(step_index)
        if not ids:
            return None
        return self._steps_by_id.get(ids[0])

    def record_step(self, step: StepTrace) -> bool:
        """Record a step. Returns True iff this call appended a new
        iteration under an existing canonical step (i.e. new ``step_id``
        at an already-recorded ``step_index``) — the session layer uses
        the return value to emit a ``DeprecationWarning`` per
        augur-sdk#31. Returns False for the create or update path
        (new ``step_index``, or update of an existing ``step_id``)."""
        if "step_index" not in step:
            raise ValueError("step is missing 'step_index'")
        if "step_id" not in step:
            raise ValueError("step is missing 'step_id'")
        sid = step["step_id"]
        sidx = step["step_index"]
        payload: StepTrace = deepcopy(dict(step))  # type: ignore[assignment]
        with self._lock:
            existing_ids = self._step_ids_by_index.setdefault(sidx, [])
            is_new_iteration = False
            if sid not in self._steps_by_id:
                if existing_ids:
                    is_new_iteration = True
                existing_ids.append(sid)
            self._steps_by_id[sid] = payload
            if len(existing_ids) > 1:
                canonical = self._steps_by_id[existing_ids[0]]
                canonical["step_iterations"] = len(existing_ids)
            return is_new_iteration

    def record_step_iteration(
        self, step_index: int, iteration: StepTrace
    ) -> None:
        """Append a brain-loop iteration under the canonical step at
        ``step_index``. Bumps ``step_iterations`` on the canonical step.

        Raises ``ValueError`` if no canonical step exists at
        ``step_index`` (call ``record_step`` first) or if the iteration
        carries the canonical step's ``step_id``."""
        if "step_id" not in iteration:
            raise ValueError("iteration is missing 'step_id'")
        sid = iteration["step_id"]
        payload: StepTrace = deepcopy(dict(iteration))  # type: ignore[assignment]
        payload["step_index"] = step_index
        with self._lock:
            existing_ids = self._step_ids_by_index.get(step_index)
            if not existing_ids:
                raise ValueError(
                    f"no canonical step at step_index={step_index}; "
                    "call record_step() first before recording iterations"
                )
            canonical_id = existing_ids[0]
            if sid == canonical_id:
                raise ValueError(
                    f"iteration step_id={sid!r} collides with the canonical "
                    f"step's id; use a distinct step_id per iteration"
                )
            if sid not in self._steps_by_id:
                existing_ids.append(sid)
            self._steps_by_id[sid] = payload
            canonical = self._steps_by_id[canonical_id]
            canonical["step_iterations"] = len(existing_ids)

    def get_step(self, step_index: int) -> StepTrace | None:
        """Return the canonical (first-recorded) step at ``step_index``."""
        with self._lock:
            step = self._canonical_locked(step_index)
            return deepcopy(step) if step is not None else None

    def get_step_by_id(self, step_id: str) -> StepTrace | None:
        with self._lock:
            return deepcopy(self._steps_by_id.get(step_id))

    def all_steps(self) -> list[StepTrace]:
        """Canonical steps in step_index order. Iterations are not
        included — they're addressable via ``iterations_for``."""
        with self._lock:
            return [
                deepcopy(self._steps_by_id[self._step_ids_by_index[i][0]])
                for i in sorted(self._step_ids_by_index)
            ]

    def iterations_for(self, step_index: int) -> list[StepTrace]:
        """All StepTraces sharing ``step_index`` in insertion order.
        The canonical step is first; iterations follow."""
        with self._lock:
            ids = self._step_ids_by_index.get(step_index, [])
            return [deepcopy(self._steps_by_id[sid]) for sid in ids]

    def iteration_count(self, step_index: int) -> int:
        with self._lock:
            return len(self._step_ids_by_index.get(step_index, []))

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
            step = self._canonical_locked(step_index)
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
            step = self._canonical_locked(step_index)
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

    def stage_side_effect(self, *, record: dict[str, Any]) -> None:
        """Stage or patch one side-effect record (#11). Keyed by
        ``side_effect_id``; subsequent calls replace the prior
        record."""
        sid = record.get("side_effect_id")
        if not isinstance(sid, str):
            raise ValueError(
                "side-effect record missing 'side_effect_id'"
            )
        with self._lock:
            self._side_effects[sid] = deepcopy(record)

    def get_side_effect(self, side_effect_id: str) -> dict[str, Any] | None:
        with self._lock:
            return deepcopy(self._side_effects.get(side_effect_id))

    def staged_side_effects(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                deepcopy(self._side_effects[k])
                for k in sorted(self._side_effects)
            ]

    def pending_side_effects(self) -> list[dict[str, Any]]:
        """Declared but not yet committed/aborted."""
        with self._lock:
            return [
                deepcopy(v)
                for v in self._side_effects.values()
                if v.get("status") == "intent_only"
            ]

    def record_reasoning(self, *, trace: dict[str, Any]) -> None:
        """Append a reasoning record (#14). Multiple per step OK."""
        with self._lock:
            self._reasoning.append(deepcopy(trace))

    def staged_reasoning(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(r) for r in self._reasoning]

    def stage_outcome(self, *, record: dict[str, Any]) -> None:
        """Stage one outcome record (#18)."""
        with self._lock:
            self._outcomes.append(deepcopy(record))

    def staged_outcomes(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(o) for o in self._outcomes]

    def mark_for_eval(
        self,
        *,
        step_index: int,
        reason: str,
        candidate_cluster_id: str | None,
        tagged_at: str,
    ) -> dict[str, Any]:
        """Tag a step as a regression-fixture candidate (#16).

        Idempotent on ``step_index`` — last-write-wins. Returns the
        stored tag record."""
        record: dict[str, Any] = {
            "step_index": step_index,
            "reason": reason,
            "tagged_at": tagged_at,
        }
        if candidate_cluster_id is not None:
            record["candidate_cluster_id"] = candidate_cluster_id
        with self._lock:
            self._eval_candidates[step_index] = deepcopy(record)
        return record

    def staged_eval_candidates(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(self._eval_candidates[i]) for i in sorted(self._eval_candidates)]

    def merge_step_captured_versions(
        self,
        step_index: int,
        *,
        versions: dict[str, str],
    ) -> bool:
        """Merge a partial captured_versions object into a step.

        Existing keys are overwritten by the patch; absent keys are
        preserved (last-write-wins). Used by
        DebugSession.set_step_versions() and the record_modelio
        auto-stamp path (#10)."""
        with self._lock:
            step = self._canonical_locked(step_index)
            if step is None:
                return False
            prior = step.get("captured_versions") or {}
            existing: dict[str, Any] = (
                dict(prior) if isinstance(prior, dict) else {}
            )
            existing.update(versions)
            step["captured_versions"] = existing  # type: ignore[typeddict-item]
            return True

    def append_judge_decision(
        self,
        step_index: int,
        *,
        decision: dict[str, Any],
        promote_verdict: bool,
        verdict_source: str | None = None,
    ) -> bool:
        """Append a judge decision to a step (#17).

        Multiple judge decisions per step are allowed. When
        ``promote_verdict`` is True, the decision's verdict object is
        copied onto ``step.verdict`` (last-write-wins) and
        ``step.verdict_source`` is set to ``verdict_source`` for
        provenance."""
        with self._lock:
            step = self._canonical_locked(step_index)
            if step is None:
                return False
            existing = step.get("judge_decisions") or []
            decisions: list[Any] = list(existing)
            decisions.append(deepcopy(decision))
            step["judge_decisions"] = decisions
            if promote_verdict:
                verdict = decision.get("verdict")
                if isinstance(verdict, dict):
                    step["verdict"] = dict(verdict)  # type: ignore[typeddict-item]
                if verdict_source is not None:
                    step["verdict_source"] = verdict_source
            return True

    def merge_step_env_fingerprint(
        self,
        step_index: int,
        *,
        fingerprint: dict[str, Any],
    ) -> bool:
        """Merge a partial env_fingerprint object into a step (#13)."""
        with self._lock:
            step = self._canonical_locked(step_index)
            if step is None:
                return False
            prior = step.get("env_fingerprint") or {}
            existing: dict[str, Any] = (
                dict(prior) if isinstance(prior, dict) else {}
            )
            existing.update(fingerprint)
            step["env_fingerprint"] = existing  # type: ignore[typeddict-item]
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
            step = self._canonical_locked(step_index)
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
                "steps": [
                    deepcopy(self._steps_by_id[self._step_ids_by_index[i][0]])
                    for i in sorted(self._step_ids_by_index)
                ],
                "events": {
                    k: [deepcopy(e) for e in v] for k, v in self._events_by_step.items()
                },
                "observation_bytes_count": len(self._observation_bytes),
            }


__all__ = ["EventRecorder"]
