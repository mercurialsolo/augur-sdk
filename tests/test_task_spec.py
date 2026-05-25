"""Producer-side support for augur-schema 0.4.0 — augur-sdk#41.

Pins the SDK surface for the RL-training fields shipped in
augur-schema 0.4.0:

- Session-level ``TaskSpec`` (instruction, max_steps,
  prohibited_actions, success_conditions, reset_state_id, task_seed,
  env_id, subgoals).
- ``task_spec_id`` shortcut for producers maintaining an external
  task-spec library.
- ``group_id`` correlation for GRPO-style training; auto-propagates
  to every recorded step.
- Per-step ``record_subgoal_completion`` with auto
  ``first_completed_at_step`` tracking.
- Per-step ``set_loop_detected`` setter.
- Extended ``set_score`` with ``should_stop`` and ``uncertainty``.
- ``ScoreComponents`` canonical-key constants.
- Schema round-trip and back-compat checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import (
    CANONICAL_SCORE_COMPONENTS,
    CaptureMode,
    DebugSession,
    ScoreComponents,
)
from augur_sdk.validation import validate_bundle


def _step(idx: int = 0, *, run_id: str = "run_t") -> dict[str, Any]:
    return {
        "step_id": f"{run_id}/step/{idx:04d}",
        "step_index": idx,
        "intent": "click",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-25T00:00:00Z",
    }


# ── TaskSpec ────────────────────────────────────────────────────────


def test_task_spec_on_session_record(tmp_path: Path) -> None:
    out = tmp_path / "b"
    spec = {
        "task_spec_id": "billing.invoice.download.v1",
        "instruction": "Find the latest invoice from Acme and download it.",
        "task_class": "saas.billing",
        "max_steps": 80,
        "prohibited_actions": ["send_email", "delete_file", "purchase"],
        "success_conditions": [
            {"kind": "file_exists", "params": {"path": "/tmp/invoice.pdf"}},
        ],
        "reset_state_id": "snap-2026-05-25-acme",
        "task_seed": 42,
        "env_id": "internal-crm-staging",
        "subgoals": [
            {"subgoal_id": "open_app", "description": "Open the billing app"},
            {
                "subgoal_id": "navigate_invoices",
                "description": "Navigate to invoice list",
                "parent_subgoal_id": "open_app",
            },
        ],
    }
    with DebugSession(
        run_id="run_t",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec=spec,
    ) as s:
        s.record_step(_step(0))

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["task_spec"]["instruction"].startswith("Find")
    assert trace["session"]["task_spec"]["max_steps"] == 80
    assert validate_bundle(out) == []


def test_task_spec_id_shortcut(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_t",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec_id="billing.invoice.download.v1",
    ) as s:
        s.record_step(_step(0))

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["task_spec_id"] == "billing.invoice.download.v1"
    assert "task_spec" not in trace["session"]
    assert validate_bundle(out) == []


def test_set_task_spec_post_construction(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_t",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.set_task_spec(
            {"instruction": "Late-bound task", "max_steps": 10}
        )
        s.record_step(_step(0))

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["task_spec"]["instruction"] == "Late-bound task"


def test_task_spec_missing_instruction_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing required field: 'instruction'"):
        DebugSession(
            run_id="r",
            client_name="t",
            capture_mode=CaptureMode.METADATA,
            out_dir=tmp_path / "b",
            task_spec={"max_steps": 10},  # missing instruction
        )


def test_task_spec_duplicate_subgoal_id_raises(tmp_path: Path) -> None:
    bad = {
        "instruction": "do thing",
        "subgoals": [
            {"subgoal_id": "open_app", "description": "open"},
            {"subgoal_id": "open_app", "description": "duplicate"},
        ],
    }
    with pytest.raises(ValueError, match="duplicate subgoal_id"):
        DebugSession(
            run_id="r",
            client_name="t",
            capture_mode=CaptureMode.METADATA,
            out_dir=tmp_path / "b",
            task_spec=bad,
        )


# ── group_id ────────────────────────────────────────────────────────


def test_group_id_propagates_to_every_step(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_g",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        group_id="grpo-batch-2026-05-25-0042",
    ) as s:
        s.record_step(_step(0))
        s.record_step(_step(1))

    trace = json.loads((out / "trace.json").read_text())
    assert all(
        step["group_id"] == "grpo-batch-2026-05-25-0042"
        for step in trace["steps"]
    )


def test_set_group_id_post_construction_affects_subsequent_steps(
    tmp_path: Path,
) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_g",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))  # no group_id yet
        s.set_group_id("group-late")
        s.record_step(_step(1))

    trace = json.loads((out / "trace.json").read_text())
    assert "group_id" not in trace["steps"][0]
    assert trace["steps"][1]["group_id"] == "group-late"


def test_explicit_step_group_id_not_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_g",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        group_id="group-session",
    ) as s:
        step = _step(0)
        step["group_id"] = "group-explicit-override"
        s.record_step(step)

    trace = json.loads((out / "trace.json").read_text())
    assert trace["steps"][0]["group_id"] == "group-explicit-override"


# ── subgoal completion ──────────────────────────────────────────────


def test_record_subgoal_completion_basic(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_s",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec={
            "instruction": "do",
            "subgoals": [
                {"subgoal_id": "open_app", "description": "open"},
            ],
        },
    ) as s:
        s.record_step(_step(0))
        s.record_subgoal_completion(0, "open_app", 0.5)

    trace = json.loads((out / "trace.json").read_text())
    entries = trace["steps"][0]["subgoals_completed"]
    assert entries == [{"subgoal_id": "open_app", "completion": 0.5}]


def test_record_subgoal_completion_auto_first_completed_at_step(
    tmp_path: Path,
) -> None:
    """Once completion reaches 1.0, subsequent records carry
    first_completed_at_step (the step where it first hit 1.0)."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_s",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec={
            "instruction": "do",
            "subgoals": [{"subgoal_id": "open_app", "description": "open"}],
        },
    ) as s:
        s.record_step(_step(0))
        s.record_step(_step(1))
        s.record_step(_step(2))
        s.record_subgoal_completion(0, "open_app", 0.4)
        s.record_subgoal_completion(1, "open_app", 1.0)  # first completion
        s.record_subgoal_completion(2, "open_app", 1.0)  # carry forward

    trace = json.loads((out / "trace.json").read_text())
    e0 = trace["steps"][0]["subgoals_completed"][0]
    e1 = trace["steps"][1]["subgoals_completed"][0]
    e2 = trace["steps"][2]["subgoals_completed"][0]
    assert "first_completed_at_step" not in e0
    assert e1["first_completed_at_step"] == 1
    assert e2["first_completed_at_step"] == 1


