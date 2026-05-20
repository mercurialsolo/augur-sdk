"""Exercise prior_steps.schema.json end-to-end (issue #4, closes augur#55 gap).

Mirrors the pattern of test_replay_fixture_schema.py. The prior_steps
schema is a thin subset of step_trace (action + verdict + intent only)
that the replay workbench writes to ``replay/<step_index:04d>.prior.json``
so the agent under test sees the same context the original run had.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from augur_sdk._schema import ValidationError, validator_for

_VALIDATOR = validator_for("prior_steps")


def _minimal_item(step_index: int = 0) -> dict[str, Any]:
    return {
        "step_index": step_index,
        "action": {"type": "click"},
        "verdict": {"status": "passed"},
    }


# ── schema sanity ────────────────────────────────────────────────────────────


def test_empty_list_validates() -> None:
    _VALIDATOR.validate([])


def test_minimal_single_item_validates() -> None:
    _VALIDATOR.validate([_minimal_item()])


def test_full_item_validates() -> None:
    full: list[dict[str, Any]] = [
        {
            "step_index": 0,
            "intent": "Click Sign in",
            "action": {
                "type": "click",
                "params": {"x": 120, "y": 240},
                "coordinate_space": "viewport_css_px",
                "dispatch_backend": "cdp",
            },
            "verdict": {
                "status": "passed",
                "reason": "visible state change",
                "score": 0.95,
                "comparator": "verifier",
                "evidence_refs": ["screenshots/0000_post.png"],
            },
        },
        {
            "step_index": 1,
            "intent": None,
            "action": {"type": "scroll", "params": {"x": 0, "y": 400}},
            "verdict": {"status": "recoverable", "score": 0.5},
        },
    ]
    _VALIDATOR.validate(full)


@pytest.mark.parametrize(
    "missing",
    ["step_index", "action", "verdict"],
)
def test_required_field_missing_fails(missing: str) -> None:
    item = _minimal_item()
    del item[missing]
    with pytest.raises(ValidationError, match=missing):
        _VALIDATOR.validate([item])


def test_negative_step_index_fails() -> None:
    item = _minimal_item()
    item["step_index"] = -1
    with pytest.raises(ValidationError, match="minimum"):
        _VALIDATOR.validate([item])


def test_action_missing_type_fails() -> None:
    item = _minimal_item()
    item["action"] = {"params": {"x": 1}}
    with pytest.raises(ValidationError, match="type"):
        _VALIDATOR.validate([item])


def test_verdict_unknown_status_fails() -> None:
    item = _minimal_item()
    item["verdict"] = {"status": "maybe"}
    with pytest.raises(ValidationError, match="enum"):
        _VALIDATOR.validate([item])


def test_verdict_score_above_unit_fails() -> None:
    item = _minimal_item()
    item["verdict"] = {"status": "passed", "score": 1.5}
    with pytest.raises(ValidationError, match="maximum"):
        _VALIDATOR.validate([item])


def test_extra_top_level_item_field_fails() -> None:
    item = _minimal_item()
    item["rumor_about_the_step"] = True
    with pytest.raises(ValidationError, match="additionalProperties"):
        _VALIDATOR.validate([item])


# ── round-trip alongside replay/ fixture ────────────────────────────────────


def test_prior_steps_file_round_trips_alongside_replay_fixture(tmp_path: Path) -> None:
    """Producers writing replay/<idx>.prior.json must remain valid after
    JSON round-trip — the disk path is the contract surface, not just
    the in-memory object."""
    out = tmp_path / "bundle"
    (out / "replay").mkdir(parents=True)

    prior: list[dict[str, Any]] = [
        _minimal_item(0),
        {
            "step_index": 1,
            "intent": "Type username",
            "action": {"type": "type", "params": {"text": "alice"}},
            "verdict": {"status": "passed", "score": 1.0, "comparator": "verifier"},
        },
    ]
    _VALIDATOR.validate(prior)

    target = out / "replay" / "0002.prior.json"
    target.write_text(json.dumps(prior, sort_keys=True, indent=2))

    loaded = json.loads(target.read_text())
    _VALIDATOR.validate(loaded)
    assert [item["step_index"] for item in loaded] == [0, 1]


def test_short_name_registered_in_loader() -> None:
    """The acceptance criterion: validator_for('prior_steps') resolves."""
    v = validator_for("prior_steps")
    # Sanity: the validator carries the canonical $id.
    assert v.schema["$id"].endswith("/prior_steps.schema.json")
