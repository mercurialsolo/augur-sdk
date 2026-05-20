"""ModelApiAdapterBase — shared scaffolding for message-log based CUAs.

OpenAI's Responses API + Anthropic's Messages API with tool_use share
~80% of the adapter pattern: walk a message log, find tool calls,
emit one Augur StepTrace per tool call, attach sidecar screenshots.
The remaining ~20% is provider-specific (the shape of `tool_calls`,
how cache hits are reported, what "stop_reason" means).

This base abstracts the common 80%. Concrete adapters in
``augur-adapter-openai-cua`` and ``augur-adapter-anthropic-cua``
subclass it and implement two methods.

Closes #53. See ``docs/adapter-feasibility.md`` (#41) for why this
matters.

Usage from a concrete adapter::

    class OpenAICuaAdapter(ModelApiAdapterBase):
        name = "openai-cua"

        def iter_tool_calls(self, messages):
            # OpenAI-shaped: tool_calls live on assistant messages.
            for turn_idx, msg in enumerate(messages):
                if msg.get("role") != "assistant":
                    continue
                for tc_idx, tc in enumerate(msg.get("tool_calls", [])):
                    if tc.get("type") != "computer_use_preview":
                        continue
                    action = self._action_from_openai_tc(tc)
                    yield (turn_idx, tc_idx, action)

        def _action_from_openai_tc(self, tc):
            params = tc["function"]["arguments"]
            return {
                "type": params["action"],
                "params": {"x": params.get("x"), "y": params.get("y"), ...},
                "coordinate_space": "viewport_css_px",
                "dispatch_backend": "openai-computer-use-preview",
            }

    OpenAICuaAdapter.bundle_from_input(input_dir, output_dir)
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from augur_sdk.capture import CaptureMode
from augur_sdk.models import Action, StepTrace
from augur_sdk.session import DebugSession


class ModelApiAdapterBase:
    """Base for adapters that consume a message log + sidecar
    screenshots (OpenAI Responses, Anthropic Messages, similar).

    Subclasses implement two methods:

    - :py:meth:`iter_tool_calls`: yield one ``(turn_idx, tool_call_idx,
      action_dict)`` per tool call. ``action_dict`` MUST match the
      canonical Augur action shape (``type``, ``params``,
      ``coordinate_space``, ``dispatch_backend``).
    - :py:meth:`load_messages`: read the native input file(s) into a
      message-log list. Default reads a JSON file with shape
      ``{"messages": [...], "metadata": {...}}``; override for
      provider-specific layouts.

    The base provides :py:meth:`bundle_from_input` (the entry-point
    method the augur.adapters group looks for) implemented in terms
    of those two.
    """

    # Subclasses MUST set:
    name: str = ""
    SUPPORTED_SCHEMA_RANGE: tuple[str, str] = ("0.1", "0.1")

    # Sidecar screenshot layout. Override per provider if your
    # native trace uses a different convention.
    screenshot_filename_template: str = "{step_index:04d}_{kind}.png"

    @abstractmethod
    def iter_tool_calls(
        self, messages: list[dict[str, Any]]
    ) -> Iterator[tuple[int, int, dict[str, Any]]]:
        """Walk the message log; yield (turn_idx, tool_call_idx,
        action) per tool call. Order MUST be the dispatch order."""
        raise NotImplementedError

    def load_messages(self, input_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Read native input into ``(messages, metadata)``.

        Default reads a single JSON file with ``{"messages": [...],
        "metadata": {...}}``. Override for vendor-specific layouts
        (e.g., conversation .jsonl, separate metadata file)."""
        data = json.loads(input_path.read_text(encoding="utf-8"))
        return data.get("messages", []), data.get("metadata", {})

    def find_screenshot(
        self, screens_dir: Path, step_index: int, kind: str
    ) -> Path | None:
        """Resolve the sidecar screenshot path for a step's
        pre/post observation. Default uses
        ``<screens_dir>/<step_index:04d>_<kind>.png``."""
        candidate = screens_dir / self.screenshot_filename_template.format(
            step_index=step_index, kind=kind
        )
        return candidate if candidate.exists() else None

    def grounding_provider(self) -> str:
        """Return the canonical grounding provider name for this
        adapter. Used to stamp grounding.provider on each step.
        Override per provider (e.g. ``"openai.computer_use_preview"``,
        ``"anthropic.computer_20241022"``)."""
        return self.name or "model-api"

    def bundle_from_input(
        self,
        input_path: Path | str,
        output_dir: Path | str,
        *,
        screens_dir: Path | str | None = None,
        run_id: str | None = None,
    ) -> Path:
        """Convert one message-log input into an Augur bundle.

        ``screens_dir`` defaults to ``<input_path.parent>/screens/``
        when ``input_path`` is a file, or ``<input_path>/screens/``
        when it's a directory. Override per adapter when your native
        layout differs."""
        input_path = Path(input_path)
        output_dir = Path(output_dir)
        if input_path.is_dir():
            candidates = sorted(input_path.glob("*.json"))
            if not candidates:
                raise FileNotFoundError(
                    f"{self.name}: no .json found under {input_path}"
                )
            messages_file = candidates[0]
        else:
            messages_file = input_path
        screens_dir = (
            messages_file.parent / "screens"
            if screens_dir is None
            else Path(screens_dir)
        )

        messages, metadata = self.load_messages(messages_file)
        resolved_run_id = (
            run_id
            or metadata.get("run_id")
            or metadata.get("session_id")
            or messages_file.stem
        )

        with DebugSession(
            run_id=resolved_run_id,
            client_name=self.name,
            client_version=metadata.get("client_version", "0.1.0"),
            capture_mode=CaptureMode.FULL,
            out_dir=output_dir,
            tags={"adapter": self.name, **(metadata.get("tags") or {})},
            started_at=metadata.get("started_at"),
        ) as session:
            for step_index, (turn_idx, _tc_idx, action) in enumerate(
                self.iter_tool_calls(messages)
            ):
                pre_path = self.find_screenshot(screens_dir, step_index, "pre")
                post_path = self.find_screenshot(screens_dir, step_index, "post")
                pre_ref = (
                    session.attach_observation(
                        step_index=step_index,
                        kind="pre",
                        png_bytes=pre_path.read_bytes(),
                    )
                    if pre_path
                    else None
                )
                post_ref = (
                    session.attach_observation(
                        step_index=step_index,
                        kind="post",
                        png_bytes=post_path.read_bytes(),
                    )
                    if post_path
                    else None
                )
                step: StepTrace = {
                    "step_id": f"{resolved_run_id}/step/{step_index:04d}",
                    "step_index": step_index,
                    "step_type": str(action.get("type", "noop")),
                    "intent": self._intent_from_turn(messages, turn_idx),
                    "required": True,
                    "status": "succeeded",  # producers without verifier signal use attach_verifier later
                    "started_at": metadata.get("started_at", ""),
                    "observation_pre": pre_ref,
                    "observation_post": post_ref,
                    "action": cast(Action, action),
                    "grounding": {
                        "provider": self.grounding_provider(),
                        "provenance": "screenshot",
                    },
                    "verdict": {"status": "unknown", "reason": "no native verifier"},
                }
                session.record_step(step)

        return output_dir

    def _intent_from_turn(
        self, messages: list[dict[str, Any]], turn_idx: int
    ) -> str:
        """Derive a one-line intent from the latest assistant text
        before the tool call. Many model-API turns have no text;
        fall back to step_type. Override if your vendor structures
        intent differently."""
        if turn_idx < 0 or turn_idx >= len(messages):
            return ""
        msg = messages[turn_idx]
        content = msg.get("content")
        if isinstance(content, str):
            return content[:120]
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return str(block.get("text", ""))[:120]
        return ""


__all__ = ["ModelApiAdapterBase"]
