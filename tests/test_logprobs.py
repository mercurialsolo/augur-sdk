"""Per-token logprob capture in modelio.response — augur-sdk#40.

Unlocks PPO / GRPO and efficient DPO training off Augur-captured
bundles. Per-token logprobs are off by default (they roughly double
the OpenAI response payload size and add a small cost on some
providers); producers opt in via `DebugSession(capture_logprobs=True)`.

Pins:
- Session-level opt-in flag round-trips through the constructor and
  surfaces on `session.capture_logprobs`.
- When `capture_logprobs=True` and the producer didn't stamp anything,
  `record_modelio` defaults `response.logprobs` to `[]` so consumers
  can tell "requested but empty" from "not requested" (absent / null).
- The vendor mapping helper produces the canonical
  `[{token, token_id, logprob, top_alternatives}]` shape for both
  OpenAI- and Anthropic-shaped responses.
- Records carrying canonical logprobs validate against
  `augur-schema 0.3.3`'s `modelio.schema.json#response.logprobs`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from augur_schema import validator_for

from augur_sdk import CaptureMode, DebugSession
from augur_sdk.model_api_adapter import ModelApiAdapterBase

# ── Session opt-in flag ──────────────────────────────────────────────


def test_capture_logprobs_defaults_off(tmp_path: Path) -> None:
    session = DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=tmp_path / "bundle",
    )
    assert session.capture_logprobs is False


def test_capture_logprobs_constructor_kwarg_round_trips(tmp_path: Path) -> None:
    session = DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=tmp_path / "bundle",
        capture_logprobs=True,
    )
    assert session.capture_logprobs is True


# ── record_modelio behaviour ─────────────────────────────────────────


def _minimal_modelio(**response_extras: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "text": "ok",
        "stop_reason": "end_turn",
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    response.update(response_extras)
    return {
        "schema_version": "0.1",
        "layer": "model",
        "ts": "2026-05-25T00:00:00Z",
        "request": {
            "model": "claude-sonnet-4-7-20260120",
            "messages": [{"role": "user", "content": "hi"}],
        },
        "response": response,
    }


def test_record_modelio_no_opt_in_leaves_logprobs_absent(tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
    ) as s:
        relpath = s.record_modelio(_minimal_modelio(), step_index=0)

    record = json.loads((out / relpath).read_text())
    assert "logprobs" not in record["response"]


def test_record_modelio_opt_in_with_no_data_emits_empty_array(
    tmp_path: Path,
) -> None:
    """The contract: `capture_logprobs=True` + producer didn't stamp
    anything → `response.logprobs = []` so consumers can tell
    "requested but empty" from "not requested" (absent)."""
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        capture_logprobs=True,
    ) as s:
        relpath = s.record_modelio(_minimal_modelio(), step_index=0)

    record = json.loads((out / relpath).read_text())
    assert record["response"]["logprobs"] == []


def test_record_modelio_opt_in_preserves_producer_logprobs(
    tmp_path: Path,
) -> None:
    """Producers that DID receive logprobs put them on
    response.logprobs themselves — the SDK doesn't overwrite them."""
    out = tmp_path / "bundle"
    canonical = [
        {"token": "Hello", "logprob": -0.12},
        {"token": " world", "logprob": -0.05},
    ]
    with DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        capture_logprobs=True,
    ) as s:
        relpath = s.record_modelio(
            _minimal_modelio(logprobs=canonical), step_index=0
        )

    record = json.loads((out / relpath).read_text())
    assert record["response"]["logprobs"] == canonical


def test_record_modelio_opt_in_preserves_null_logprobs(tmp_path: Path) -> None:
    """Producer explicitly stamped null (vendor doesn't surface
    logprobs); SDK doesn't promote null → empty."""
    out = tmp_path / "bundle"
    with DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        capture_logprobs=True,
    ) as s:
        relpath = s.record_modelio(
            _minimal_modelio(logprobs=None), step_index=0
        )

    record = json.loads((out / relpath).read_text())
    assert record["response"]["logprobs"] is None


def test_canonical_logprobs_validate_against_schema(tmp_path: Path) -> None:
    """End-to-end: a modelio record carrying canonical logprobs
    validates against augur-schema 0.3.3."""
    out = tmp_path / "bundle"
    logprobs = [
        {
            "token": "Hello",
            "token_id": 9906,
            "logprob": -0.12,
            "top_alternatives": [
                {"token": "Hi", "logprob": -1.5},
                {"token": "Hey", "logprob": -2.1},
            ],
        },
        {"token": " world", "logprob": -0.05},
    ]
    with DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        capture_logprobs=True,
    ) as s:
        s.record_modelio(_minimal_modelio(logprobs=logprobs), step_index=0)

    record = json.loads(
        (out / "modelio" / "0000-model-0.json").read_text()
    )
    # The SDK's own validator already ran on close; double-check
    # against the live schema validator for the explicit assertion.
    validator_for("modelio").validate(record)
    assert record["response"]["logprobs"][0]["top_alternatives"][0]["token"] == "Hi"


# ── Vendor mapping helper ────────────────────────────────────────────


