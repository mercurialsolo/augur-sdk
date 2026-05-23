"""BranchContext labelling (#15)."""

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


def test_branch_context_on_session_and_step(tmp_path: Path) -> None:
    out = tmp_path / "b"
    ctx = {
        "parent_run_id": "run_parent",
        "branch_point_step_index": 3,
        "mutated_axis": "model",
        "mutation": {"model": "claude-opus-4-7"},
        "branch_id": "branch_xyz",
    }
    with DebugSession(
        run_id="run_branch",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        branch_context=ctx,
    ) as s:
        s.record_step(_step(0))

    trace = json.loads((out / "trace.json").read_text())
    # Session-level: full BranchContext including mutation payload
    sess_ctx = trace["session"]["branch_context"]
    assert sess_ctx["parent_run_id"] == "run_parent"
    assert sess_ctx["mutation"] == {"model": "claude-opus-4-7"}

    # Step-level: lightweight slice without the mutation payload
    step_ctx = trace["steps"][0]["branch_context"]
    assert step_ctx["parent_run_id"] == "run_parent"
    assert step_ctx["branch_point_step_index"] == 3
    assert step_ctx["mutated_axis"] == "model"
    assert step_ctx["branch_id"] == "branch_xyz"
    assert "mutation" not in step_ctx

    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_production_run_omits_branch_context(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_prod",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))

    trace = json.loads((out / "trace.json").read_text())
    assert "branch_context" not in trace["session"]
    assert "branch_context" not in trace["steps"][0]


def test_branch_context_missing_field_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    bad = {"parent_run_id": "x", "mutated_axis": "model"}
    with pytest.raises(ValueError, match="missing required field"):
        DebugSession(
            run_id="r",
            client_name="t",
            capture_mode=CaptureMode.METADATA,
            out_dir=out,
            branch_context=bad,
        )


def test_branch_context_unknown_axis_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    bad = {
        "parent_run_id": "x",
        "branch_point_step_index": 0,
        "mutated_axis": "temperature",
    }
    with pytest.raises(ValueError, match="mutated_axis must be one of"):
        DebugSession(
            run_id="r",
            client_name="t",
            capture_mode=CaptureMode.METADATA,
            out_dir=out,
            branch_context=bad,
        )


def test_explicit_step_branch_context_wins(tmp_path: Path) -> None:
    """A producer-supplied branch_context on a step is not overwritten."""
    out = tmp_path / "b"
    ctx = {
        "parent_run_id": "run_parent",
        "branch_point_step_index": 3,
        "mutated_axis": "model",
    }
    with DebugSession(
        run_id="r",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        branch_context=ctx,
    ) as s:
        step = _step(0)
        step["branch_context"] = {
            "parent_run_id": "other",
            "branch_point_step_index": 0,
            "mutated_axis": "prompt",
        }
        s.record_step(step)

    trace = json.loads((out / "trace.json").read_text())
    assert trace["steps"][0]["branch_context"]["parent_run_id"] == "other"
