"""End-to-end: synthetic run writes a valid bundle (issue #6 exit criterion)."""

from __future__ import annotations

import json

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.validation import validate_bundle


def _png_bytes() -> bytes:
    # 1x1 transparent PNG — smallest valid PNG.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
        "426082"
    )


def test_synthetic_run_writes_valid_bundle(tmp_path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_test",
        client_name="testclient",
        client_version="0.0.0",
        capture_mode=CaptureMode.SCREENSHOTS,
        out_dir=out,
    ) as session:
        pre = session.attach_observation(step_index=0, kind="pre", png_bytes=_png_bytes())
        post = session.attach_observation(step_index=0, kind="post", png_bytes=_png_bytes())
        session.record_step(
            {
                "step_id": "run_test/step/0000",
                "step_index": 0,
                "intent": "Click login",
                "step_type": "click",
                "required": True,
                "status": "succeeded",
                "started_at": "2026-05-19T00:00:00Z",
                "ended_at": "2026-05-19T00:00:01Z",
                "duration_ms": 1000,
                "observation_pre": pre,
                "observation_post": post,
                "action": {
                    "type": "click",
                    "params": {"x": 100, "y": 200},
                    "coordinate_space": "viewport_css_px",
                    "dispatch_backend": "cdp",
                },
                "grounding": {
                    "provider": "test",
                    "target_label": "Login",
                    "coordinates": {"x": 100, "y": 200},
                    "confidence": 0.9,
                    "evidence": "test",
                    "provenance": "screenshot",
                },
                "verdict": {"status": "passed", "reason": "visible state change"},
            }
        )
        session.record_event(
            {
                "ts": "2026-05-19T00:00:00.500Z",
                "step_index": 0,
                "layer": "model",
                "kind": "decision",
                "summary": "selected Login button",
            }
        )

    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["bundle_format"] == "augur-bundle"
    assert manifest["step_count"] == 1
    assert manifest["paths"]["steps"] == "steps/"
    assert manifest["paths"]["agent"] == "AGENT.md"
    assert manifest["paths"]["schema"] == "schema/"
    assert (out / "screenshots" / "0000_pre.png").exists()
    assert (out / "steps" / "0000.json").exists()
    assert (out / "events" / "0000.jsonl").exists()
    # Agent-oriented additions:
    agent_md = (out / "AGENT.md").read_text()
    assert "Augur bundle" in agent_md
    assert "Suggested first reads" in agent_md
    assert (out / "schema" / "manifest.schema.json").exists()
    assert (out / "schema" / "step_trace.schema.json").exists()


def test_off_mode_writes_envelope_only(tmp_path) -> None:
    out = tmp_path / "off"
    with DebugSession(
        run_id="run_off",
        client_name="testclient",
        capture_mode=CaptureMode.OFF,
        out_dir=out,
    ) as session:
        # These calls are allowed but produce no on-disk artifacts.
        session.record_event(
            {
                "ts": "2026-05-19T00:00:00Z",
                "layer": "runner",
                "kind": "info",
                "summary": "ignored",
            }
        )

    issues = validate_bundle(out)
    assert issues == [], "\n".join(i.render() for i in issues)
    assert (out / "manifest.json").exists()
    assert not (out / "events").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["capture_mode"] == "off"
    assert manifest["step_count"] == 0