def test_extract_logprobs_openai_shape() -> None:
    response = {
        "choices": [
            {
                "logprobs": {
                    "content": [
                        {
                            "token": "Hello",
                            "logprob": -0.12,
                            "bytes": [72, 101, 108, 108, 111],
                            "top_logprobs": [
                                {"token": "Hi", "logprob": -1.5},
                                {"token": "Hey", "logprob": -2.1},
                            ],
                        },
                        {"token": " world", "logprob": -0.05},
                    ]
                }
            }
        ]
    }

    logprobs = ModelApiAdapterBase.extract_logprobs_from_response(response)

    assert logprobs is not None
    assert logprobs == [
        {
            "token": "Hello",
            "logprob": -0.12,
            "top_alternatives": [
                {"token": "Hi", "logprob": -1.5},
                {"token": "Hey", "logprob": -2.1},
            ],
        },
        {"token": " world", "logprob": -0.05},
    ]
    # Round-trip through the schema validator on a synthetic record.
    validator_for("modelio").validate(
        {
            "schema_version": "0.1",
            "layer": "model",
            "ts": "2026-05-25T00:00:00Z",
            "request": {"model": "gpt-5"},
            "response": {"logprobs": logprobs},
        }
    )


def test_extract_logprobs_anthropic_shape() -> None:
    response = {
        "content": [
            {
                "type": "text",
                "text": "Hello world",
                "logprobs": [
                    {
                        "token": "Hello",
                        "logprob": -0.18,
                        "top_logprobs": [
                            {"token": "Hi", "logprob": -1.9},
                        ],
                    },
                    {"token": " world", "logprob": -0.07},
                ],
            }
        ]
    }

    logprobs = ModelApiAdapterBase.extract_logprobs_from_response(response)

    assert logprobs is not None
    assert logprobs == [
        {
            "token": "Hello",
            "logprob": -0.18,
            "top_alternatives": [{"token": "Hi", "logprob": -1.9}],
        },
        {"token": " world", "logprob": -0.07},
    ]
    validator_for("modelio").validate(
        {
            "schema_version": "0.1",
            "layer": "model",
            "ts": "2026-05-25T00:00:00Z",
            "request": {"model": "claude-sonnet-4-7"},
            "response": {"logprobs": logprobs},
        }
    )


def test_extract_logprobs_missing_returns_none() -> None:
    """A response with no recognisable logprob block → None."""
    response = {"text": "Hello", "stop_reason": "end_turn"}
    assert ModelApiAdapterBase.extract_logprobs_from_response(response) is None


def test_extract_logprobs_openai_empty_choices_returns_none() -> None:
    """Edge case: choices exists but is empty → None."""
    assert (
        ModelApiAdapterBase.extract_logprobs_from_response({"choices": []})
        is None
    )


def test_extract_logprobs_openai_top_logprobs_zero_returns_no_alternatives() -> None:
    """When OpenAI is called with top_logprobs=0, each entry has
    `top_logprobs: []` — we drop the field entirely rather than emit
    an empty alternatives list."""
    response = {
        "choices": [
            {
                "logprobs": {
                    "content": [
                        {"token": "Hi", "logprob": -0.5, "top_logprobs": []},
                    ]
                }
            }
        ]
    }
    logprobs = ModelApiAdapterBase.extract_logprobs_from_response(response)
    assert logprobs == [{"token": "Hi", "logprob": -0.5}]


def test_redaction_preserves_logprob_token_text(tmp_path: Path) -> None:
    """The default redaction policy masks bare `token` keys (intended
    for API/bearer tokens). Logprob entries carry `token` as decoded
    model output — context-aware carve-out keeps the training signal
    intact while the generic rule still defends elsewhere."""
    out = tmp_path / "bundle"
    canonical = [
        {"token": "Hello", "logprob": -0.12, "token_id": 9906},
        {"token": " world", "logprob": -0.05},
    ]
    with DebugSession(
        run_id="run_lp",
        client_name="testclient",
        capture_mode=CaptureMode.METADATA,
        out_dir=out,
        capture_logprobs=True,
    ) as s:
        relpath = s.record_modelio(
            _minimal_modelio(logprobs=canonical), step_index=0
        )
    record = json.loads((out / relpath).read_text())
    assert record["response"]["logprobs"][0]["token"] == "Hello"
    assert record["response"]["logprobs"][0]["token_id"] == 9906


def test_extract_logprobs_preserves_token_id_when_present() -> None:
    """If a vendor (e.g. vLLM via OpenAI-compatible mode) surfaces
    token_id, we pass it through. Most providers leave it null."""
    response = {
        "choices": [
            {
                "logprobs": {
                    "content": [
                        {
                            "token": "Hello",
                            "token_id": 9906,
                            "logprob": -0.1,
                            "top_logprobs": [
                                {"token": "Hi", "token_id": 13347, "logprob": -1.2},
                            ],
                        },
                    ]
                }
            }
        ]
    }
    logprobs = ModelApiAdapterBase.extract_logprobs_from_response(response)
    assert logprobs == [
        {
            "token": "Hello",
            "token_id": 9906,
            "logprob": -0.1,
            "top_alternatives": [
                {"token": "Hi", "token_id": 13347, "logprob": -1.2},
            ],
        }
    ]