def test_record_subgoal_completion_clamps(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_s",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec={
            "instruction": "do",
            "subgoals": [{"subgoal_id": "x", "description": "x"}],
        },
    ) as s:
        s.record_step(_step(0))
        s.record_subgoal_completion(0, "x", 1.5)  # over

    trace = json.loads((out / "trace.json").read_text())
    assert trace["steps"][0]["subgoals_completed"][0]["completion"] == 1.0


def test_record_subgoal_completion_unknown_id_warns(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_s",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec={
            "instruction": "do",
            "subgoals": [{"subgoal_id": "x", "description": "x"}],
        },
    ) as s:
        s.record_step(_step(0))
        with pytest.warns(UserWarning, match="not declared"):
            s.record_subgoal_completion(0, "y_unknown", 0.5)


def test_record_subgoal_completion_without_task_spec_no_warning(
    tmp_path: Path, recwarn: pytest.WarningsRecorder
) -> None:
    """Without a task_spec we can't validate, so no warning fires —
    the producer is just attaching free-form progress."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_s",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.record_subgoal_completion(0, "freeform", 0.3)
    assert len(recwarn) == 0


def test_record_subgoal_completion_replaces_same_subgoal_on_same_step(
    tmp_path: Path,
) -> None:
    """Calling twice for the same subgoal on the same step replaces
    the prior entry (last-write-wins)."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_s",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        task_spec={
            "instruction": "do",
            "subgoals": [{"subgoal_id": "x", "description": "x"}],
        },
    ) as s:
        s.record_step(_step(0))
        s.record_subgoal_completion(0, "x", 0.3)
        s.record_subgoal_completion(0, "x", 0.7)

    trace = json.loads((out / "trace.json").read_text())
    entries = trace["steps"][0]["subgoals_completed"]
    assert len(entries) == 1
    assert entries[0]["completion"] == 0.7


