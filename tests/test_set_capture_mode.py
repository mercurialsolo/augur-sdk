"""DebugSession.set_capture_mode mid-run override (#36)."""

from __future__ import annotations

import json

from augur_sdk import CaptureMode, DebugSession


def _step(idx: int, *, mode: str | None = None) -> dict:
    step: dict = {
        "step_id": f"run_test/step/{idx:04d}",
        "step_index": idx,
        "intent": "test",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-19T00:00:00Z",
        "ended_at": "2026-05-19T00:00:01Z",
        "action": {
            "type": "click",
            "params": {"x": 1, "y": 1},
            "coordinate_space": "viewport_css_px",
            "dispatch_backend": "playwright",
        },
        "grounding": {"provider": "test", "provenance": "screenshot"},
        "verdict": {"status": "passed"},
    }
    if mode is not None:
        step["capture_mode"] = mode
    return step


def test_unset_capture_mode_does_not_stamp(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as session:
        session.record_step(_step(0))

    step_doc = json.loads((out / "steps" / "0000.json").read_text())
    assert "capture_mode" not in step_doc, "no override => no per-step field"


def test_set_capture_mode_stamps_subsequent_steps(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as session:
        session.record_step(_step(0))
        session.set_capture_mode("screenshots")
        session.record_step(_step(1))
        session.record_step(_step(2))

    s0 = json.loads((out / "steps" / "0000.json").read_text())
    s1 = json.loads((out / "steps" / "0001.json").read_text())
    s2 = json.loads((out / "steps" / "0002.json").read_text())
    assert "capture_mode" not in s0
    assert s1["capture_mode"] == "screenshots"
    assert s2["capture_mode"] == "screenshots", "override persists across steps"


def test_set_capture_mode_accepts_enum_or_string(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as session:
        session.set_capture_mode(CaptureMode.FULL)
        session.record_step(_step(0))

    s0 = json.loads((out / "steps" / "0000.json").read_text())
    assert s0["capture_mode"] == "full"


def test_explicit_step_capture_mode_wins_over_override(tmp_path) -> None:
    """If the caller already set capture_mode on the StepTrace, don't clobber it."""
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as session:
        session.set_capture_mode("screenshots")
        session.record_step(_step(0, mode="trace"))

    s0 = json.loads((out / "steps" / "0000.json").read_text())
    assert s0["capture_mode"] == "trace", "caller-set value must not be overwritten"
