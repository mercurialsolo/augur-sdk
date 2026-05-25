"""DebugSession — top-level capture controller.

Spec §6 calls out four SDK components: capture controller, event recorder,
redaction pipeline, bundle writer. This module is the controller that
wires them together.

Public surface:

    with DebugSession(...) as session:
        session.record_step({...})
        session.record_event({...})
        session.attach_observation(step_index=0, kind="pre", png_bytes=...)
"""

from __future__ import annotations

import uuid
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from augur_schema import SCHEMA_VERSION, validator_for
from jsonschema.exceptions import ValidationError

from augur_sdk.bundle import write_bundle
from augur_sdk.capture import CaptureMode, resolve_capture_mode
from augur_sdk.intervention import InterventionChannel
from augur_sdk.models import BundleManifest, DecisionEvent, StepTrace
from augur_sdk.models import DebugSession as SessionRecord
from augur_sdk.recorder import EventRecorder
from augur_sdk.redaction import DefaultRedactionPolicy, RedactionPolicy
from augur_sdk.storage import LocalFSStore, Store
from augur_sdk.streaming import DSN, StreamingSink

_VERDICT_COMPARATORS = {"verifier", "model-judge", "exact-match", "human"}


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _gen_debug_session_id() -> str:
    return f"dbg_{uuid.uuid4().hex[:16]}"


