"""StepTrace iteration semantics — augur-sdk#30 + augur-sdk#31.

Covers:
- step_id keying in the recorder (#30): two record_step() calls with the
  same step_index but distinct step_ids produce two on-disk files and
  both reload.
- Bundle layout: single-emission steps keep the flat
  `steps/<NNNN>.json` path (byte-identical with pre-0.3.0 bundles);
  steps with iterations move to `steps/<NNNN>/<short_id>.json`.
- record_step_iteration() helper (#31): appends iterations under an
  existing canonical step, bumps step_iterations, and stages each
  iteration's payload addressably on close.
- record_step() with a new step_id at an existing step_index emits a
  DeprecationWarning pointing at record_step_iteration().
"""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


def _step(run_id: str, idx: int, *, suffix: str = "") -> dict[str, Any]:
    step_id = f"{run_id}/step/{idx:04d}" + (f"/iter/{suffix}" if suffix else "")
    return {
        "step_id": step_id,
        "step_index": idx,
        "intent": f"step {idx} {suffix}".strip(),
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-25T00:00:00Z",
        "ended_at": "2026-05-25T00:00:01Z",
        "duration_ms": 1000,
    }


def _short(step_id: str) -> str:
    return hashlib.sha256(step_id.encode("utf-8")).hexdigest()[:8]


# ── #30: step_id keying preserves single-emission layout ──────────────────


