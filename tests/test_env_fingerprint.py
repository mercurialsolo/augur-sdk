"""Environment fingerprint on observation/step (#13)."""

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
        "step_id": f"run/step/{idx:04d}",
        "step_index": idx,
        "intent": "click login",
        "step_type": "click",
        "required": True,
        "status": "succeeded",
        "started_at": "2026-05-19T00:00:00Z",
    }


def test_attach_env_fingerprint_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_e",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.attach_env_fingerprint(
            0,
            url_host="example.com",
            url_path_template="/users/:id",
            viewport_hash="abc12345",
            dom_hash="dom-abc",
            api_shapes={"stripe": "shape-abc"},
            extensions=["ublock"],
        )

    step = json.loads((out / "steps" / "0000.json").read_text())
    env = step["env_fingerprint"]
    assert env["url_host"] == "example.com"
    assert env["url_path_template"] == "/users/:id"
    assert env["viewport_hash"] == "abc12345"
    assert env["dom_hash"] == "dom-abc"
    assert env["api_shapes"] == {"stripe": "shape-abc"}
    assert env["extensions"] == ["ublock"]
    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)


def test_attach_env_fingerprint_merges(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_e",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
        s.attach_env_fingerprint(0, url_host="example.com")
        s.attach_env_fingerprint(0, dom_hash="dom-xyz")

    step = json.loads((out / "steps" / "0000.json").read_text())
    env = step["env_fingerprint"]
    assert env["url_host"] == "example.com"
    assert env["dom_hash"] == "dom-xyz"


def test_attach_env_fingerprint_no_step_raises(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_e",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s, pytest.raises(ValueError, match="no step at step_index"):
        s.attach_env_fingerprint(5, url_host="x")


def test_observation_with_env_fingerprint_validates() -> None:
    obs = {
        "artifact": "screenshots/0000_pre.png",
        "media_type": "image/png",
        "width": 100,
        "height": 100,
        "coordinate_space": "viewport_css_px",
        "env_fingerprint": {
            "url_host": "example.com",
            "url_path_template": "/users/:id",
            "viewport_hash": "abc",
        },
    }
    validator_for("observation").validate(obs)


def test_backward_compat_step_without_env_fingerprint_validates(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_e",
        client_name="t",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        s.record_step(_step(0))
    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)