class DebugSession:
    """Capture controller. Use as a context manager."""

    def __init__(
        self,
        *,
        run_id: str,
        client_name: str,
        out_dir: str | Path,
        client_version: str | None = None,
        client_git_sha: str | None = None,
        capture_mode: CaptureMode | str | None = None,
        debug_session_id: str | None = None,
        redaction_policy: RedactionPolicy | None = None,
        store: Store | None = None,
        tags: dict[str, str] | None = None,
        started_at: str | None = None,
        dsn: str | None = None,
        branch_context: dict[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.debug_session_id = debug_session_id or _gen_debug_session_id()
        self.capture_mode = resolve_capture_mode(capture_mode)
        self.redaction_policy = redaction_policy or DefaultRedactionPolicy()
        self._client_name = client_name
        self._client_version = client_version
        self._client_git_sha = client_git_sha
        self._out_dir = Path(out_dir)
        self._store: Store = store if store is not None else LocalFSStore(self._out_dir)
        self._tags = dict(tags or {})
        self._recorder = EventRecorder()
        self._started_at = started_at or _utcnow_iso()
        self._ended_at: str | None = None
        self._status: str = "running"
        self._open = False
        self._manifest: BundleManifest | None = None
        self._live_endpoints: dict[str, str] = {}
        # Optional per-step capture_mode override (#36). Set via
        # set_capture_mode(); None means "inherit manifest mode" and
        # no `capture_mode` field is stamped on the step.
        self._capture_mode_override: str | None = None
        # Session-level cost rollup (#58). Populated by set_costs();
        # surfaces on both the session record and the manifest.
        self._session_costs: dict[str, int | float] = {}
        # #15: BranchContext labels replay-branch trajectories so
        # server-side cohort filters can exclude branches by default.
        # Production runs leave this as None.
        self._branch_context: dict[str, Any] | None = (
            self._validate_branch_context(branch_context)
            if branch_context is not None
            else None
        )
        # Optional streaming sink (Sentry-style). DSN arg wins; otherwise
        # consult AUGUR_DSN env var. None disables streaming.
        parsed_dsn = DSN.from_env(dsn)
        self._stream: StreamingSink | None = (
            StreamingSink(parsed_dsn, client_name=client_name, client_version=client_version)
            if parsed_dsn
            else None
        )
        # Parsed DSN cached for the intervention channel; bind_intervention
        # needs the base URL and token to long-poll.
        self._dsn: DSN | None = parsed_dsn
        self._intervention: InterventionChannel | None = None
        # #25: set by branch_from() classmethod when constructing a
        # replay-branch session; None for production runs.
        self._branch_mode: str | None = None

    # -- branching replay (#25) -----------------------------------------

    @classmethod
    def branch_from(
        cls,
        *,
        parent_run_id: str,
        branch_point_step_index: int,
        mutated_axis: str,
        mutation: dict[str, Any],
        client_name: str,
        out_dir: str | Path,
        mode: str = "auto",
        parent_bundle: str | Path | None = None,
        branch_id: str | None = None,
        run_id: str | None = None,
        **session_kwargs: Any,
    ) -> DebugSession:
        """Construct a child session that records a replay branch off a parent run.

        The child session is stamped with a ``branch_context`` that
        carries ``parent_run_id``, ``branch_point_step_index``,
        ``mutated_axis``, ``mutation``, and ``branch_id`` so the platform
        can exclude branches from production cohorts by default
        (`mercurialsolo/augur#91`).

        ``mode`` controls what happens to steps before the branch point:

        - ``replay``: load steps ``[0, branch_point_step_index)`` from
          ``parent_bundle`` and record them on the new session so the
          branch's bundle includes the deterministic prefix without
          re-execution. Per-step pre/post screenshots are copied over
          when present on disk. Requires ``parent_bundle`` to point at
          a valid Augur bundle directory.
        - ``sandbox``: stamp ``branch_context`` only; the producer
          executes from step 0 against a live sandbox. No prefix loading.
        - ``auto`` (default): pick ``sandbox`` when ``mutated_axis ==
          "action"`` (action changes break the deterministic-prefix
          assumption) and ``replay`` otherwise.

        ``branch_id`` defaults to ``f"{parent_run_id}:branch:<short-uuid>"``;
        ``run_id`` defaults to ``branch_id``.

        Raises ``ValueError`` for:

        - ``mode == "replay"`` with ``mutated_axis == "action"`` —
          replay would lie about what the agent did.
        - ``mode == "replay"`` without ``parent_bundle``.
        - ``mutated_axis`` outside the canonical 5-axis enum.
        - ``branch_point_step_index < 0``.
        """
        allowed_axes = {"model", "prompt", "action", "grounder", "tool_description"}
        if mutated_axis not in allowed_axes:
            raise ValueError(
                f"mutated_axis must be one of {sorted(allowed_axes)}, "
                f"got {mutated_axis!r}"
            )
        if branch_point_step_index < 0:
            raise ValueError(
                f"branch_point_step_index must be >= 0, got {branch_point_step_index}"
            )
        if mode not in ("replay", "sandbox", "auto"):
            raise ValueError(
                f"mode must be 'replay'|'sandbox'|'auto', got {mode!r}"
            )

        resolved_mode = mode
        if resolved_mode == "auto":
            # SPEC §10: action changes break the deterministic-prefix
            # assumption, so auto downgrades to sandbox.
            resolved_mode = "sandbox" if mutated_axis == "action" else "replay"

        if resolved_mode == "replay" and mutated_axis == "action":
            raise ValueError(
                "replay mode is unsound when mutated_axis='action' — "
                "action changes mean the parent's downstream observations "
                "no longer reflect what the agent will see. Use "
                "mode='sandbox' to execute fresh against a live target."
            )
        if resolved_mode == "replay" and parent_bundle is None:
            raise ValueError(
                "replay mode needs parent_bundle to load the deterministic "
                "prefix from. Pass parent_bundle=<path-to-parent-Augur-bundle> "
                "or use mode='sandbox'."
            )

        resolved_branch_id = (
            branch_id or f"{parent_run_id}:branch:{uuid.uuid4().hex[:8]}"
        )
        resolved_run_id = run_id or resolved_branch_id

        branch_context: dict[str, Any] = {
            "parent_run_id": parent_run_id,
            "branch_point_step_index": branch_point_step_index,
            "mutated_axis": mutated_axis,
            "mutation": dict(mutation),
            "branch_id": resolved_branch_id,
        }

        # Strip any conflicting keys callers might pass via **session_kwargs.
        session_kwargs.pop("run_id", None)
        session_kwargs.pop("client_name", None)
        session_kwargs.pop("out_dir", None)
        session_kwargs.pop("branch_context", None)

        session = cls(
            run_id=resolved_run_id,
            client_name=client_name,
            out_dir=out_dir,
            branch_context=branch_context,
            **session_kwargs,
        )

        # Replay mode: pre-load the parent's prefix into the new session's
        # recorder. Pre/post screenshot bytes are copied verbatim. The new
        # session's record_step path will stamp branch_context on every
        # prefix step automatically (the same way it does for fresh steps).
        if resolved_mode == "replay":
            session._preload_parent_prefix(
                parent_bundle=Path(parent_bundle),  # type: ignore[arg-type]
                branch_point_step_index=branch_point_step_index,
            )

        # Expose the resolved mode so callers and tests can introspect.
        session._branch_mode = resolved_mode
        return session

    def _preload_parent_prefix(
        self,
        *,
        parent_bundle: Path,
        branch_point_step_index: int,
    ) -> None:
        """Load steps [0, branch_point_step_index) from ``parent_bundle``
        into this session, copying screenshots verbatim (#25).

        Opens the session for recording so the standard ``record_step``
        path runs (branch_context stamping, streaming sink). Leaves the
        session open afterwards — the caller is expected to enter the
        context manager and continue from ``branch_point_step_index``.
        """
        trace_path = parent_bundle / "trace.json"
        if not trace_path.exists():
            raise FileNotFoundError(
                f"parent_bundle does not contain trace.json: {parent_bundle}"
            )
        import json as _json

        with trace_path.open(encoding="utf-8") as f:
            trace = _json.load(f)
        steps = trace.get("steps") or []

        # Drive record_step through the public API so streaming sinks
        # and branch_context stamping fire the same way as for fresh
        # steps. Temporarily open the session so record_step's
        # _require_open() check passes; this is the only path that
        # records before the user's `with` block.
        was_open = self._open
        self._open = True
        try:
            for step in steps:
                idx = step.get("step_index")
                if not isinstance(idx, int):
                    continue
                if idx >= branch_point_step_index:
                    break
                # Copy screenshot bytes for this step before recording it
                # so attach_observation paths resolve correctly later.
                for kind in ("pre", "post"):
                    relpath = step.get(f"observation_{kind}")
                    if not isinstance(relpath, str) or not relpath.startswith(
                        "screenshots/"
                    ):
                        continue
                    src = parent_bundle / relpath
                    if not src.exists():
                        continue
                    self._recorder.stage_observation_bytes(
                        relpath, src.read_bytes()
                    )
                # record_step deep-copies so we don't share mutable refs
                # with the parent bundle.
                self.record_step(dict(step))  # type: ignore[arg-type]
        finally:
            self._open = was_open

    # -- lifecycle --

    def __enter__(self) -> DebugSession:
        self._open = True
        if self._stream is not None:
            self._stream.begin(run_id=self.run_id, capture_mode=self.capture_mode.value)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc is not None and self._status == "running":
            self._status = "halted"
        self.close()

    def close(self, status: str | None = None) -> BundleManifest:
        """Write the bundle and return the manifest."""
        if not self._open:
            raise RuntimeError("DebugSession.close() called on a session that was never opened")
        self._open = False
        if status is not None:
            self._status = status
        elif self._status == "running":
            self._status = "succeeded"
        self._ended_at = _utcnow_iso()
        # #12: stop the intervention long-poll before the bundle write
        # so a stray late-arriving command can't race the final flush.
        if self._intervention is not None:
            self._intervention.stop()
            self._intervention = None
        record = self._session_record()
        if self.capture_mode is CaptureMode.OFF:
            # Honour the contract: off mode writes only the manifest envelope so
            # consumers can see the run existed. No steps/events/screenshots.
            self._manifest = write_bundle(
                store=self._store,
                session=record,
                recorder=EventRecorder(),  # empty
                policy=self.redaction_policy,
            )
        else:
            self._manifest = write_bundle(
                store=self._store,
                session=record,
                recorder=self._recorder,
                policy=self.redaction_policy,
            )
        if self._stream is not None and self._manifest is not None:
            # Final flush — manifest carries final step_count + signatures.
            self._stream.post_manifest(dict(self._manifest))
            # Also send the full trace so the server has session metadata
            # immediately (no need to wait for a reader to assemble it).
            trace_payload = {"session": record, "steps": self._recorder.all_steps()}
            self._stream.put_trace(self.redaction_policy.apply(trace_payload))
            self._stream.end()
        return self._manifest

    # -- recording --

    def record_step(self, step: StepTrace) -> None:
        self._require_open()
        # Per-step capture_mode override (#36): if set_capture_mode()
        # changed the active mode since the last record_step, stamp
        # the override onto this step (and only this one; the override
        # persists in self._capture_mode_override for subsequent
        # record_step calls until explicitly cleared).
        if self._capture_mode_override and "capture_mode" not in step:
            step["capture_mode"] = self._capture_mode_override  # type: ignore[typeddict-unknown-key]
        # #15: propagate BranchContext (sans mutation payload) to every
        # step so server-side filters can exclude branches by default
        # without joining back to the session.
        if self._branch_context is not None and "branch_context" not in step:
            step["branch_context"] = self._step_branch_context()  # type: ignore[typeddict-item]
        is_new_iteration = self._recorder.record_step(step)
        if is_new_iteration:
            # augur-sdk#31: per-iteration emission should go through
            # record_step_iteration() so the canonical step's
            # step_iterations counter and the per-iteration bundle path
            # are managed together.
            warnings.warn(
                "record_step() with a new step_id at an existing "
                "step_index is deprecated; use "
                "DebugSession.record_step_iteration() to append "
                "iterations under the canonical step.",
                DeprecationWarning,
                stacklevel=2,
            )
        if self._stream is not None:
            redacted = self.redaction_policy.apply(dict(step))
            self._stream.put_step(redacted)
            if is_new_iteration:
                # Mirror the canonical step (now carrying an updated
                # step_iterations counter) so the live runs-list reflects
                # the new iteration count without waiting for close().
                canonical_idx = step.get("step_index")
                if isinstance(canonical_idx, int):
                    canonical = self._recorder.get_step(canonical_idx)
                    if canonical is not None:
                        self._stream.put_step(
                            self.redaction_policy.apply(dict(canonical))
                        )

    def record_step_iteration(
        self,
        step_id_or_index: str | int,
        iteration: StepTrace,
    ) -> None:
        """Append a brain-loop iteration under an existing canonical
        step. Bumps ``step_iterations`` on the canonical step and
        stages the iteration payload at
        ``steps/<NNNN>/<short_id>.json`` on close (augur-sdk#31).

        ``step_id_or_index`` resolves the canonical step: pass the
        canonical's ``step_id`` for explicit linkage, or its
        ``step_index`` when iterations always share the same canonical
        slot (Mantis-style agent loops).

        ``iteration`` is a ``StepTrace`` dict; it MUST carry a
        ``step_id`` distinct from the canonical's. The SDK forces
        ``step_index`` to match the resolved canonical step.

        Raises ``ValueError`` if no canonical step exists at the
        resolved index (call :py:meth:`record_step` first)."""
        self._require_open()
        if isinstance(step_id_or_index, int):
            canonical_idx = step_id_or_index
        else:
            canonical = self._recorder.get_step_by_id(step_id_or_index)
            if canonical is None:
                raise ValueError(
                    f"no canonical step with step_id={step_id_or_index!r}; "
                    "call record_step() first before recording iterations"
                )
            canonical_idx_any = canonical.get("step_index")
            if not isinstance(canonical_idx_any, int):
                raise ValueError(
                    f"canonical step {step_id_or_index!r} is missing step_index"
                )
            canonical_idx = canonical_idx_any
        iter_payload: StepTrace = dict(iteration)  # type: ignore[assignment]
        if (
            self._capture_mode_override
            and "capture_mode" not in iter_payload
        ):
            iter_payload["capture_mode"] = self._capture_mode_override  # type: ignore[typeddict-unknown-key]
        if (
            self._branch_context is not None
            and "branch_context" not in iter_payload
        ):
            iter_payload["branch_context"] = self._step_branch_context()  # type: ignore[typeddict-item]
        self._recorder.record_step_iteration(canonical_idx, iter_payload)
        if self._stream is not None:
            # Stream the iteration's StepTrace; the server's idempotency
            # on (run_id, step_index) means consumers without
            # iteration-aware aggregation see the latest, while
            # iteration-aware consumers can read the bumped counter from
            # the canonical re-emission below.
            self._stream.put_step(
                self.redaction_policy.apply(dict(iter_payload))
            )
            canonical = self._recorder.get_step(canonical_idx)
            if canonical is not None:
                self._stream.put_step(
                    self.redaction_policy.apply(dict(canonical))
                )

    def record_event(self, event: DecisionEvent) -> None:
        self._require_open()
        self._recorder.record_event(event)
        if self._stream is not None:
            redacted = self.redaction_policy.apply(dict(event))
            step_index = event.get("step_index")
            self._stream.post_events([redacted], step_index=step_index)

    def attach_observation(
        self,
        *,
        step_index: int,
        kind: str,
        png_bytes: bytes,
    ) -> str:
        """Stage a PNG screenshot. Returns the bundle-relative path that the
        adapter SHOULD assign to `step.observation_pre/post`."""
        self._require_open()
        if kind not in ("pre", "post"):
            raise ValueError(f"kind must be 'pre' or 'post', got {kind!r}")
        relpath = f"screenshots/{step_index:04d}_{kind}.png"
        self._recorder.stage_observation_bytes(relpath, png_bytes)
        if self._stream is not None:
            self._stream.post_screenshot(step_index, kind, png_bytes)
        return relpath

    def set_status(self, status: str) -> None:
        """Override the run's terminal status. Otherwise inferred at close time."""
        self._status = status

    def set_capture_mode(self, mode: str | CaptureMode) -> None:
        """Change the active capture mode from this point forward.

        The next :py:meth:`record_step` (and every subsequent one) gets
        an explicit ``capture_mode`` field stamped on the StepTrace
        with the new mode, per `step_trace.schema.json` (#36). Use to
        upgrade — e.g. ``session.set_capture_mode("screenshots")``
        after the first failed verifier — without restarting the
        session.

        The manifest's ``capture_mode`` (set at construction) remains
        the default for steps that don't carry an override.
        """
        self._require_open()
        if isinstance(mode, CaptureMode):
            self._capture_mode_override = mode.value
        else:
            # Validate against the canonical enum without forcing
            # callers to import the enum.
            self._capture_mode_override = resolve_capture_mode(mode).value

    def attach_verifier(
        self,
        step_index: int,
        *,
        status: str,
        reason: str | None = None,
        check: str | None = None,
        expected: Any = None,
        actual: Any = None,
        evidence_refs: list[str] | None = None,
    ) -> None:
        """Add a post-hoc verdict to a previously-recorded step (#51).

        For traces whose native format carries no verifier signal
        (OpenAI / Anthropic Computer-Use, raw OSWorld), an external
        harness can call this after running its own check against the
        step's post-state. The step's `verdict` field is replaced
        in-place; on close, the bundle reflects the attached verdict.

        ``status`` follows the canonical verdict enum (passed, failed,
        recoverable, skipped, unknown). ``check`` / ``expected`` /
        ``actual`` are folded into ``verdict.reason`` for traceability
        when no explicit reason is provided.

        Precedence (documented contract):
          native verdict > attach_verifier > inferred default

        i.e. if the producer already recorded a non-unknown verdict,
        attach_verifier overrides it. Callers who want the gentler
        "fill in only when missing" behavior can check via
        :py:meth:`step` first.
        """
        self._require_open()
        composed_reason = reason
        if composed_reason is None and check is not None:
            composed_reason = (
                f"{check}: expected={expected!r} actual={actual!r}"
            )
        ok = self._recorder.patch_step_verdict(
            step_index,
            status=status,
            reason=composed_reason,
            evidence_refs=evidence_refs,
        )
        if not ok:
            raise ValueError(
                f"attach_verifier: no step at step_index={step_index}. "
                f"Record the step first via record_step()."
            )
        # #17: emit a JudgeDecision with judge_type="rule" so the
        # provenance is preserved alongside the operative verdict.
        # Use a stable, anonymous judge_id since attach_verifier is
        # the legacy entry point without an explicit judge identity.
        rule_decision: dict[str, Any] = {
            "judge_id": check or "attach_verifier",
            "judge_type": "rule",
            "verdict": {"status": status},
            "judged_at": _utcnow_iso(),
        }
        if composed_reason is not None:
            rule_decision["verdict"]["reason"] = composed_reason
        if evidence_refs is not None:
            rule_decision["verdict"]["evidence_refs"] = list(evidence_refs)
            rule_decision["evidence_refs"] = list(evidence_refs)
        self._recorder.append_judge_decision(
            step_index,
            decision=rule_decision,
            promote_verdict=False,
        )
        # Echo through the streaming sink so live viewers see the
        # patched verdict without waiting for close().
        if self._stream is not None:
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def set_score(
        self,
        step_index: int,
        score: float,
        *,
        comparator: str | None = None,
        components: dict[str, float] | None = None,
    ) -> None:
        """Attach a continuous reward signal to a recorded step's verdict (#59).

        Merges into the existing verdict object — the categorical
        ``status`` is preserved. ``score`` is clamped to [0.0, 1.0].
        ``comparator`` must be one of the canonical values:
        ``verifier``, ``model-judge``, ``exact-match``, ``human``.
        ``components`` is a free-form breakdown (per-criterion
        contributions); each value SHOULD be a float in [0,1] but
        the schema does not enforce that.

        Raises ``ValueError`` when no step exists at ``step_index``
        or when ``comparator`` is not in the canonical set.
        """
        self._require_open()
        if comparator is not None and comparator not in _VERDICT_COMPARATORS:
            raise ValueError(
                f"comparator must be one of {sorted(_VERDICT_COMPARATORS)}, "
                f"got {comparator!r}"
            )
        clamped = max(0.0, min(1.0, float(score)))
        ok = self._recorder.merge_step_verdict_score(
            step_index,
            score=clamped,
            comparator=comparator,
            components=components,
        )
        if not ok:
            raise ValueError(
                f"set_score: no step at step_index={step_index}. "
                f"Record the step first via record_step()."
            )
        if self._stream is not None:
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def set_costs(
        self,
        *,
        total_usd: float | None = None,
        model_usd: float | None = None,
        gpu_usd: float | None = None,
        proxy_usd: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cache_hit_tokens: int | None = None,
    ) -> None:
        """Stamp a structured cost rollup on the session (#58).

        Surfaces on both the session record (``trace.json``) and the
        manifest (``manifest.json#/costs``) so cost-aware consumers
        (run-list dashboards, training pipelines) can read either.
        Repeated calls overwrite previously-set fields; unset fields
        are preserved across calls. Pass only the dimensions you
        measured.

        When streaming is enabled (``dsn`` configured), the cumulative
        ``_session_costs`` dict is PUT to ``/runs/{run_id}/costs``
        immediately (#34) so the live runs-list COST column reflects
        the producer's running total without waiting for ``close()``.
        Server is idempotent last-write-wins; 429 backpressure is
        absorbed by the shared retry helper.
        """
        self._require_open()
        mutated = False
        for name, value in {
            "total_usd": total_usd,
            "model_usd": model_usd,
            "gpu_usd": gpu_usd,
            "proxy_usd": proxy_usd,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_hit_tokens": cache_hit_tokens,
        }.items():
            if value is not None:
                self._session_costs[name] = value
                mutated = True
        if mutated and self._stream is not None:
            self._stream.put_session_costs(dict(self._session_costs))

    def set_step_costs(
        self,
        step_index: int,
        *,
        total_usd: float | None = None,
        model_usd: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cache_hit_tokens: int | None = None,
    ) -> None:
        """Patch a previously-recorded step's structured costs (#58).

        Merges into any existing ``step.costs`` object; unset keys
        are preserved. Raises ``ValueError`` if no step exists at
        ``step_index``.
        """
        self._require_open()
        patch: dict[str, int | float] = {}
        for name, value in {
            "total_usd": total_usd,
            "model_usd": model_usd,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_hit_tokens": cache_hit_tokens,
        }.items():
            if value is not None:
                patch[name] = value
        if not patch:
            return
        ok = self._recorder.merge_step_costs(step_index, costs=patch)
        if not ok:
            raise ValueError(
                f"set_step_costs: no step at step_index={step_index}. "
                f"Record the step first via record_step()."
            )
        if self._stream is not None:
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def bind_intervention(
        self,
        adapter: Any,
        *,
        poll_timeout: float = 25.0,
    ) -> InterventionChannel | None:
        """Wire up the server→SDK intervention channel (#12).

        Starts a long-poll loop on
        ``GET <DSN-base>/runs/<run_id>/commands`` that dispatches
        pause/resume/kill/inject_hint/override_action commands to
        ``adapter``. Returns the started channel, or ``None`` if
        streaming is disabled (no DSN configured).

        The channel runs on a background thread; commands arrive
        between steps with latency bounded by ``poll_timeout``.
        Adapters that don't implement a particular hook see the
        channel degrade to a no-op for that command type — never a
        raised exception.

        Couples to #11: when a ``kill`` command arrives, the channel
        calls :py:meth:`abort_pending_side_effects` before invoking
        ``adapter.on_kill()`` so the ledger doesn't show dangling
        ``intent_only`` declarations.
        """
        self._require_open()
        if self._dsn is None:
            return None
        channel = InterventionChannel(
            session=self,  # type: ignore[arg-type]
            adapter=adapter,
            base_url=self._dsn.base_url,
            token=self._dsn.token,
            poll_timeout=poll_timeout,
        )
        channel.start()
        self._intervention = channel
        return channel

    def declare_side_effect(
        self,
        step_index: int,
        resource: str,
        action: str,
        *,
        idempotency_key: str | None = None,
        reversibility: str = "irreversible",
        compensation_handle: str | None = None,
        provenance: str = "sdk_declared",
        side_effect_id: str | None = None,
        declared_at: str | None = None,
    ) -> str:
        """Declare an irreversible agent action BEFORE dispatch (#11).

        Recording the declaration before dispatch means that, if the
        run is killed mid-step, the ledger still shows the agent's
        intent — "the agent was about to charge this card" — even
        though the commit record never lands.

        Returns the generated ``side_effect_id`` so callers can pass
        it to :py:meth:`commit_side_effect` after dispatch returns.

        Raises ``ValueError`` for unknown ``reversibility`` or
        ``provenance``.
        """
        self._require_open()
        if reversibility not in ("irreversible", "reversible", "compensated"):
            raise ValueError(
                f"reversibility must be irreversible|reversible|compensated, "
                f"got {reversibility!r}"
            )
        if provenance not in ("sdk_declared", "adapter_inferred", "human_declared"):
            raise ValueError(
                f"provenance must be sdk_declared|adapter_inferred|human_declared, "
                f"got {provenance!r}"
            )
        sid = side_effect_id or f"se_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "side_effect_id": sid,
            "step_index": step_index,
            "resource": resource,
            "action": action,
            "reversibility": reversibility,
            "provenance": provenance,
            "status": "intent_only",
            "declared_at": declared_at or _utcnow_iso(),
        }
        # Best-effort link to the canonical step_id if the step is
        # already recorded; producers MAY call declare_side_effect
        # before record_step lands.
        step = self._recorder.get_step(step_index)
        if step is not None:
            step_id = step.get("step_id")
            if isinstance(step_id, str):
                record["step_id"] = step_id
        if idempotency_key is not None:
            record["idempotency_key"] = idempotency_key
        if compensation_handle is not None:
            record["compensation_handle"] = compensation_handle
        redacted = self.redaction_policy.apply(record)
        if not isinstance(redacted, dict):
            redacted = record
        self._recorder.stage_side_effect(record=redacted)
        if self._stream is not None:
            self._stream.post_side_effect(dict(redacted))
        return sid

    def commit_side_effect(
        self,
        side_effect_id: str,
        observed_result: Any = None,
        *,
        committed_at: str | None = None,
    ) -> None:
        """Mark a declared side effect as committed (#11).

        Call after the dispatcher returns. ``observed_result`` is the
        raw return payload; the session's redaction policy is applied
        before persistence (PII may live there).

        Raises ``ValueError`` when ``side_effect_id`` is unknown or
        already terminal.
        """
        self._require_open()
        record = self._recorder.get_side_effect(side_effect_id)
        if record is None:
            raise ValueError(
                f"commit_side_effect: unknown side_effect_id={side_effect_id!r}. "
                f"Declare it first via declare_side_effect()."
            )
        if record.get("status") in ("committed", "aborted"):
            raise ValueError(
                f"commit_side_effect: side_effect_id={side_effect_id!r} "
                f"is already {record['status']!r}"
            )
        record["status"] = "committed"
        record["committed_at"] = committed_at or _utcnow_iso()
        if observed_result is not None:
            record["observed_result"] = observed_result
        redacted = self.redaction_policy.apply(record)
        if not isinstance(redacted, dict):
            redacted = record
        self._recorder.stage_side_effect(record=redacted)
        if self._stream is not None:
            self._stream.post_side_effect(dict(redacted))

    def mark_side_effect_aborted(
        self,
        side_effect_id: str,
        reason: str,
        *,
        aborted_at: str | None = None,
    ) -> None:
        """Mark a declared side effect as aborted (#11).

        Called when a kill signal arrives between declare and commit.
        The intervention channel (#12) wires kill → mark_aborted for
        every pending declaration on the runner's behalf, so adapters
        typically don't need to call this directly.
        """
        self._require_open()
        record = self._recorder.get_side_effect(side_effect_id)
        if record is None:
            raise ValueError(
                f"mark_side_effect_aborted: unknown side_effect_id={side_effect_id!r}"
            )
        if record.get("status") in ("committed", "aborted"):
            raise ValueError(
                f"mark_side_effect_aborted: side_effect_id={side_effect_id!r} "
                f"is already {record['status']!r}"
            )
        record["status"] = "aborted"
        record["aborted_at"] = aborted_at or _utcnow_iso()
        record["abort_reason"] = reason
        redacted = self.redaction_policy.apply(record)
        if not isinstance(redacted, dict):
            redacted = record
        self._recorder.stage_side_effect(record=redacted)
        if self._stream is not None:
            self._stream.post_side_effect(dict(redacted))

    def abort_pending_side_effects(self, reason: str) -> list[str]:
        """Abort every declared-but-not-committed side effect (#11).

        Returns the list of aborted ``side_effect_id``s. Used by the
        intervention channel (#12) when a kill command arrives, so
        the ledger doesn't show declarations dangling at
        ``intent_only`` forever.
        """
        self._require_open()
        pending = self._recorder.pending_side_effects()
        aborted: list[str] = []
        for record in pending:
            sid = record["side_effect_id"]
            self.mark_side_effect_aborted(sid, reason=reason)
            aborted.append(sid)
        return aborted

    def record_reasoning(
        self,
        step_index: int | None,
        text: str,
        *,
        tokens: int | None = None,
        format: str = "adapter_inferred",
        model: str | None = None,
        ts: str | None = None,
    ) -> dict[str, Any]:
        """Capture an explicit reasoning trace (#14).

        For models that emit reasoning (Claude extended thinking,
        OpenAI reasoning summaries), the failure is often visible in
        the reasoning before the action goes wrong. Today reasoning
        is stuffed into ``DecisionEvent.detail`` unstructured;
        ``record_reasoning()`` makes it first-class so the platform
        can search and filter across.

        Multiple reasoning records per step are allowed (representing
        multiple model calls per step). Reasoning text is redacted
        via the session's ``RedactionPolicy.apply_reasoning()`` hook,
        which runs both the regular redactors and any
        reasoning-specific redactors registered with
        ``add_reasoning_redactor()``.

        Returns the redacted trace as recorded.
        """
        self._require_open()
        if format not in (
            "adapter_inferred",
            "claude_extended_thinking",
            "openai_reasoning_summary",
        ):
            raise ValueError(
                f"format must be one of adapter_inferred|"
                f"claude_extended_thinking|openai_reasoning_summary, "
                f"got {format!r}"
            )
        trace: dict[str, Any] = {
            "ts": ts or _utcnow_iso(),
            "text": text,
            "format": format,
        }
        if step_index is not None:
            trace["step_index"] = step_index
        if tokens is not None:
            trace["tokens"] = tokens
        if model is not None:
            trace["model"] = model
        redacted = self.redaction_policy.apply_reasoning(trace)
        self._recorder.record_reasoning(trace=redacted)
        if self._stream is not None:
            self._stream.post_reasoning(dict(redacted))
        return redacted

    def finalize_outcome(
        self,
        *,
        scope: str = "session",
        step_index: int | None = None,
        verdict: dict[str, Any] | None = None,
        task_class: str | None = None,
        cost_summary: dict[str, int | float] | None = None,
    ) -> dict[str, Any]:
        """Couple verdict + cost + task_class into one OutcomeRecord (#18).

        ``scope="step"`` records a per-step outcome (``step_index``
        required); ``scope="session"`` rolls up costs and records a
        single session-level outcome. Both end up in
        ``outcomes.json`` at the bundle root and on the live stream.

        For ``scope="session"`` when ``cost_summary`` is None, the SDK
        rolls up:
          - the session-level costs set via ``set_costs()``;
          - the sum of per-step ``step.costs`` for any field absent
            at the session level.

        For ``scope="step"`` when ``verdict`` is None and the step
        already carries a verdict, that one is used.

        Returns the recorded outcome record.
        """
        self._require_open()
        if scope not in ("step", "session"):
            raise ValueError(f"scope must be 'step' or 'session', got {scope!r}")

        finalized_at = _utcnow_iso()
        record: dict[str, Any] = {
            "scope": scope,
            "run_id": self.run_id,
            "finalized_at": finalized_at,
        }
        if task_class is not None:
            record["task_class"] = task_class

        if scope == "step":
            if step_index is None:
                raise ValueError("scope='step' requires step_index")
            step = self._recorder.get_step(step_index)
            if step is None:
                raise ValueError(
                    f"finalize_outcome: no step at step_index={step_index}"
                )
            record["step_index"] = step_index
            record["step_id"] = step.get("step_id")
            record["verdict"] = (
                dict(verdict) if verdict is not None else dict(step.get("verdict") or {})
            )
            if cost_summary is not None:
                record["cost_summary"] = dict(cost_summary)
            else:
                step_costs = step.get("costs")
                if isinstance(step_costs, dict):
                    record["cost_summary"] = dict(step_costs)
        else:
            record["debug_session_id"] = self.debug_session_id
            if verdict is not None:
                record["verdict"] = dict(verdict)
            if cost_summary is not None:
                record["cost_summary"] = dict(cost_summary)
            else:
                record["cost_summary"] = self._rolled_up_session_costs()

        self._recorder.stage_outcome(record=record)
        if self._stream is not None:
            redacted = self.redaction_policy.apply(dict(record))
            if isinstance(redacted, dict):
                self._stream.post_outcome(redacted)
        return record

    def successful_task_cost_summary(self) -> dict[str, int | float] | None:
        """Return a rolled-up cost summary for callers who want to
        assert budgets in-process (#18). Returns None when no costs
        have been recorded."""
        rolled = self._rolled_up_session_costs()
        return rolled or None

    def _rolled_up_session_costs(self) -> dict[str, int | float]:
        """Combine session-level costs with the sum of per-step costs.

        Session-level fields win for any key they set; absent keys are
        filled by summing the corresponding per-step values."""
        summary: dict[str, int | float] = dict(self._session_costs)
        per_step_totals: dict[str, int | float] = {}
        for step in self._recorder.all_steps():
            costs = step.get("costs")
            if not isinstance(costs, dict):
                continue
            for k, v in costs.items():
                if isinstance(v, (int, float)):
                    per_step_totals[k] = per_step_totals.get(k, 0) + v
        for k, v in per_step_totals.items():
            summary.setdefault(k, v)
        return summary

    def mark_for_eval(
        self,
        step_index: int,
        reason: str,
        *,
        candidate_cluster_id: str | None = None,
    ) -> None:
        """Tag a step as a regression-fixture candidate (#16).

        Idempotent on ``step_index`` — repeat calls overwrite the
        prior tag (last-write-wins). The tag lands in
        ``eval_candidates.json`` at the bundle root on close, and is
        POSTed live to the server's promotion endpoint when streaming
        is enabled. Operates on any step index — even one that
        hasn't been recorded yet — so producers can mark a step
        eagerly before its post-action result is known.
        """
        self._require_open()
        record = self._recorder.mark_for_eval(
            step_index=step_index,
            reason=reason,
            candidate_cluster_id=candidate_cluster_id,
            tagged_at=_utcnow_iso(),
        )
        if self._stream is not None:
            self._stream.post_eval_candidate(dict(record))

    def record_judge_decision(
        self,
        step_index: int,
        *,
        judge_id: str,
        judge_type: str,
        verdict: dict[str, Any],
        confidence: float | None = None,
        evidence_refs: list[str] | None = None,
        judged_at: str | None = None,
        promote: bool = True,
    ) -> None:
        """Record a judge decision against a step (#17).

        ``judge_type`` is one of ``rule``, ``model``, ``human``,
        ``hybrid``. Multiple judge decisions per step are kept as a
        sibling list to ``step.verdict``; their provenance is the value
        of this primitive.

        When ``promote`` is True (default), the supplied ``verdict``
        becomes the operative ``step.verdict`` and ``step.verdict_source``
        is set to ``"<judge_type>:<judge_id>"`` so consumers know which
        judge produced the operative verdict.

        Raises ``ValueError`` for unknown ``judge_type`` or when the
        step doesn't exist.
        """
        self._require_open()
        if judge_type not in ("rule", "model", "human", "hybrid"):
            raise ValueError(
                f"judge_type must be one of rule|model|human|hybrid, "
                f"got {judge_type!r}"
            )
        decision: dict[str, Any] = {
            "judge_id": judge_id,
            "judge_type": judge_type,
            "verdict": dict(verdict),
        }
        if confidence is not None:
            decision["confidence"] = max(0.0, min(1.0, float(confidence)))
        if evidence_refs is not None:
            decision["evidence_refs"] = list(evidence_refs)
        decision["judged_at"] = judged_at or _utcnow_iso()
        ok = self._recorder.append_judge_decision(
            step_index,
            decision=decision,
            promote_verdict=promote,
            verdict_source=f"{judge_type}:{judge_id}" if promote else None,
        )
        if not ok:
            raise ValueError(
                f"record_judge_decision: no step at step_index={step_index}. "
                f"Record the step first via record_step()."
            )
        if self._stream is not None:
            redacted_decision = self.redaction_policy.apply(dict(decision))
            if isinstance(redacted_decision, dict):
                self._stream.post_judge_decision(step_index, redacted_decision)
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def attach_env_fingerprint(
        self,
        step_index: int,
        *,
        url_host: str | None = None,
        url_path_template: str | None = None,
        viewport_hash: str | None = None,
        dom_hash: str | None = None,
        api_shapes: dict[str, str] | None = None,
        extensions: list[str] | None = None,
    ) -> None:
        """Attach a structural environment fingerprint to a step (#13).

        The visual half lives on the Observation
        (`observation.hashes.phash_64`); this is the structural half.
        Stored side-by-side, not merged. Lets the platform's
        determinism checker attribute drift to agent/model/env
        independently.

        SDK never derives ``dom_hash`` itself — only adapters that
        already probe DOM for diagnostics should populate it
        (preserves the screenshot-grounded core invariant).

        Merges into ``step.env_fingerprint``; unset arguments are
        preserved. Raises ``ValueError`` if no step exists.
        """
        self._require_open()
        patch: dict[str, Any] = {}
        for name, value in {
            "url_host": url_host,
            "url_path_template": url_path_template,
            "viewport_hash": viewport_hash,
            "dom_hash": dom_hash,
        }.items():
            if value is not None:
                patch[name] = value
        if api_shapes is not None:
            patch["api_shapes"] = dict(api_shapes)
        if extensions is not None:
            patch["extensions"] = list(extensions)
        if not patch:
            return
        ok = self._recorder.merge_step_env_fingerprint(
            step_index, fingerprint=patch
        )
        if not ok:
            raise ValueError(
                f"attach_env_fingerprint: no step at step_index={step_index}. "
                f"Record the step first via record_step()."
            )
        if self._stream is not None:
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def set_step_versions(
        self,
        step_index: int,
        *,
        model: str | None = None,
        prompt: str | None = None,
        prompt_hash: str | None = None,
        tool_descriptions_hash: str | None = None,
        code_git_sha: str | None = None,
        grounder: str | None = None,
        env_fingerprint_ref: str | None = None,
    ) -> None:
        """Stamp version axes on a previously-recorded step (#10).

        Merges into ``step.captured_versions``; unset arguments are
        preserved. Used by the platform's causal-attribution engine
        to disentangle which input changed when an outcome moves.
        Raises ``ValueError`` if no step exists at ``step_index``.
        """
        self._require_open()
        patch: dict[str, str] = {}
        for name, value in {
            "model": model,
            "prompt": prompt,
            "prompt_hash": prompt_hash,
            "tool_descriptions_hash": tool_descriptions_hash,
            "code_git_sha": code_git_sha,
            "grounder": grounder,
            "env_fingerprint_ref": env_fingerprint_ref,
        }.items():
            if value is not None:
                patch[name] = value
        if not patch:
            return
        ok = self._recorder.merge_step_captured_versions(
            step_index, versions=patch
        )
        if not ok:
            raise ValueError(
                f"set_step_versions: no step at step_index={step_index}. "
                f"Record the step first via record_step()."
            )
        if self._stream is not None:
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def record_modelio(
        self,
        record: dict[str, Any],
        *,
        step_index: int | None = None,
        layer: str | None = None,
        validate: bool = True,
    ) -> str:
        """Stage one model-call record (#56 producer side).

        Validates ``record`` against the vendored
        ``modelio.schema.json`` (Draft 2020-12) unless ``validate`` is
        False. Writes the record to
        ``modelio/<step_index:04d>-<layer>-<seq>.json`` on session
        close (or ``modelio/run-<layer>-<seq>.json`` when
        ``step_index`` is None). The session's redaction policy is
        applied before persistence.

        Idempotent on the record's ``prompt_hash`` (when set): a
        second call with the same hash returns the existing path
        without staging again. Returns the bundle-relative path of
        the persisted record.

        If ``layer`` is given and the record doesn't already carry
        one, it is stamped onto the record. If neither is set, the
        layer defaults to ``"model"`` for path construction.
        """
        self._require_open()
        rec = dict(record)
        if layer is not None and "layer" not in rec:
            rec["layer"] = layer
        # Default schema_version + ts for ergonomics — callers MAY
        # override either by setting them directly on the record.
        rec.setdefault("schema_version", SCHEMA_VERSION)
        rec.setdefault("ts", _utcnow_iso())
        if step_index is not None:
            rec.setdefault("step_index", step_index)

        # Idempotency: same prompt_hash → same path, no duplicate stage.
        prompt_hash = rec.get("prompt_hash")
        if isinstance(prompt_hash, str):
            existing = self._recorder.lookup_modelio_by_hash(prompt_hash)
            if existing is not None:
                return existing

        if validate:
            try:
                validator_for("modelio").validate(rec)
            except ValidationError as exc:
                raise ValueError(
                    f"record_modelio: payload does not match modelio.schema.json: {exc.message}"
                ) from exc

        # Redact before persistence — same path payloads take.
        redacted = self.redaction_policy.apply(rec)
        if isinstance(redacted, dict):
            redacted.setdefault("redaction_applied", True)
        path_layer = (
            redacted.get("layer") if isinstance(redacted, dict) else None
        ) or layer or "model"
        relpath = self._recorder.reserve_modelio_path(
            step_index=step_index, layer=str(path_layer)
        )
        staged = redacted if isinstance(redacted, dict) else rec
        self._recorder.stage_modelio(
            relpath,
            staged,
            prompt_hash=prompt_hash if isinstance(prompt_hash, str) else None,
        )
        if self._stream is not None:
            self._stream.post_modelio(relpath, dict(staged))
        # #10: auto-stamp captured_versions on the corresponding step
        # so the platform's causal-attribution engine can disentangle
        # which input changed when an outcome moves. Last-write-wins.
        if step_index is not None:
            self._autostamp_captured_versions(
                step_index=step_index, record=rec, prompt_hash=prompt_hash
            )
        return relpath

    def _autostamp_captured_versions(
        self,
        *,
        step_index: int,
        record: dict[str, Any],
        prompt_hash: str | None,
    ) -> None:
        """Pick out the version axes the modelio record happens to carry
        and merge them onto step.captured_versions. Silent no-op if the
        step hasn't been recorded yet — late callers can still use
        set_step_versions() explicitly."""
        if self._recorder.get_step(step_index) is None:
            return
        patch: dict[str, str] = {}
        request = record.get("request")
        if isinstance(request, dict):
            model = request.get("model")
            if isinstance(model, str):
                patch["model"] = model
        if isinstance(prompt_hash, str):
            patch["prompt_hash"] = prompt_hash
        if not patch:
            return
        self._recorder.merge_step_captured_versions(step_index, versions=patch)
        if self._stream is not None:
            patched = self._recorder.get_step(step_index)
            if patched is not None:
                self._stream.put_step(self.redaction_policy.apply(dict(patched)))

    def append_log(
        self,
        text: str,
        *,
        step_index: int | None = None,
        name: str = "run",
    ) -> None:
        """Append a log chunk to the server (#17).

        When streaming is enabled (``AUGUR_DSN`` set), POSTs to
        ``/api/v1/runs/<run_id>/logs``. When streaming is off, this
        is a no-op — local bundles don't have a server-side log
        store and producers that want local logs should write to the
        bundle's ``logs/`` directory directly via their store.

        ``step_index``, when set, routes the chunk to
        ``logs/step-<idx>.log`` instead of ``logs/<name>.log``.
        """
        self._require_open()
        if self._stream is None:
            return
        self._stream.post_logs(text=text, name=name, step_index=step_index)

    def add_tag(self, key: str, value: str) -> None:
        self._tags[key] = value

    def set_live_endpoints(
        self,
        *,
        status_url: str | None = None,
        video_url: str | None = None,
        reasoning_url: str | None = None,
    ) -> None:
        """Record live attach endpoints (spec §8 DebugSession.live).

        Even for static bundles, the `video_url` is useful as a reference to
        an externally-stored recording (e.g. `/v1/runs/{id}/video`).
        """
        live: dict[str, str] = {}
        if status_url is not None:
            live["status_url"] = status_url
        if video_url is not None:
            live["video_url"] = video_url
        if reasoning_url is not None:
            live["reasoning_url"] = reasoning_url
        self._live_endpoints = live

    # -- accessors --

    @property
    def manifest(self) -> BundleManifest | None:
        return self._manifest

    @property
    def branch_mode(self) -> str | None:
        """Resolved branching-replay mode (``replay`` or ``sandbox``)
        when constructed via :py:meth:`branch_from`; ``None`` for
        production runs."""
        return self._branch_mode

    @property
    def store(self) -> Store:
        return self._store

    @property
    def out_dir(self) -> Path:
        return self._out_dir

    # -- internals --

    @staticmethod
    def _validate_branch_context(ctx: dict[str, Any]) -> dict[str, Any]:
        """Sanity-check a BranchContext at construction time so producer
        bugs (missing axis, unknown axis) surface immediately rather
        than at bundle write."""
        required = ("parent_run_id", "branch_point_step_index", "mutated_axis")
        for field in required:
            if field not in ctx:
                raise ValueError(
                    f"BranchContext missing required field: {field!r}"
                )
        allowed = {"model", "prompt", "action", "grounder", "tool_description"}
        if ctx["mutated_axis"] not in allowed:
            raise ValueError(
                f"BranchContext.mutated_axis must be one of {sorted(allowed)}, "
                f"got {ctx['mutated_axis']!r}"
            )
        return dict(ctx)

    def _require_open(self) -> None:
        if not self._open:
            raise RuntimeError("DebugSession is closed; create a new one to record more")

    def _step_branch_context(self) -> dict[str, Any]:
        """The slice of branch_context that lands on each step — the
        mutation payload stays at session level only."""
        if self._branch_context is None:
            return {}
        ctx = self._branch_context
        out: dict[str, Any] = {
            "parent_run_id": ctx["parent_run_id"],
            "branch_point_step_index": ctx["branch_point_step_index"],
            "mutated_axis": ctx["mutated_axis"],
        }
        if "branch_id" in ctx:
            out["branch_id"] = ctx["branch_id"]
        return out

    def _session_record(self) -> SessionRecord:
        client: dict[str, Any] = {"name": self._client_name}
        if self._client_version is not None:
            client["version"] = self._client_version
        if self._client_git_sha is not None:
            client["git_sha"] = self._client_git_sha
        record: SessionRecord = {
            "schema_version": SCHEMA_VERSION,
            "debug_session_id": self.debug_session_id,
            "run_id": self.run_id,
            "client": client,  # type: ignore[typeddict-item]
            "capture_mode": self.capture_mode.value,
            "started_at": self._started_at,
            "ended_at": self._ended_at,
            "status": self._status,  # type: ignore[typeddict-item]
            "artifact_root": self._store.root_uri,
            "trace_uri": self._store.signed_url("trace.json"),
        }
        if self._tags:
            record["tags"] = dict(self._tags)
        if self._live_endpoints:
            record["live"] = dict(self._live_endpoints)  # type: ignore[typeddict-item]
        if self._session_costs:
            record["costs"] = dict(self._session_costs)  # type: ignore[typeddict-unknown-key]
        if self._branch_context is not None:
            record["branch_context"] = dict(self._branch_context)  # type: ignore[typeddict-item]
        return record


__all__ = ["DebugSession"]
