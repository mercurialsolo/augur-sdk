"""cua.dom_used_as_runtime_target (0.1.5) — behavioural coverage.

The rule fires when a step's grounding.provenance == "dom" AND
action.params carries numeric x/y — runtime click targets must be
screenshot-grounded (Spec §4); DOM probes are diagnostic-only.
"""

from __future__ import annotations

from typing import Any

from augur_sdk.diagnostics.engine import RuleResult
from augur_sdk.diagnostics.packs.cua import dom_used_as_runtime_target


class _Ctx:
    """Minimal BundleContext stand-in — the rule only reads `.steps`."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self.steps = steps


def _step(
    idx: int,
    *,
    provenance: str | None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s: dict[str, Any] = {"step_index": idx, "intent": f"step {idx}"}
    if provenance is not None:
        s["grounding"] = {"provenance": provenance}
    if params is not None:
        s["action"] = {"type": "click", "params": params}
    return s


def _run(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    r = RuleResult()
    dom_used_as_runtime_target(_Ctx(steps), r)  # type: ignore[arg-type]
    return list(r.findings)


def test_fires_when_dom_grounded_with_xy() -> None:
    findings = _run([_step(3, provenance="dom", params={"x": 120, "y": 250})])
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "cua.dom_used_as_runtime_target"
    assert findings[0]["severity"] == "high"
    assert findings[0]["step_index"] == 3
    assert "120" in findings[0]["summary"] and "250" in findings[0]["summary"]
    assert findings[0]["evidence"] == [{"type": "step", "ref": "steps/0003.json"}]


def test_accepts_float_coordinates() -> None:
    findings = _run([_step(0, provenance="dom", params={"x": 12.5, "y": 33.0})])
    assert len(findings) == 1


def test_does_not_fire_for_screenshot_grounded() -> None:
    findings = _run(
        [_step(0, provenance="screenshot", params={"x": 100, "y": 200})]
    )
    assert findings == []


def test_does_not_fire_when_action_has_no_xy() -> None:
    findings = _run([_step(0, provenance="dom", params={"text": "hello"})])
    assert findings == []


def test_does_not_fire_when_xy_non_numeric() -> None:
    findings = _run(
        [_step(0, provenance="dom", params={"x": "120", "y": "250"})]
    )
    assert findings == []


def test_does_not_fire_when_no_action_or_grounding() -> None:
    findings = _run(
        [
            {"step_index": 0, "intent": "no fields"},
            _step(1, provenance=None, params={"x": 1, "y": 2}),
            _step(2, provenance="dom", params=None),
        ]
    )
    assert findings == []


def test_fires_independently_per_step() -> None:
    findings = _run(
        [
            _step(0, provenance="dom", params={"x": 1, "y": 2}),
            _step(1, provenance="screenshot", params={"x": 1, "y": 2}),
            _step(2, provenance="dom", params={"x": 3, "y": 4}),
        ]
    )
    assert sorted(f["step_index"] for f in findings) == [0, 2]
