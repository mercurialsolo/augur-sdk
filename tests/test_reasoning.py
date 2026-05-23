"""record_reasoning() — first-class reasoning-token capture (#14)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.model_api_adapter import ModelApiAdapterBase
from augur_sdk.redaction import DefaultRedactionPolicy


def _step(idx: int = 0) -> dict[str, Any]:
    return {
        "step_id": f"r/step/{idx:04d}",
        "step_index": idx,
        "intent": "click",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-19T00:00:00Z",
    }


def test_record_reasoning_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.record_reasoning(
            0,
            "I should click the Login button because…",
            tokens=42,
            format="claude_extended_thinking",
            model="claude-opus-4-7",
        )
        s.record_reasoning(0, "second pass", format="openai_reasoning_summary")

    f = out / "events" / "reasoning.jsonl"
    assert f.exists()
    lines = f.read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["step_index"] == 0
    assert first["text"].startswith("I should click")
    assert first["tokens"] == 42
    assert first["format"] == "claude_extended_thinking"
    assert first["model"] == "claude-opus-4-7"
    second = json.loads(lines[1])
    assert second["format"] == "openai_reasoning_summary"


def test_record_reasoning_unknown_format_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="format must be one of"):
        s.record_reasoning(0, "x", format="not-real")


def test_reasoning_redactor_is_applied(tmp_path: Path) -> None:
    out = tmp_path / "b"
    policy = DefaultRedactionPolicy()
    policy.add_reasoning_redactor(lambda s: s.replace("Acme Co", "***COMPANY***"))
    with DebugSession(
        run_id="r",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        redaction_policy=policy,
    ) as s:
        s.record_reasoning(None, "Should I click for Acme Co?")

    line = (out / "events" / "reasoning.jsonl").read_text().strip()
    trace = json.loads(line)
    assert trace["text"] == "Should I click for ***COMPANY***?"


def test_streaming_post_reasoning_called(tmp_path: Path) -> None:
    out = tmp_path / "b"
    calls: list[dict[str, Any]] = []

    class FakeSink:
        def begin(self, *, run_id: str, capture_mode: str) -> None: ...
        def end(self) -> None: ...
        def post_manifest(self, m: dict[str, Any]) -> None: ...
        def put_trace(self, t: dict[str, Any]) -> None: ...
        def put_step(self, s: Any) -> None: ...
        def post_events(self, evs: list[Any], *, step_index: int | None) -> None: ...
        def post_screenshot(self, *a: Any, **k: Any) -> None: ...
        def post_logs(self, *a: Any, **k: Any) -> None: ...

        def post_reasoning(self, trace: dict[str, Any]) -> None:
            calls.append(trace)

    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s._stream = FakeSink()  # type: ignore[assignment]
        s.record_reasoning(0, "think")

    assert len(calls) == 1
    assert calls[0]["text"] == "think"


def test_extract_reasoning_from_claude_extended_thinking() -> None:
    response = {
        "content": [
            {"type": "thinking", "text": "step 1: identify login"},
            {"type": "text", "text": "Clicking Login."},
            {"type": "tool_use", "name": "click", "input": {"x": 10, "y": 20}},
        ]
    }
    out = ModelApiAdapterBase.extract_reasoning_from_response(response)
    assert len(out) == 1
    assert out[0]["text"] == "step 1: identify login"
    assert out[0]["format"] == "claude_extended_thinking"


def test_extract_reasoning_from_openai_summary() -> None:
    response = {
        "reasoning": {"summary": "I will start by reading the page"},
        "output": [],
    }
    out = ModelApiAdapterBase.extract_reasoning_from_response(response)
    assert len(out) == 1
    assert out[0]["text"] == "I will start by reading the page"
    assert out[0]["format"] == "openai_reasoning_summary"


def test_extract_reasoning_returns_empty_when_unknown_shape() -> None:
    response = {"foo": "bar"}
    assert ModelApiAdapterBase.extract_reasoning_from_response(response) == []