def test_record_subgoal_completion_no_step_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with (
        DebugSession(
            run_id="run_s",
            client_name="t",
            capture_mode=CaptureMode.METADATA,
            out_dir=out,
        ) as s,
        pytest.raises(ValueError, match="no step at step_index=0"),
    ):
        s.record_subgoal_completion(0, "x", 0.5)


# ── loop detection ──────────────────────────────────────────────────


def test_set_loop_detected_stamps_step(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_l",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.set_loop_detected(0)

    trace = json.loads((out / "trace.json").read_text())
    assert trace["steps"][0]["loop_detected"] is True


def test_set_loop_detected_no_step_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with (
        DebugSession(
            run_id="run_l",
            client_name="t",
            capture_mode=CaptureMode.METADATA,
            out_dir=out,
        ) as s,
        pytest.raises(ValueError, match="no step at step_index=0"),
    ):
        s.set_loop_detected(0)


# ── verdict extensions ──────────────────────────────────────────────


def test_set_score_with_should_stop_and_uncertainty(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        step = _step(0)
        step["verdict"] = {"status": "passed"}
        s.record_step(step)
        s.set_score(
            0,
            0.92,
            comparator="verifier",
            components={
                ScoreComponents.PROGRESS: 0.25,
                ScoreComponents.ACTION_QUALITY: 0.9,
                ScoreComponents.SAFETY_RISK: 0.0,
            },
            should_stop=False,
            uncertainty=0.08,
        )

    trace = json.loads((out / "trace.json").read_text())
    verdict = trace["steps"][0]["verdict"]
    assert verdict["should_stop"] is False
    assert verdict["uncertainty"] == 0.08
    assert verdict["score"] == 0.92
    assert verdict["score_components"]["progress"] == 0.25


def test_set_score_uncertainty_clamped(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_v",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        step = _step(0)
        step["verdict"] = {"status": "passed"}
        s.record_step(step)
        s.set_score(0, 0.5, uncertainty=2.5)  # over 1

    trace = json.loads((out / "trace.json").read_text())
    assert trace["steps"][0]["verdict"]["uncertainty"] == 1.0


# ── ScoreComponents constants ───────────────────────────────────────


def test_score_components_constants_match_canonical_set() -> None:
    """The exported constants stay in sync with the canonical set
    documented in augur-schema 0.4.0."""
    assert frozenset(
        {
            "progress",
            "action_quality",
            "process_quality",
            "safety_risk",
            "loopiness",
            "verifier_confidence",
            "grounding_accuracy",
        }
    ) == CANONICAL_SCORE_COMPONENTS
    # The class attribute values are the string keys.
    assert ScoreComponents.PROGRESS == "progress"
    assert ScoreComponents.SAFETY_RISK == "safety_risk"


# ── round-trip + back-compat ────────────────────────────────────────


def test_full_0_4_0_bundle_round_trips(tmp_path: Path) -> None:
    """End-to-end: a session exercising every new 0.4.0 surface
    produces a bundle that validates clean."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_full",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        group_id="grp-1",
        task_spec={
            "task_spec_id": "tsk.v1",
            "instruction": "do",
            "subgoals": [{"subgoal_id": "x", "description": "x"}],
        },
    ) as s:
        step = _step(0)
        step["verdict"] = {"status": "passed"}
        s.record_step(step)
        s.record_subgoal_completion(0, "x", 1.0)
        s.set_loop_detected(0, value=False)
        s.set_score(
            0,
            0.95,
            comparator="verifier",
            components={ScoreComponents.PROGRESS: 1.0},
            should_stop=True,
            uncertainty=0.01,
        )

    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_session_without_any_new_fields_still_valid(tmp_path: Path) -> None:
    """Back-compat: a session that doesn't touch any 0.4.0 surface
    emits a bundle with no new fields, and validates cleanly."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="run_legacy",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))

    trace = json.loads((out / "trace.json").read_text())
    assert "task_spec" not in trace["session"]
    assert "task_spec_id" not in trace["session"]
    assert "group_id" not in trace["steps"][0]
    assert "loop_detected" not in trace["steps"][0]
    assert "subgoals_completed" not in trace["steps"][0]
    assert validate_bundle(out) == []
