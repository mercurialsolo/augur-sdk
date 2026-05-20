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
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from augur_sdk._schema import SCHEMA_VERSION
from augur_sdk.bundle import write_bundle
from augur_sdk.capture import CaptureMode, resolve_capture_mode
from augur_sdk.models import BundleManifest, DecisionEvent, StepTrace
from augur_sdk.models import DebugSession as SessionRecord
from augur_sdk.recorder import EventRecorder
from augur_sdk.redaction import DefaultRedactionPolicy, RedactionPolicy
from augur_sdk.storage import LocalFSStore, Store
from augur_sdk.streaming import DSN, StreamingSink


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
        # Optional streaming sink (Sentry-style). DSN arg wins; otherwise
        # consult AUGUR_DSN env var. None disables streaming.
        parsed_dsn = DSN.from_env(dsn)
        self._stream: StreamingSink | None = (
            StreamingSink(parsed_dsn, client_name=client_name, client_version=client_version)
            if parsed_dsn
            else None
        )

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
        self._recorder.record_step(step)
        if self._stream is not None:
            redacted = self.redaction_policy.apply(dict(step))
            self._stream.put_step(redacted)

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
        # Echo through the streaming sink so live viewers see the
        # patched verdict without waiting for close().
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
    def store(self) -> Store:
        return self._store

    @property
    def out_dir(self) -> Path:
        return self._out_dir

    # -- internals --

    def _require_open(self) -> None:
        if not self._open:
            raise RuntimeError("DebugSession is closed; create a new one to record more")

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
        return record


__all__ = ["DebugSession"]
