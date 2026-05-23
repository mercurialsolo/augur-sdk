"""record_judge_decision() — model/HITL judges as first-class (#17)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


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


def test_multiple_decisions_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.record_judge_decision(
            0,
            judge_id="exact",
            judge_type="rule",
            verdict={"status": "passed"},
            promote=False,
        )
        s.record_judge_decision(
            0,
            judge_id="opus",
            judge_type="model",
            verdict={"status": "failed", "reason": "wrong page"},
            confidence=0.8,
            promote=True,
        )
        s.record_judge_decision(
            0,
            judge_id="reviewer42",
            judge_type="human",
            verdict={"status": "passed", "reason": "false alarm"},
            promote=True,
        )

    step = json.loads((out / "steps" / "0000.json").read_text())
    decisions = step["judge_decisions"]
    assert len(decisions) == 3
    # operative verdict comes from the last-promoted (human)
    assert step["verdict"]["status"] == "passed"
    assert step["verdict_source"] == "human:reviewer42"
    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_promote_false_keeps_existing_verdict(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        step = _step(0)
        step["verdict"] = {"status": "passed", "reason": "native"}
        s.record_step(step)
        s.record_judge_decision(
            0,
            judge_id="opus",
            judge_type="model",
            verdict={"status": "failed", "reason": "looks wrong"},
            promote=False,
        )

    step = json.loads((out / "steps" / "0000.json").read_text())
    # Operative verdict unchanged
    assert step["verdict"]["status"] == "passed"
    assert step["judge_decisions"][0]["verdict"]["status"] == "failed"
    assert "verdict_source" not in step


def test_unknown_judge_type_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        with pytest.raises(ValueError, match="judge_type must be"):
            s.record_judge_decision(
                0, judge_id="x", judge_type="oracle", verdict={"status": "passed"}
            )


def test_no_step_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="no step at step_index"):
        s.record_judge_decision(
            7, judge_id="x", judge_type="model", verdict={"status": "passed"}
        )


def test_attach_verifier_emits_rule_judge_decision(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.attach_verifier(0, status="failed", check="screenshot_diff", expected="x", actual="y")

    step = json.loads((out / "steps" / "0000.json").read_text())
    assert step["verdict"]["status"] == "failed"
    assert len(step["judge_decisions"]) == 1
    decision = step["judge_decisions"][0]
    assert decision["judge_type"] == "rule"
    assert decision["judge_id"] == "screenshot_diff"


def test_streaming_post_judge_decision_called(tmp_path: Path) -> None:
    """When a sink is attached, record_judge_decision fires post_judge_decision()."""
    out = tmp_path / "b"
    calls: list[tuple[int, dict[str, Any]]] = []

    class FakeSink:
        def begin(self, *, run_id: str, capture_mode: str) -> None: ...
        def end(self) -> None: ...
        def post_manifest(self, m: dict[str, Any]) -> None: ...
        def put_trace(self, t: dict[str, Any]) -> None: ...
        def put_step(self, s: Any) -> None: ...
        def post_events(self, evs: list[Any], *, step_index: int | None) -> None: ...
        def post_screenshot(self, *args: Any, **kwargs: Any) -> None: ...
        def post_logs(self, *args: Any, **kwargs: Any) -> None: ...

        def post_judge_decision(
            self, step_index: int, decision: dict[str, Any]
        ) -> None:
            calls.append((step_index, decision))

    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s._stream = FakeSink()  # type: ignore[assignment]
        s.record_step(_step(0))
        s.record_judge_decision(
            0, judge_id="opus", judge_type="model", verdict={"status": "passed"}
        )

    assert len(calls) == 1
    posted_index, posted_decision = calls[0]
    assert posted_index == 0
    assert posted_decision["judge_id"] == "opus"
    assert posted_decision["judge_type"] == "model"
