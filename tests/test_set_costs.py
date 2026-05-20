"""DebugSession.set_costs + set_step_costs (0.1.8) — issue #1.

Structured cost emission for both run-level rollups and per-step
breakdowns. Validates against the vendored schemas on close.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


def _minimal_step(idx: int) -> dict[str, Any]:
    return {
        "step_id": f"run_c/step/{idx:04d}",
        "step_index": idx,
        "intent": f"step {idx}",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-20T00:00:00Z",
        "ended_at": "2026-05-20T00:00:01Z",
        "duration_ms": 1000,
    }


def test_set_costs_lands_on_session_record_and_manifest(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.set_costs(
            total_usd=0.42,
            model_usd=0.32,
            gpu_usd=0.10,
            tokens_in=1500,
            tokens_out=400,
            cache_hit_tokens=200,
        )

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["costs"] == {
        "total_usd": 0.42,
        "model_usd": 0.32,
        "gpu_usd": 0.10,
        "tokens_in": 1500,
        "tokens_out": 400,
        "cache_hit_tokens": 200,
    }
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["costs"] == trace["session"]["costs"]
    assert validate_bundle(out) == []


def test_set_costs_merges_across_calls(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.set_costs(model_usd=0.20, tokens_in=500)
        s.set_costs(total_usd=0.30, tokens_out=200)  # extends prior call

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["costs"] == {
        "model_usd": 0.20,
        "total_usd": 0.30,
        "tokens_in": 500,
        "tokens_out": 200,
    }


def test_set_costs_no_call_means_no_costs_field(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ):
        pass

    manifest = json.loads((out / "manifest.json").read_text())
    assert "costs" not in manifest
    trace = json.loads((out / "trace.json").read_text())
    assert "costs" not in trace["session"]


def test_set_step_costs_patches_recorded_step(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        s.set_step_costs(
            0,
            total_usd=0.05,
            model_usd=0.04,
            tokens_in=300,
            tokens_out=80,
        )

    written: dict[str, Any] = json.loads((out / "steps" / "0000.json").read_text())
    assert written["costs"] == {
        "total_usd": 0.05,
        "model_usd": 0.04,
        "tokens_in": 300,
        "tokens_out": 80,
    }


def test_set_step_costs_merges_across_calls(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        s.set_step_costs(0, tokens_in=100)
        s.set_step_costs(0, tokens_out=50)

    written: dict[str, Any] = json.loads((out / "steps" / "0000.json").read_text())
    assert written["costs"] == {"tokens_in": 100, "tokens_out": 50}


def test_set_step_costs_no_args_is_noop(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_minimal_step(0))
        s.set_step_costs(0)  # no kwargs — no-op

    written: dict[str, Any] = json.loads((out / "steps" / "0000.json").read_text())
    assert "costs" not in written


def test_set_step_costs_raises_for_unknown_step(tmp_path) -> None:
    out = tmp_path / "bundle"
    with (
        DebugSession(
            run_id="run_c",
            client_name="testclient",
            capture_mode=CaptureMode.METADATA,
            out_dir=out,
        ) as s,
        pytest.raises(ValueError, match="no step at step_index=0"),
    ):
        s.set_step_costs(0, total_usd=0.1)
