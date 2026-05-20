"""ModelApiAdapterBase (0.1.7) — behavioural coverage.

A subclass need only implement `iter_tool_calls`; the base handles
the DebugSession lifecycle, sidecar screenshot resolution, and step
construction.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from augur_sdk import ModelApiAdapterBase
from augur_sdk.validation import validate_bundle


def _png_bytes() -> bytes:
    # 1x1 transparent PNG.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
        "426082"
    )


class _StubAdapter(ModelApiAdapterBase):
    name = "stub"

    def iter_tool_calls(
        self, messages: list[dict[str, Any]]
    ) -> Iterator[tuple[int, int, dict[str, Any]]]:
        for turn_idx, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                continue
            for tc_idx, tc in enumerate(msg.get("tool_calls", [])):
                yield (turn_idx, tc_idx, tc["action"])


def _write_input(
    tmp_path: Path, *, with_screens: bool = True, run_id: str = "stub_run_1"
) -> Path:
    """Write a minimal messages.json + optional sidecar screenshots."""
    messages = [
        {"role": "user", "content": "Open the login page and click Sign in."},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Clicking Sign in at (100, 200)."}],
            "tool_calls": [
                {
                    "type": "computer_use_preview",
                    "action": {
                        "type": "click",
                        "params": {"x": 100, "y": 200},
                        "coordinate_space": "viewport_css_px",
                        "dispatch_backend": "stub",
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": "Now scrolling to find the submit button.",
            "tool_calls": [
                {
                    "type": "computer_use_preview",
                    "action": {
                        "type": "scroll",
                        "params": {"x": 0, "y": 400},
                        "coordinate_space": "viewport_css_px",
                        "dispatch_backend": "stub",
                    },
                }
            ],
        },
    ]
    input_file = tmp_path / "messages.json"
    input_file.write_text(
        json.dumps(
            {
                "messages": messages,
                "metadata": {
                    "run_id": run_id,
                    "client_version": "0.0.1",
                    "started_at": "2026-05-20T00:00:00Z",
                },
            }
        )
    )
    if with_screens:
        screens = tmp_path / "screens"
        screens.mkdir()
        for i in range(2):
            (screens / f"{i:04d}_pre.png").write_bytes(_png_bytes())
            (screens / f"{i:04d}_post.png").write_bytes(_png_bytes())
    return input_file


def test_bundle_from_input_produces_valid_bundle(tmp_path) -> None:
    input_file = _write_input(tmp_path)
    out_dir = tmp_path / "bundle"

    result = _StubAdapter().bundle_from_input(input_file, out_dir)

    assert result == out_dir
    issues = validate_bundle(out_dir)
    assert issues == [], "\n".join(i.render() for i in issues)

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["bundle_format"] == "augur-bundle"
    assert manifest["step_count"] == 2

    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["action"]["type"] == "click"
    assert step0["action"]["params"] == {"x": 100, "y": 200}
    assert step0["grounding"]["provider"] == "stub"
    assert step0["grounding"]["provenance"] == "screenshot"
    assert step0["verdict"] == {"status": "unknown", "reason": "no native verifier"}


def test_intent_extracted_from_assistant_text_block(tmp_path) -> None:
    input_file = _write_input(tmp_path)
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_file, out_dir)

    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["intent"].startswith("Clicking Sign in")


def test_intent_extracted_from_string_content(tmp_path) -> None:
    input_file = _write_input(tmp_path)
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_file, out_dir)

    step1 = json.loads((out_dir / "steps" / "0001.json").read_text())
    assert "scrolling to find" in step1["intent"]


def test_screenshots_resolved_when_present(tmp_path) -> None:
    input_file = _write_input(tmp_path, with_screens=True)
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_file, out_dir)

    assert (out_dir / "screenshots" / "0000_pre.png").exists()
    assert (out_dir / "screenshots" / "0000_post.png").exists()
    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["observation_pre"] is not None
    assert step0["observation_post"] is not None


def test_screenshots_omitted_when_sidecar_dir_missing(tmp_path) -> None:
    input_file = _write_input(tmp_path, with_screens=False)
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_file, out_dir)

    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["observation_pre"] is None
    assert step0["observation_post"] is None
    assert not (out_dir / "screenshots").exists()


def test_run_id_resolution_prefers_explicit_kwarg(tmp_path) -> None:
    input_file = _write_input(tmp_path, run_id="from_metadata")
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_file, out_dir, run_id="explicit_override")

    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["step_id"].startswith("explicit_override/step/")


def test_run_id_falls_back_to_metadata(tmp_path) -> None:
    input_file = _write_input(tmp_path, run_id="from_metadata")
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_file, out_dir)

    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["step_id"].startswith("from_metadata/step/")


def test_input_dir_picks_first_json(tmp_path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    # Two files; sorted picks alphabetical first.
    (input_dir / "001_first.json").write_text(
        json.dumps({"messages": [], "metadata": {"run_id": "alpha"}})
    )
    (input_dir / "002_later.json").write_text(
        json.dumps({"messages": [], "metadata": {"run_id": "beta"}})
    )
    out_dir = tmp_path / "bundle"
    _StubAdapter().bundle_from_input(input_dir, out_dir)

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["run_id"] == "alpha"


def test_input_dir_raises_when_no_json(tmp_path) -> None:
    input_dir = tmp_path / "empty"
    input_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="no .json"):
        _StubAdapter().bundle_from_input(input_dir, tmp_path / "bundle")


def test_subclass_can_override_grounding_provider(tmp_path) -> None:
    class _OpenAIish(_StubAdapter):
        name = "openai-cua"

        def grounding_provider(self) -> str:
            return "openai.computer_use_preview"

    input_file = _write_input(tmp_path)
    out_dir = tmp_path / "bundle"
    _OpenAIish().bundle_from_input(input_file, out_dir)

    step0 = json.loads((out_dir / "steps" / "0000.json").read_text())
    assert step0["grounding"]["provider"] == "openai.computer_use_preview"
