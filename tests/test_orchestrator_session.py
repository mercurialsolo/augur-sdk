"""Fanout-orchestrator helper — augur-sdk#38.

`DebugSession.open_orchestrator(...)` is the producer-side ergonomic
for a parent-only session in a fanout pattern. The session carries
aggregate tags/costs/metadata but has no step traces of its own;
sibling child sessions point at it via
`branch_context.parent_run_id=<this run_id>`.

Pins:
- The session lands with the `augur.session_type=orchestrator` tag so
  viewers can render it as a parent row.
- `session_name` / `tenant_id` kwargs land as tags by the same names.
- `record_step`, `record_step_iteration`, and `attach_observation`
  raise — the contract is enforced at the SDK boundary.
- `set_costs` and `add_tag` work normally; trace.json round-trips
  cleanly through `validate_bundle` (step_count=0).
- The grouping-contract semantics (children share
  `branch_context.parent_run_id`) round-trip through the SDK so
  consumers can rely on the contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import (
    ORCHESTRATOR_TAG_KEY,
    ORCHESTRATOR_TAG_VALUE,
    CaptureMode,
    DebugSession,
)
from augur_sdk.validation import validate_bundle


def _step(idx: int = 0, *, run_id: str = "child_run") -> dict[str, Any]:
    return {
        "step_id": f"{run_id}/step/{idx:04d}",
        "step_index": idx,
        "intent": "click",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-25T00:00:00Z",
    }


def test_open_orchestrator_stamps_session_type_tag(tmp_path: Path) -> None:
    out = tmp_path / "parent"
    with DebugSession.open_orchestrator(
        run_id="fanout-abc",
        client_name="myproducer",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
        tags={"phase1_workers": "4", "fanout_pattern": "phase1_collect_phase2_extract"},
    ) as parent:
        assert parent.is_orchestrator is True

    trace = json.loads((out / "trace.json").read_text())
    tags = trace["session"]["tags"]
    assert tags[ORCHESTRATOR_TAG_KEY] == ORCHESTRATOR_TAG_VALUE
    assert tags["phase1_workers"] == "4"
    assert tags["fanout_pattern"] == "phase1_collect_phase2_extract"


def test_open_orchestrator_writes_empty_step_bundle(tmp_path: Path) -> None:
    out = tmp_path / "parent"
    with DebugSession.open_orchestrator(
        run_id="fanout-empty",
        client_name="myproducer",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
    ):
        pass

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["step_count"] == 0
    trace = json.loads((out / "trace.json").read_text())
    assert trace["steps"] == []
    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_open_orchestrator_forbids_record_step(tmp_path: Path) -> None:
    out = tmp_path / "parent"
    with (
        DebugSession.open_orchestrator(
            run_id="fanout-no-steps",
            client_name="myproducer",
            out_dir=out,
            capture_mode=CaptureMode.METADATA,
        ) as parent,
        pytest.raises(RuntimeError, match="not supported on an orchestrator session"),
    ):
        parent.record_step(_step(0))


def test_open_orchestrator_forbids_record_step_iteration(tmp_path: Path) -> None:
    out = tmp_path / "parent"
    with (
        DebugSession.open_orchestrator(
            run_id="fanout-no-iters",
            client_name="myproducer",
            out_dir=out,
            capture_mode=CaptureMode.METADATA,
        ) as parent,
        pytest.raises(RuntimeError, match="not supported on an orchestrator session"),
    ):
        parent.record_step_iteration(0, _step(0))


def test_open_orchestrator_forbids_attach_observation(tmp_path: Path) -> None:
    out = tmp_path / "parent"
    with (
        DebugSession.open_orchestrator(
            run_id="fanout-no-obs",
            client_name="myproducer",
            out_dir=out,
            capture_mode=CaptureMode.METADATA,
        ) as parent,
        pytest.raises(RuntimeError, match="not supported on an orchestrator session"),
    ):
        parent.attach_observation(step_index=0, kind="pre", png_bytes=b"\x89PNG")


def test_open_orchestrator_supports_set_costs_and_add_tag(tmp_path: Path) -> None:
    out = tmp_path / "parent"
    with DebugSession.open_orchestrator(
        run_id="fanout-with-costs",
        client_name="myproducer",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
    ) as parent:
        parent.set_costs(total_usd=1.42, model_usd=1.20, tokens_in=12_000)
        parent.add_tag("budget_usd", "5.00")

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["costs"] == {
        "total_usd": 1.42,
        "model_usd": 1.20,
        "tokens_in": 12_000,
    }
    assert trace["session"]["tags"]["budget_usd"] == "5.00"
    assert (
        trace["session"]["tags"][ORCHESTRATOR_TAG_KEY] == ORCHESTRATOR_TAG_VALUE
    )
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["costs"]["total_usd"] == 1.42


def test_open_orchestrator_session_name_and_tenant_id_land_as_tags(
    tmp_path: Path,
) -> None:
    out = tmp_path / "parent"
    with DebugSession.open_orchestrator(
        run_id="fanout-named",
        client_name="myproducer",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
        session_name="boattrader-fanout (4 workers)",
        tenant_id="acme-tenant",
    ):
        pass

    trace = json.loads((out / "trace.json").read_text())
    tags = trace["session"]["tags"]
    assert tags["session_name"] == "boattrader-fanout (4 workers)"
    assert tags["tenant_id"] == "acme-tenant"


def test_open_orchestrator_caller_tags_win_over_convenience_kwargs(
    tmp_path: Path,
) -> None:
    """An explicit `tags={'session_name': X}` should not be silently
    overwritten by the `session_name=...` convenience kwarg."""
    out = tmp_path / "parent"
    with DebugSession.open_orchestrator(
        run_id="fanout-named",
        client_name="myproducer",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
        session_name="convenience-wins",
        tags={"session_name": "explicit-wins"},
    ):
        pass

    trace = json.loads((out / "trace.json").read_text())
    assert trace["session"]["tags"]["session_name"] == "explicit-wins"


def test_orchestrator_marker_flag_via_is_orchestrator_property(
    tmp_path: Path,
) -> None:
    out = tmp_path / "parent"
    parent = DebugSession.open_orchestrator(
        run_id="fanout-flag",
        client_name="myproducer",
        out_dir=out,
        capture_mode=CaptureMode.METADATA,
    )
    assert parent.is_orchestrator is True

    sibling = DebugSession(
        run_id="ordinary-run",
        client_name="myproducer",
        capture_mode=CaptureMode.METADATA,
        out_dir=tmp_path / "ordinary",
    )
    assert sibling.is_orchestrator is False


def test_grouping_contract_children_share_parent_run_id(tmp_path: Path) -> None:
    """End-to-end shape of the grouping contract: a parent orchestrator
    session plus N child sessions that carry
    `branch_context.parent_run_id` pointing at the parent. The viewer
    is expected to group them under the parent (per Proposal A in #38);
    the SDK's job is just to make the linkage explicit and stable."""
    parent_out = tmp_path / "parent"
    with DebugSession.open_orchestrator(
        run_id="fanout-grp",
        client_name="myproducer",
        out_dir=parent_out,
        capture_mode=CaptureMode.METADATA,
        tags={"phase1_workers": "2"},
    ) as parent:
        parent.set_costs(total_usd=0.10)

    # Two child sessions point at the parent via branch_context. The
    # mutated_axis isn't strictly meaningful for fanout siblings — the
    # schema requires it, so producers pick the closest match (often
    # "action" for genuinely independent fanout work). The load-bearing
    # field is `parent_run_id`.
    children: list[Path] = []
    for i in range(2):
        child_out = tmp_path / f"child_{i}"
        children.append(child_out)
        with DebugSession(
            run_id=f"fanout-grp:phase2_w{i}",
            client_name="myproducer",
            capture_mode=CaptureMode.METADATA,
            out_dir=child_out,
            branch_context={
                "parent_run_id": "fanout-grp",
                "branch_point_step_index": 0,
                "mutated_axis": "action",
                "branch_id": f"fanout-grp:phase2_w{i}",
            },
        ) as child:
            child.record_step(_step(0, run_id=f"fanout-grp_w{i}"))

    # Parent session writes the orchestrator marker.
    parent_trace = json.loads((parent_out / "trace.json").read_text())
    assert (
        parent_trace["session"]["tags"][ORCHESTRATOR_TAG_KEY]
        == ORCHESTRATOR_TAG_VALUE
    )
    # Every child resolves back to the parent via branch_context.
    for child_out in children:
        child_trace = json.loads((child_out / "trace.json").read_text())
        assert (
            child_trace["session"]["branch_context"]["parent_run_id"]
            == "fanout-grp"
        )
        # The lightweight slice propagates to each step so server-side
        # cohort filters and grouping logic don't have to join back.
        assert (
            child_trace["steps"][0]["branch_context"]["parent_run_id"]
            == "fanout-grp"
        )
