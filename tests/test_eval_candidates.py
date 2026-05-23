"""mark_for_eval() — tag a step as regression-fixture candidate (#16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from augur_sdk import CaptureMode, DebugSession


def _step(idx: int = 0) -> dict[str, Any]:
    return {
        "step_id": f"r/step/{idx:04d}",
        "step_index": idx,
        "intent": "click",
        "step_type": "click",
        "required": True,
        "status": "failed",
        "started_at": "2026-05-19T00:00:00Z",
    }


def test_mark_for_eval_lands_in_bundle(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.record_step(_step(1))
        s.mark_for_eval(0, reason="wrong target", candidate_cluster_id="cluster-a")
        s.mark_for_eval(1, reason="silent skip")

    candidates_file = out / "eval_candidates.json"
    assert candidates_file.exists()
    payload = json.loads(candidates_file.read_text())
    assert len(payload["candidates"]) == 2
    by_idx = {c["step_index"]: c for c in payload["candidates"]}
    assert by_idx[0]["reason"] == "wrong target"
    assert by_idx[0]["candidate_cluster_id"] == "cluster-a"
    assert "tagged_at" in by_idx[0]
    assert by_idx[1]["reason"] == "silent skip"
    assert "candidate_cluster_id" not in by_idx[1]


def test_mark_for_eval_is_idempotent_on_step_index(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.mark_for_eval(0, reason="first try")
        s.mark_for_eval(0, reason="actually this one", candidate_cluster_id="x")

    payload = json.loads((out / "eval_candidates.json").read_text())
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["reason"] == "actually this one"
    assert payload["candidates"][0]["candidate_cluster_id"] == "x"


def test_no_eval_candidates_means_no_file(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))

    assert not (out / "eval_candidates.json").exists()


def test_streaming_post_eval_candidate_called(tmp_path: Path) -> None:
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

        def post_eval_candidate(self, candidate: dict[str, Any]) -> None:
            calls.append(candidate)

    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s._stream = FakeSink()  # type: ignore[assignment]
        s.record_step(_step(0))
        s.mark_for_eval(0, reason="needs attention")

    assert len(calls) == 1
    assert calls[0]["reason"] == "needs attention"
    assert calls[0]["step_index"] == 0


def test_tag_before_record_step_allowed(tmp_path: Path) -> None:
    """Tag eagerly; the post-action result may arrive later."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        # Tag before the step exists — must not raise.
        s.mark_for_eval(0, reason="speculative")
        s.record_step(_step(0))

    payload = json.loads((out / "eval_candidates.json").read_text())
    assert payload["candidates"][0]["reason"] == "speculative"
