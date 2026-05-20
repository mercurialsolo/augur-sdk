"""DebugSession.set_score (0.1.8) — issue #3.

Adds a continuous reward signal (0..1) to an already-recorded step
without disturbing the categorical verdict.status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


def _minimal_step(idx: int, *, verdict: dict[str, Any] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {
        "step_id": f"run_t/step/{idx:04d}",
        "step_index": idx,
        "intent": f"step {idx}",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-20T00:00:00Z",
        "ended_at": "2026-05-20T00:00:01Z",
        "duration_ms": 1000,
        "action": {
            "type": "click",
            "params": {"x": 10, "y": 20},
            "coordinate_space": "viewport_css_px",
            "dispatch_backend": "cdp",
        },
        "grounding": {
            "provider": "test",
            "target_label": "x",
            "coordinates": {"x": 10, "y": 20},
            "confidence": 0.9,
            "evidence": "test",
            "provenance": "screenshot",
        },
    }
    if verdict is not None:
        s["verdict"] = verdict
    return s


def _written_step(out: Path, idx: int) -> dict[str, Any]:
    return json.loads((out / "steps" / f"{idx:04d}.json").read_text())


def test_set_score_attaches_to_existing_verdict(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0, verdict={"status": "passed", "reason": "ok"}))
        s.set_score(0, 0.73, comparator="verifier")

    v = _written_step(out, 0)["verdict"]
    assert v["status"] == "passed"
    assert v["reason"] == "ok"
    assert v["score"] == pytest.approx(0.73)
    assert v["comparator"] == "verifier"
    assert validate_bundle(out) == []


def test_set_score_synthesizes_unknown_verdict_when_step_has_none(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))  # no verdict
        s.set_score(0, 0.5)

    v = _written_step(out, 0)["verdict"]
    assert v["status"] == "unknown"
    assert v["score"] == pytest.approx(0.5)


def test_set_score_clamps_to_unit_interval(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        s.record_step(_minimal_step(1))
        s.set_score(0, -0.5)
        s.set_score(1, 1.5)

    assert _written_step(out, 0)["verdict"]["score"] == 0.0
    assert _written_step(out, 1)["verdict"]["score"] == 1.0


def test_set_score_records_components(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        s.set_score(
            0,
            0.8,
            comparator="model-judge",
            components={"grounding_accuracy": 0.9, "state_change_observed": 0.7},
        )

    v = _written_step(out, 0)["verdict"]
    assert v["score_components"] == {
        "grounding_accuracy": 0.9,
        "state_change_observed": 0.7,
    }


def test_set_score_rejects_unknown_comparator(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        with pytest.raises(ValueError, match="comparator must be one of"):
            s.set_score(0, 0.5, comparator="rubric_v1")


def test_set_score_raises_for_unknown_step_index(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        with pytest.raises(ValueError, match="no step at step_index=7"):
            s.set_score(7, 0.5)
