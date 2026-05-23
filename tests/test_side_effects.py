"""Side-effect ledger API (#11): declare / commit / abort lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from augur_schema import validator_for

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


def _step(idx: int = 0) -> dict[str, Any]:
    return {
        "step_id": f"r/step/{idx:04d}",
        "step_index": idx,
        "intent": "submit",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-19T00:00:00Z",
    }


def test_declare_then_commit_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        sid = s.declare_side_effect(
            0,
            resource="stripe:cus_x",
            action="payment_create",
            idempotency_key="key-42",
            reversibility="irreversible",
        )
        s.commit_side_effect(sid, observed_result={"id": "ch_y"})

    files = sorted((out / "side_effects").glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["side_effect_id"] == sid
    assert record["status"] == "committed"
    assert record["resource"] == "stripe:cus_x"
    assert record["action"] == "payment_create"
    assert record["idempotency_key"] == "key-42"
    assert record["step_id"] == "r/step/0000"
    assert record["observed_result"] == {"id": "ch_y"}
    assert "declared_at" in record
    assert "committed_at" in record

    validator_for("side_effect").validate(record)
    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_declare_then_kill_lands_intent_only(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        s.declare_side_effect(0, resource="db:row_x", action="delete")
        # Simulate kill arriving between declare and commit.
        aborted = s.abort_pending_side_effects("operator kill")
        assert len(aborted) == 1

    files = sorted((out / "side_effects").glob("*.json"))
    record = json.loads(files[0].read_text())
    assert record["status"] == "aborted"
    assert record["abort_reason"] == "operator kill"
    assert "aborted_at" in record


def test_commit_unknown_side_effect_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="unknown side_effect_id"):
        s.commit_side_effect("se_does_not_exist")


def test_double_commit_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        sid = s.declare_side_effect(0, resource="x", action="y")
        s.commit_side_effect(sid)
        with pytest.raises(ValueError, match="already 'committed'"):
            s.commit_side_effect(sid)


def test_invalid_reversibility_raises(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s, pytest.raises(ValueError, match="reversibility must be"):
        s.declare_side_effect(0, resource="x", action="y", reversibility="kinda")


def test_observed_result_redacted(tmp_path: Path) -> None:
    """Redaction policy applies to observed_result (PII may live there)."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
        sid = s.declare_side_effect(0, resource="api:x", action="POST")
        s.commit_side_effect(
            sid,
            observed_result={
                "email": "user@example.com",
                "ok": True,
                "token": "leaked",
            },
        )

    record = json.loads(next((out / "side_effects").glob("*.json")).read_text())
    result = record["observed_result"]
    # email gets regex-redacted to ***REDACTED:email***
    assert "@example.com" not in result["email"]
    # token key masks via mask_keys
    assert result["token"].startswith("***REDACTED")


def test_streaming_post_side_effect_called(tmp_path: Path) -> None:
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

        def post_side_effect(self, r: dict[str, Any]) -> None:
            calls.append(r)

    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s._stream = FakeSink()  # type: ignore[assignment]
        s.record_step(_step(0))
        sid = s.declare_side_effect(0, resource="x", action="y")
        s.commit_side_effect(sid)

    # One post on declare, one on commit.
    assert len(calls) == 2
    assert calls[0]["status"] == "intent_only"
    assert calls[1]["status"] == "committed"


def test_no_side_effects_no_directory(tmp_path: Path) -> None:
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        s.record_step(_step(0))
    assert not (out / "side_effects").exists()


def test_declare_before_step_allowed(tmp_path: Path) -> None:
    """Declare can land before record_step — step_id is then absent."""
    out = tmp_path / "b"
    with DebugSession(
        run_id="r", client_name="t", capture_mode=CaptureMode.METADATA, out_dir=out
    ) as s:
        sid = s.declare_side_effect(0, resource="x", action="y")
        s.commit_side_effect(sid)

    record = json.loads(next((out / "side_effects").glob("*.json")).read_text())
    assert record["status"] == "committed"
    assert "step_id" not in record
