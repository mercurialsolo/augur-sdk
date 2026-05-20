"""DebugSession.attach_verifier (0.1.5) — behavioural coverage.

The method lets an external harness add a post-hoc verdict to a step
the producer didn't categorize. Replaces the step's `verdict` field
in-place; streams the patched step through the live sink so viewers
see the update without waiting for close().
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession


def _step(idx: int, *, verdict: dict[str, Any] | None = None) -> dict[str, Any]:
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


def test_attach_verifier_replaces_verdict_in_place(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))  # no verdict
        s.attach_verifier(0, status="failed", reason="post-state mismatch")

    written = json.loads((out / "steps" / "0000.json").read_text())
    assert written["verdict"] == {"status": "failed", "reason": "post-state mismatch"}


def test_attach_verifier_composes_reason_from_check_expected_actual(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.attach_verifier(
            0,
            status="failed",
            check="dom.contains_text",
            expected="Welcome",
            actual="Sign in",
        )

    v = json.loads((out / "steps" / "0000.json").read_text())["verdict"]
    assert v["status"] == "failed"
    assert "dom.contains_text" in v["reason"]
    assert "'Welcome'" in v["reason"]
    assert "'Sign in'" in v["reason"]


def test_attach_verifier_overrides_existing_verdict(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0, verdict={"status": "unknown"}))
        s.attach_verifier(0, status="passed", reason="external check ok")

    v = json.loads((out / "steps" / "0000.json").read_text())["verdict"]
    assert v == {"status": "passed", "reason": "external check ok"}


def test_attach_verifier_records_evidence_refs(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.attach_verifier(
            0,
            status="failed",
            reason="dom check failed",
            evidence_refs=["screenshots/0000_post.png", "events/0000.jsonl"],
        )

    v = json.loads((out / "steps" / "0000.json").read_text())["verdict"]
    assert v["evidence_refs"] == ["screenshots/0000_post.png", "events/0000.jsonl"]


def test_attach_verifier_raises_for_unknown_step_index(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_t",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        with pytest.raises(ValueError, match="no step at step_index=7"):
            s.attach_verifier(7, status="failed")
