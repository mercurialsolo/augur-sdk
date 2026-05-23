"""finalize_outcome() — couple verdict + cost + task_class (#18)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession


def _step(idx: int = 0, verdict: str = "passed") -> dict[str, Any]:
    return {
        "step_id": f"r/step/{idx:04d}",
        "step_index": idx,
        "intent": "click",
        "step_type": "click",
        "required": True,
        "status": "succeeded" if verdict == "passed" else "failed",
        "started_at": "2026-05-19T00:00:00Z",
        "verdict": {"status": verdict},
    }


def test_step_scope_outcome_couples_verdict_and_cost(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.set_step_costs(0, total_usd=0.5, tokens_in=10)
        s.finalize_outcome(scope="step", step_index=0, task_class="login_flow")

    payload = json.loads((out / "outcomes.json").read_text())
    assert len(payload["outcomes"]) == 1
    outcome = payload["outcomes"][0]
    assert outcome["scope"] == "step"
    assert outcome["task_class"] == "login_flow"
    assert outcome["verdict"]["status"] == "passed"
    assert outcome["cost_summary"]["total_usd"] == 0.5
    assert outcome["cost_summary"]["tokens_in"] == 10
    assert outcome["step_index"] == 0


def test_session_scope_rolls_up_step_costs(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.record_step(_step(1))
        s.set_step_costs(0, total_usd=0.5, tokens_in=10)
        s.set_step_costs(1, total_usd=0.3, tokens_in=5)
        s.finalize_outcome(
            scope="session",
            task_class="login_flow",
            verdict={"status": "passed", "reason": "all steps green"},
        )

    payload = json.loads((out / "outcomes.json").read_text())
    outcome = payload["outcomes"][0]
    assert outcome["scope"] == "session"
    assert outcome["verdict"]["status"] == "passed"
    assert outcome["cost_summary"]["total_usd"] == 0.8
    assert outcome["cost_summary"]["tokens_in"] == 15
    assert outcome["debug_session_id"].startswith("dbg_")


def test_session_costs_take_precedence(tmp_path: Path) -> None:
    """Session-level costs (set_costs) override the per-step roll-up
    for the same key."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.set_step_costs(0, total_usd=999.0)
        s.set_costs(total_usd=1.0)  # session-level wins
        s.finalize_outcome(scope="session")

    payload = json.loads((out / "outcomes.json").read_text())
    assert payload["outcomes"][0]["cost_summary"]["total_usd"] == 1.0


def test_explicit_cost_summary_overrides_rollup(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.set_step_costs(0, total_usd=0.5)
        s.finalize_outcome(scope="session", cost_summary={"total_usd": 42.0})

    payload = json.loads((out / "outcomes.json").read_text())
    assert payload["outcomes"][0]["cost_summary"] == {"total_usd": 42.0}


def test_step_scope_requires_step_index(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="requires step_index"):
        s.finalize_outcome(scope="step")


def test_step_scope_unknown_step_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="no step at step_index"):
        s.finalize_outcome(scope="step", step_index=99)


def test_invalid_scope_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="scope must be"):
        s.finalize_outcome(scope="run")


def test_no_outcomes_no_file(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))

    assert not (out / "outcomes.json").exists()


def test_streaming_post_outcome_called(tmp_path: Path) -> None:
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

        def post_outcome(self, outcome: dict[str, Any]) -> None:
            calls.append(outcome)

    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s._stream = FakeSink()  # type: ignore[assignment]
        s.record_step(_step(0))
        s.finalize_outcome(scope="step", step_index=0, task_class="login")

    assert len(calls) == 1
    assert calls[0]["task_class"] == "login"


def test_successful_task_cost_summary_helper(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.set_step_costs(0, total_usd=0.4, tokens_in=10)
        s.set_costs(model_usd=0.1)
        summary = s.successful_task_cost_summary()

    assert summary == {"total_usd": 0.4, "tokens_in": 10, "model_usd": 0.1}


def test_no_outcome_call_is_no_op(tmp_path: Path) -> None:
    """Bundles that never call finalize_outcome work as before."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))

    # Manifest still exists and contains the step.
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["step_count"] == 1
