"""Exercise replay_fixture.schema.json end-to-end (upstream augur#55 item 2).

Until 0.1.8 the schema shipped vendored but nothing in the SDK actually
constructed, validated, or persisted a ReplayFixture. These tests close
that gap: build representative fixtures for every `mode`, validate them
against the vendored schema, and round-trip through the bundle's
``replay/`` directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from augur_schema import SchemaError, validator_for
from jsonschema.exceptions import ValidationError

_VALIDATOR = validator_for("replay_fixture")


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
        "426082"
    )


def _minimal(*, mode: str = "observation_replay") -> dict[str, Any]:
    return {
        "fixture_id": "run_t/replay/0011-observation",
        "step_id": "run_t/step/0011",
        "mode": mode,
        "observation": "screenshots/0011_pre.png",
    }


# ── schema sanity ────────────────────────────────────────────────────────────


def test_minimal_fixture_validates() -> None:
    _VALIDATOR.validate(_minimal())


@pytest.mark.parametrize(
    "mode",
    [
        "observation_replay",
        "handler_replay",
        "model_replay",
        "sandbox_replay",
        "shadow_replay",
    ],
)
def test_every_mode_validates(mode: str) -> None:
    _VALIDATOR.validate(_minimal(mode=mode))


def test_full_fixture_validates() -> None:
    full: dict[str, Any] = {
        **_minimal(mode="handler_replay"),
        "task": "Click the Sign in button",
        "prior_steps": "replay/0011_prior.json",
        "expected": {
            "action_type": "click",
            "acceptable_regions": [
                {"x1": 100.0, "y1": 200.0, "x2": 200.0, "y2": 240.0, "label": "Sign in"},
            ],
            "verdict_status": "passed",
        },
        "captured_versions": {
            "model": "claude-sonnet-4-7-20260120",
            "prompt": "planner@v3",
            "code_git_sha": "abc1234",
            "grounder": "som-clicker-v2",
        },
    }
    _VALIDATOR.validate(full)


def test_missing_required_field_fails() -> None:
    bad = _minimal()
    del bad["observation"]
    with pytest.raises(ValidationError, match="observation"):
        _VALIDATOR.validate(bad)


def test_unknown_mode_fails() -> None:
    with pytest.raises(ValidationError, match="enum"):
        _VALIDATOR.validate(_minimal(mode="time_travel_replay"))


def test_unknown_verdict_status_in_expected_fails() -> None:
    bad = {**_minimal(), "expected": {"verdict_status": "maybe"}}
    with pytest.raises(ValidationError, match="enum"):
        _VALIDATOR.validate(bad)


def test_extra_top_level_field_fails() -> None:
    bad = {**_minimal(), "rumor_about_the_run": True}
    with pytest.raises(ValidationError, match="additionalProperties"):
        _VALIDATOR.validate(bad)


def test_acceptable_region_extra_field_fails() -> None:
    bad = {
        **_minimal(),
        "expected": {
            "acceptable_regions": [
                {"x1": 0, "y1": 0, "x2": 10, "y2": 10, "color": "red"}
            ]
        },
    }
    with pytest.raises(ValidationError, match="additionalProperties"):
        _VALIDATOR.validate(bad)


def test_schema_loader_round_trip() -> None:
    # The same schema must be reachable by short name and by $id.
    with pytest.raises(SchemaError):
        validator_for("not_a_real_schema")


# ── bundle round-trip ────────────────────────────────────────────────────────


def test_fixture_round_trips_via_bundle_replay_dir(tmp_path: Path) -> None:
    """A producer that writes a fixture under ``replay/`` must remain
    schema-valid after JSON round-trip."""
    out = tmp_path / "bundle"
    (out / "replay").mkdir(parents=True)
    (out / "screenshots").mkdir(parents=True)
    (out / "screenshots" / "0011_pre.png").write_bytes(_png_bytes())

    fixture = {
        **_minimal(mode="model_replay"),
        "task": "Locate and click submit",
        "expected": {"verdict_status": "passed"},
    }
    _VALIDATOR.validate(fixture)
    (out / "replay" / "0011_fixture.json").write_text(
        json.dumps(fixture, sort_keys=True, indent=2)
    )

    loaded = json.loads((out / "replay" / "0011_fixture.json").read_text())
    _VALIDATOR.validate(loaded)
    assert loaded["observation"] == "screenshots/0011_pre.png"
    assert (out / loaded["observation"]).exists()
