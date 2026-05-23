"""Trajectory fingerprint at session close (#19)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.fingerprint import (
    compute_trajectory_fingerprint,
    cua_v1,
    resolve_algorithm,
)


def _step(idx: int, action: str, target: str, verdict: str = "passed") -> dict[str, Any]:
    return {
        "step_id": f"r/step/{idx:04d}",
        "step_index": idx,
        "intent": f"{action} {target}",
        "step_type": action,
        "required": True,
        "status": "succeeded" if verdict == "passed" else "failed",
        "started_at": "2026-05-19T00:00:00Z",
        "action": {"type": action},
        "grounding": {"provider": "test", "target_label": target, "provenance": "screenshot"},
        "verdict": {"status": verdict},
    }


def _run_with_steps(
    out_dir: Path, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    with DebugSession(
        run_id="run_fp",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out_dir,
    ) as s:
        for step in steps:
            s.record_step(step)
    return json.loads((out_dir / "manifest.json").read_text())


def test_manifest_carries_trajectory_fingerprint(tmp_path: Path) -> None:
    manifest = _run_with_steps(
        tmp_path / "b",
        [
            _step(0, "click", "Login button"),
            _step(1, "type", "email"),
        ],
    )
    assert "trajectory_fingerprint" in manifest
    assert manifest["trajectory_fingerprint"].startswith("cua_v1:")


def test_identical_trajectories_produce_identical_fingerprints(tmp_path: Path) -> None:
    steps_a = [_step(0, "click", "Login"), _step(1, "type", "email")]
    steps_b = [_step(0, "click", "Login"), _step(1, "type", "email")]
    m_a = _run_with_steps(tmp_path / "a", steps_a)
    m_b = _run_with_steps(tmp_path / "b", steps_b)
    assert m_a["trajectory_fingerprint"] == m_b["trajectory_fingerprint"]


def test_one_differing_action_changes_fingerprint(tmp_path: Path) -> None:
    base = [_step(0, "click", "Login"), _step(1, "type", "email")]
    diff = [_step(0, "click", "Login"), _step(1, "scroll", "page")]
    m_a = _run_with_steps(tmp_path / "a", base)
    m_b = _run_with_steps(tmp_path / "b", diff)
    assert m_a["trajectory_fingerprint"] != m_b["trajectory_fingerprint"]


def test_target_label_normalization_collapses_trivial_diff() -> None:
    a = [_step(0, "click", "Login Button"), _step(1, "type", "email")]
    b = [_step(0, "click", "login-button"), _step(1, "type", "email")]
    assert cua_v1(a) == cua_v1(b)


def test_empty_trajectory_no_fingerprint(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_empty",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as _s:
        pass
    manifest = json.loads((out / "manifest.json").read_text())
    assert "trajectory_fingerprint" not in manifest


def test_resolve_default_algorithm() -> None:
    fn = resolve_algorithm()
    assert fn is cua_v1


def test_resolve_unknown_algorithm_raises() -> None:
    with pytest.raises(ValueError, match="unknown trajectory_fingerprint"):
        resolve_algorithm("not-real-v999")


def test_step_order_matters() -> None:
    a = [_step(0, "click", "x"), _step(1, "type", "y")]
    b = [_step(0, "type", "y"), _step(1, "click", "x")]
    assert cua_v1(a) != cua_v1(b)


def test_fingerprint_is_deterministic_across_calls() -> None:
    steps = [_step(0, "click", "x"), _step(1, "type", "y")]
    assert compute_trajectory_fingerprint(steps) == compute_trajectory_fingerprint(steps)
