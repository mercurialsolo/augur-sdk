"""DebugSession.branch_from() — replay-branch execution (#25)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
        "426082"
    )


def _step(idx: int, target: str = "x") -> dict[str, Any]:
    return {
        "step_id": f"r/step/{idx:04d}",
        "step_index": idx,
        "intent": f"click {target}",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-23T00:00:00Z",
        "action": {"type": "click"},
        "grounding": {
            "provider": "t",
            "target_label": target,
            "provenance": "screenshot",
        },
        "verdict": {"status": "passed"},
    }


def _make_parent_bundle(out: Path, n_steps: int = 5) -> Path:
    """Write a synthetic parent bundle with n_steps and pre/post screenshots."""
    with DebugSession(
        run_id="run_parent",
        client_name="t",
        capture_mode=CaptureMode.SCREENSHOTS,
        out_dir=out,
    ) as s:
        for i in range(n_steps):
            pre = s.attach_observation(
                step_index=i, kind="pre", png_bytes=_png_bytes()
            )
            post = s.attach_observation(
                step_index=i, kind="post", png_bytes=_png_bytes()
            )
            step = _step(i, target=f"target_{i}")
            step["observation_pre"] = pre
            step["observation_post"] = post
            s.record_step(step)  # type: ignore[arg-type]
    return out


# ── basic construction ──────────────────────────────────────────────────────


def test_sandbox_mode_stamps_branch_context_only(tmp_path: Path) -> None:
    out = tmp_path / "branch"
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=3,
        mutated_axis="action",
        mutation={"action_override": {"x": 100, "y": 200}},
        client_name="t",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
    ) as s:
        assert s.branch_mode == "sandbox"
        s.record_step(_step(0, target="new"))  # type: ignore[arg-type]

    trace = json.loads((out / "trace.json").read_text())
    sess_ctx = trace["session"]["branch_context"]
    assert sess_ctx["parent_run_id"] == "run_parent"
    assert sess_ctx["mutated_axis"] == "action"
    assert sess_ctx["mutation"] == {"action_override": {"x": 100, "y": 200}}
    # Only the step the producer recorded — no replay prefix in sandbox.
    assert trace["steps"][0]["step_index"] == 0
    assert len(trace["steps"]) == 1


def test_branch_id_is_generated_when_unset(tmp_path: Path) -> None:
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=0,
        mutated_axis="model",
        mutation={"model": "claude-opus-4-7"},
        client_name="t",
        out_dir=tmp_path / "b",
        mode="sandbox",
    ) as s:
        assert s.run_id.startswith("run_parent:branch:")


def test_explicit_branch_id_used_as_run_id(tmp_path: Path) -> None:
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=0,
        mutated_axis="model",
        mutation={"model": "x"},
        client_name="t",
        out_dir=tmp_path / "b",
        mode="sandbox",
        branch_id="run_parent:branch:exp1",
    ) as s:
        assert s.run_id == "run_parent:branch:exp1"


# ── auto mode ───────────────────────────────────────────────────────────────


def test_auto_mode_picks_sandbox_for_action_axis(tmp_path: Path) -> None:
    with DebugSession.branch_from(
        parent_run_id="r",
        branch_point_step_index=0,
        mutated_axis="action",
        mutation={"x": 1},
        client_name="t",
        out_dir=tmp_path / "b",
        mode="auto",
    ) as s:
        assert s.branch_mode == "sandbox"


@pytest.mark.parametrize("axis", ["model", "prompt", "grounder", "tool_description"])
def test_auto_mode_picks_replay_for_upstream_axes(
    tmp_path: Path, axis: str
) -> None:
    parent = tmp_path / "parent"
    _make_parent_bundle(parent, n_steps=3)
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=2,
        mutated_axis=axis,
        mutation={"value": "x"},
        client_name="t",
        out_dir=tmp_path / "b",
        mode="auto",
        parent_bundle=parent,
    ) as s:
        assert s.branch_mode == "replay"


# ── replay mode ─────────────────────────────────────────────────────────────


def test_replay_loads_parent_prefix(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    _make_parent_bundle(parent, n_steps=5)

    out = tmp_path / "branch"
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=3,
        mutated_axis="model",
        mutation={"model": "claude-opus-4-7"},
        client_name="t",
        out_dir=out,
        capture_mode=CaptureMode.SCREENSHOTS,
        mode="replay",
        parent_bundle=parent,
    ) as s:
        assert s.branch_mode == "replay"
        # Producer continues from the branch point with new behavior.
        s.record_step(_step(3, target="new_target_after_branch"))  # type: ignore[arg-type]
        s.record_step(_step(4, target="another_after_branch"))  # type: ignore[arg-type]

    trace = json.loads((out / "trace.json").read_text())
    steps = trace["steps"]
    # Prefix (0,1,2) replayed from parent + new (3,4) from producer.
    assert [s["step_index"] for s in steps] == [0, 1, 2, 3, 4]
    # Prefix steps carry the parent's target labels.
    assert steps[0]["grounding"]["target_label"] == "target_0"
    assert steps[2]["grounding"]["target_label"] == "target_2"
    # Branch-point and later carry the new producer's labels.
    assert steps[3]["grounding"]["target_label"] == "new_target_after_branch"
    # Every step — prefix and fresh — carries branch_context.
    for s in steps:
        assert s["branch_context"]["parent_run_id"] == "run_parent"
        assert s["branch_context"]["branch_point_step_index"] == 3


def test_replay_copies_screenshots_from_parent(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    _make_parent_bundle(parent, n_steps=4)

    out = tmp_path / "branch"
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=2,
        mutated_axis="prompt",
        mutation={"prompt_id": "v2"},
        client_name="t",
        out_dir=out,
        capture_mode=CaptureMode.SCREENSHOTS,
        mode="replay",
        parent_bundle=parent,
    ):
        pass

    # Prefix screenshots (0, 1) are present in the branch bundle.
    assert (out / "screenshots" / "0000_pre.png").exists()
    assert (out / "screenshots" / "0000_post.png").exists()
    assert (out / "screenshots" / "0001_pre.png").exists()
    # Step 2 is the branch point — the parent's step 2 screenshots are
    # NOT copied (those came from the parent's pre-mutation execution).
    assert not (out / "screenshots" / "0002_pre.png").exists()


def test_replay_refuses_when_action_is_mutated(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    _make_parent_bundle(parent, n_steps=3)
    with pytest.raises(ValueError, match="replay mode is unsound"):
        DebugSession.branch_from(
            parent_run_id="run_parent",
            branch_point_step_index=1,
            mutated_axis="action",
            mutation={"x": 1, "y": 2},
            client_name="t",
            out_dir=tmp_path / "b",
            mode="replay",
            parent_bundle=parent,
        )


def test_replay_requires_parent_bundle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="replay mode needs parent_bundle"):
        DebugSession.branch_from(
            parent_run_id="run_parent",
            branch_point_step_index=1,
            mutated_axis="model",
            mutation={"model": "x"},
            client_name="t",
            out_dir=tmp_path / "b",
            mode="replay",
        )


def test_replay_missing_parent_trace_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="trace.json"):
        DebugSession.branch_from(
            parent_run_id="r",
            branch_point_step_index=1,
            mutated_axis="model",
            mutation={"model": "x"},
            client_name="t",
            out_dir=tmp_path / "b",
            mode="replay",
            parent_bundle=empty,
        )


# ── validation ──────────────────────────────────────────────────────────────


def test_unknown_axis_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mutated_axis must be"):
        DebugSession.branch_from(
            parent_run_id="r",
            branch_point_step_index=0,
            mutated_axis="temperature",
            mutation={},
            client_name="t",
            out_dir=tmp_path / "b",
        )


def test_negative_branch_point_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="branch_point_step_index must be >= 0"):
        DebugSession.branch_from(
            parent_run_id="r",
            branch_point_step_index=-1,
            mutated_axis="model",
            mutation={"model": "x"},
            client_name="t",
            out_dir=tmp_path / "b",
        )


def test_unknown_mode_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mode must be"):
        DebugSession.branch_from(
            parent_run_id="r",
            branch_point_step_index=0,
            mutated_axis="model",
            mutation={"model": "x"},
            client_name="t",
            out_dir=tmp_path / "b",
            mode="rewind",
        )


def test_branch_point_zero_replay_loads_no_prefix(tmp_path: Path) -> None:
    """branch_point_step_index=0 means no prefix to replay — entire run is fresh."""
    parent = tmp_path / "parent"
    _make_parent_bundle(parent, n_steps=3)

    out = tmp_path / "branch"
    with DebugSession.branch_from(
        parent_run_id="run_parent",
        branch_point_step_index=0,
        mutated_axis="model",
        mutation={"model": "x"},
        client_name="t",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
        mode="replay",
        parent_bundle=parent,
    ) as s:
        s.record_step(_step(0, target="fresh_from_zero"))  # type: ignore[arg-type]

    trace = json.loads((out / "trace.json").read_text())
    assert len(trace["steps"]) == 1
    assert trace["steps"][0]["grounding"]["target_label"] == "fresh_from_zero"


def test_session_kwargs_passed_through(tmp_path: Path) -> None:
    """Extra session kwargs (tags, client_version) flow into the child."""
    with DebugSession.branch_from(
        parent_run_id="r",
        branch_point_step_index=0,
        mutated_axis="model",
        mutation={"model": "x"},
        client_name="t",
        out_dir=tmp_path / "b",
        mode="sandbox",
        client_version="9.9.9",
        tags={"experiment": "X"},
    ) as s:
        assert s._tags == {"experiment": "X"}
        assert s._client_version == "9.9.9"
