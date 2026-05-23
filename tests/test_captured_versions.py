"""CapturedVersions on StepTrace (#10).

Promotes the version-axes block from `ReplayFixture` to a first-class
StepTrace field so the platform's causal-attribution engine can
disentangle which input changed when an outcome moves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from augur_schema import validator_for

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


def _step(idx: int = 0) -> dict[str, Any]:
    return {
        "step_id": f"run/step/{idx:04d}",
        "step_index": idx,
        "intent": "click login",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-19T00:00:00Z",
    }


def _modelio() -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "layer": "planner",
        "ts": "2026-05-20T00:00:00Z",
        "prompt_hash": "abc123",
        "request": {
            "model": "claude-sonnet-4-7-20260120",
            "messages": [{"role": "user", "content": "go"}],
        },
        "response": {
            "text": "ok",
            "stop_reason": "end_turn",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    }


def test_set_step_versions_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.set_step_versions(
            0,
            model="claude-opus-4-6",
            prompt_hash="deadbeef",
            tool_descriptions_hash="cafe1234",
            grounder="osatlas",
            code_git_sha="abc1234",
        )

    step = json.loads((out / "steps" / "0000.json").read_text())
    cv = step["captured_versions"]
    assert cv["model"] == "claude-opus-4-6"
    assert cv["prompt_hash"] == "deadbeef"
    assert cv["tool_descriptions_hash"] == "cafe1234"
    assert cv["grounder"] == "osatlas"
    assert cv["code_git_sha"] == "abc1234"

    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_record_modelio_auto_stamps_step(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.record_modelio(_modelio(), step_index=0)

    step = json.loads((out / "steps" / "0000.json").read_text())
    cv = step["captured_versions"]
    assert cv["model"] == "claude-sonnet-4-7-20260120"
    assert cv["prompt_hash"] == "abc123"


def test_set_step_versions_merges_with_modelio_autostamp(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.record_modelio(_modelio(), step_index=0)  # stamps model + prompt_hash
        s.set_step_versions(0, grounder="omniparser")

    step = json.loads((out / "steps" / "0000.json").read_text())
    cv = step["captured_versions"]
    # autostamped fields survive merge
    assert cv["model"] == "claude-sonnet-4-7-20260120"
    assert cv["prompt_hash"] == "abc123"
    # explicit field added
    assert cv["grounder"] == "omniparser"


def test_set_step_versions_partial_no_step_raises(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s, pytest.raises(ValueError, match="no step at step_index"):
        s.set_step_versions(7, model="claude-sonnet")


def test_set_step_versions_noop_when_all_none(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.set_step_versions(0)  # no-op
        # Field is absent when nothing was set.
        rec = s._recorder.get_step(0)
        assert rec is not None
        assert "captured_versions" not in rec


def test_modelio_autostamp_silent_when_no_step_recorded(tmp_path: Path) -> None:
    """Auto-stamp tolerates record_modelio() before record_step()."""
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        # No step recorded yet — this used to be valid, must not raise.
        s.record_modelio(_modelio(), step_index=0)
        s.record_step(_step(0))

    step = json.loads((out / "steps" / "0000.json").read_text())
    # Step has no captured_versions because the auto-stamp ran before
    # the step existed; callers who want late stamping use
    # set_step_versions() explicitly.
    assert "captured_versions" not in step


def test_step_with_captured_versions_validates(tmp_path: Path) -> None:
    """A StepTrace with captured_versions must validate."""
    step = _step(0)
    step["captured_versions"] = {
        "model": "claude",
        "prompt_hash": "deadbeef",
        "grounder": "osatlas",
    }
    validator_for("step_trace").validate(step)
