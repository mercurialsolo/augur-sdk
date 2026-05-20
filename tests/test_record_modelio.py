"""DebugSession.record_modelio (0.1.8) — issue #2.

Producer-side helper for the canonical model-call record. Validates
against modelio.schema.json, stages under modelio/<step>-<layer>-<seq>.json,
and is idempotent on prompt_hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import CaptureMode, DebugSession


def _minimal_modelio(
    *, layer: str = "model", prompt_hash: str | None = None
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "schema_version": "0.1",
        "layer": layer,
        "ts": "2026-05-20T00:00:00Z",
        "request": {
            "model": "claude-sonnet-4-7-20260120",
            "messages": [{"role": "user", "content": "do the thing"}],
        },
        "response": {
            "text": "ok",
            "stop_reason": "end_turn",
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        },
    }
    if prompt_hash is not None:
        rec["prompt_hash"] = prompt_hash
    return rec


def _modelio_file(out: Path, relpath: str) -> dict[str, Any]:
    return json.loads((out / relpath).read_text())


def test_record_modelio_writes_under_modelio_dir(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        relpath = s.record_modelio(_minimal_modelio(layer="planner"), step_index=3)

    assert relpath == "modelio/0003-planner-0.json"
    assert (out / relpath).exists()
    record = _modelio_file(out, relpath)
    assert record["layer"] == "planner"
    assert record["request"]["model"] == "claude-sonnet-4-7-20260120"


def test_path_encodes_step_layer_and_seq(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        p1 = s.record_modelio(_minimal_modelio(layer="planner"), step_index=0)
        p2 = s.record_modelio(_minimal_modelio(layer="grounding"), step_index=0)
        p3 = s.record_modelio(_minimal_modelio(layer="planner"), step_index=0)  # 2nd planner
        p4 = s.record_modelio(_minimal_modelio(layer="planner"), step_index=1)
        p5 = s.record_modelio(_minimal_modelio(layer="planner"))  # run-scoped

    assert p1 == "modelio/0000-planner-0.json"
    assert p2 == "modelio/0000-grounding-0.json"
    assert p3 == "modelio/0000-planner-1.json"
    assert p4 == "modelio/0001-planner-0.json"
    assert p5 == "modelio/run-planner-0.json"


def test_layer_kwarg_stamped_when_missing_from_record(tmp_path) -> None:
    out = tmp_path / "bundle"
    rec = _minimal_modelio()
    del rec["layer"]
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        relpath = s.record_modelio(rec, layer="verifier", step_index=2)

    assert relpath == "modelio/0002-verifier-0.json"
    record = _modelio_file(out, relpath)
    assert record["layer"] == "verifier"


def test_idempotent_on_prompt_hash(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        p1 = s.record_modelio(_minimal_modelio(prompt_hash="abc123"), step_index=0)
        p2 = s.record_modelio(_minimal_modelio(prompt_hash="abc123"), step_index=0)
        p3 = s.record_modelio(_minimal_modelio(prompt_hash="abc123"), step_index=99)

    # All three return the same path; only one file on disk.
    assert p1 == p2 == p3
    files = sorted((out / "modelio").glob("*.json"))
    assert len(files) == 1


def test_validates_payload_by_default(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        bad = _minimal_modelio()
        bad["layer"] = "not-a-valid-layer"
        with pytest.raises(ValueError, match="modelio.schema.json"):
            s.record_modelio(bad, step_index=0)


def test_validate_false_skips_schema_check(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        bad = _minimal_modelio()
        bad["layer"] = "not-a-valid-layer"
        relpath = s.record_modelio(bad, step_index=0, validate=False)

    assert (out / relpath).exists()


def test_three_call_round_trip_validates(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_modelio(_minimal_modelio(layer="planner"), step_index=0)
        s.record_modelio(_minimal_modelio(layer="grounding"), step_index=0)
        s.record_modelio(_minimal_modelio(layer="verifier"), step_index=0)

    # All three on disk, all valid.
    from augur_sdk._schema import validator_for

    val = validator_for("modelio")
    files = sorted((out / "modelio").glob("*.json"))
    assert len(files) == 3
    for f in files:
        val.validate(json.loads(f.read_text()))


def test_redaction_applied_to_modelio_payload(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_m",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        # Default redaction policy masks 'token' and similar fields.
        rec = _minimal_modelio()
        rec["request"]["params"] = {"token": "secret-bearer-xyz"}
        relpath = s.record_modelio(rec, step_index=0)

    written = _modelio_file(out, relpath)
    assert written["request"]["params"]["token"] != "secret-bearer-xyz"
    assert written.get("redaction_applied") is True