def test_single_emission_keeps_flat_step_file(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_a",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step("run_a", 0))
        s.record_step(_step("run_a", 1))

    assert (out / "steps" / "0000.json").exists()
    assert (out / "steps" / "0001.json").exists()
    assert not (out / "steps" / "0000").is_dir()
    assert not (out / "steps" / "0001").is_dir()
    assert validate_bundle(out) == []


def test_update_same_step_id_is_idempotent(tmp_path: Path) -> None:
    """``running`` → ``succeeded`` update under the same step_id stays
    last-write-wins and MUST NOT emit a DeprecationWarning — the issue
    explicitly preserves ``record_step()``'s "existing single-emission
    semantics" for this common producer pattern."""
    out = tmp_path / "bundle"
    with (
        DebugSession(
            run_id="run_a",
            client_name="testclient",
            capture_mode=CaptureMode.METADATA,
            out_dir=out,
        ) as s,
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("error", DeprecationWarning)
        running = _step("run_a", 0)
        running["status"] = "running"
        s.record_step(running)
        finished = _step("run_a", 0)
        finished["status"] = "succeeded"
        s.record_step(finished)

    payload = json.loads((out / "steps" / "0000.json").read_text())
    assert payload["status"] == "succeeded"
    # Single emission semantics: no iteration counter, flat layout.
    assert "step_iterations" not in payload
    assert not (out / "steps" / "0000").is_dir()


# ── #30: two record_step() calls with distinct step_ids ──────────────────


def test_record_step_distinct_step_ids_produces_two_files(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_b",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        canonical = _step("run_b", 0)
        s.record_step(canonical)
        iteration = _step("run_b", 0, suffix="1")
        iteration["intent"] = "retry"
        with (
            warnings.catch_warnings(),
            pytest.raises(DeprecationWarning),
        ):
            warnings.simplefilter("error", DeprecationWarning)
            s.record_step(iteration)

    iter_dir = out / "steps" / "0000"
    assert iter_dir.is_dir()
    files = sorted(iter_dir.glob("*.json"))
    assert len(files) == 2
    by_short = {p.stem: json.loads(p.read_text()) for p in files}
    assert _short(canonical["step_id"]) in by_short
    assert _short(iteration["step_id"]) in by_short
    # Both step_ids round-trip addressably.
    assert {p["step_id"] for p in by_short.values()} == {
        canonical["step_id"],
        iteration["step_id"],
    }
    # Flat path is NOT written when iterations exist.
    assert not (out / "steps" / "0000.json").exists()
    assert validate_bundle(out) == []


# ── #31: record_step_iteration helper ─────────────────────────────────────


def test_record_step_iteration_bumps_counter_and_persists_iterations(
    tmp_path: Path,
) -> None:
    """Issue #31 round-trip exit criterion: emit 1 canonical step + 5
    iterations, close, reload — ``step_iterations == 6`` and all 6
    iteration payloads MUST be addressable by step_id from disk."""
    out = tmp_path / "bundle"
    expected_step_ids: list[str] = []
    expected_intents: dict[str, str] = {}
    with DebugSession(
        run_id="run_c",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        canonical = _step("run_c", 0)
        canonical["intent"] = "canonical click"
        s.record_step(canonical)
        expected_step_ids.append(canonical["step_id"])
        expected_intents[canonical["step_id"]] = "canonical click"
        for i in range(1, 6):
            iter_payload = _step("run_c", 0, suffix=str(i))
            iter_payload["intent"] = f"iteration {i}"
            s.record_step_iteration(0, iter_payload)
            expected_step_ids.append(iter_payload["step_id"])
            expected_intents[iter_payload["step_id"]] = f"iteration {i}"

    # 1 canonical + 5 iterations → 6 files.
    iter_dir = out / "steps" / "0000"
    assert iter_dir.is_dir()
    files = sorted(iter_dir.glob("*.json"))
    assert len(files) == 6

    # Reload + index by step_id. Every iteration's payload MUST be
    # addressable from disk; payloads MUST be distinct (no overwrites).
    by_id: dict[str, dict[str, Any]] = {
        json.loads(p.read_text())["step_id"]: json.loads(p.read_text())
        for p in files
    }
    assert set(by_id) == set(expected_step_ids)
    for sid, intent in expected_intents.items():
        assert by_id[sid]["intent"] == intent
        assert by_id[sid]["step_index"] == 0

    # step_iterations == 6 on the canonical, both in trace.json and on
    # the canonical's per-iteration file.
    trace = json.loads((out / "trace.json").read_text())
    assert len(trace["steps"]) == 1
    assert trace["steps"][0]["step_iterations"] == 6
    assert by_id[canonical["step_id"]]["step_iterations"] == 6
    # Iteration payloads SHOULD NOT carry the counter — only the
    # canonical does. Otherwise consumers would double-count.
    for sid in expected_step_ids[1:]:
        assert "step_iterations" not in by_id[sid]

    assert validate_bundle(out) == []


def test_record_step_iteration_accepts_canonical_step_id(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_d",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        canonical = _step("run_d", 3)
        s.record_step(canonical)
        s.record_step_iteration(
            canonical["step_id"], _step("run_d", 3, suffix="a")
        )
        s.record_step_iteration(
            canonical["step_id"], _step("run_d", 3, suffix="b")
        )

    trace = json.loads((out / "trace.json").read_text())
    canonical_on_trace = next(
        s for s in trace["steps"] if s["step_index"] == 3
    )
    assert canonical_on_trace["step_iterations"] == 3
    assert (out / "steps" / "0003").is_dir()
    assert len(list((out / "steps" / "0003").glob("*.json"))) == 3


def test_record_step_iteration_without_canonical_raises(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_e",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s, pytest.raises(ValueError, match="no canonical step"):
        s.record_step_iteration(0, _step("run_e", 0, suffix="1"))


def test_record_step_iteration_collision_raises(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_f",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        canonical = _step("run_f", 0)
        s.record_step(canonical)
        # Re-using the canonical step_id as an iteration id is rejected.
        with pytest.raises(ValueError, match="collides"):
            s.record_step_iteration(0, canonical)


def test_record_step_does_not_warn_for_new_step_index(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_g",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s, warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        s.record_step(_step("run_g", 0))
        s.record_step(_step("run_g", 1))


# ── manifest signatures cover iteration files ────────────────────────────


def test_manifest_signatures_include_iteration_paths(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_h",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        canonical = _step("run_h", 0)
        s.record_step(canonical)
        s.record_step_iteration(0, _step("run_h", 0, suffix="1"))

    manifest = json.loads((out / "manifest.json").read_text())
    sigs = manifest["signatures"]
    assert any(
        path.startswith("steps/0000/") and path.endswith(".json")
        for path in sigs
    )
    assert "steps/0000.json" not in sigs
