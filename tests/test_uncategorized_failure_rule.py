"""cua.uncategorized_failure (0.1.4) — behavioural coverage.

The rule fires on `status == "failed"` AND `failure_class` is missing
or the literal string "unknown". Anything else is a non-fire.
"""

from __future__ import annotations

from typing import Any

from augur_sdk.diagnostics.engine import RuleResult
from augur_sdk.diagnostics.packs.cua import uncategorized_failure


class _Ctx:
    """Minimal BundleContext stand-in — the rule only reads `.steps`."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self.steps = steps


def _step(idx: int, *, status: str, failure_class: Any = ...) -> dict[str, Any]:
    s: dict[str, Any] = {
        "step_index": idx,
        "intent": f"step {idx}",
        "status": status,
    }
    if failure_class is not ...:
        s["failure_class"] = failure_class
    return s


def _run(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    r = RuleResult()
    uncategorized_failure(_Ctx(steps), r)  # type: ignore[arg-type]
    return list(r.findings)


def test_fires_when_failed_with_no_failure_class() -> None:
    findings = _run([_step(0, status="failed")])
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "cua.uncategorized_failure"
    assert findings[0]["severity"] == "low"
    assert findings[0]["step_index"] == 0
    assert findings[0]["evidence"] == [{"type": "step", "ref": "steps/0000.json"}]
    assert "failure-class-taxonomy" in findings[0]["recommendation"]


def test_fires_when_failed_with_literal_unknown() -> None:
    findings = _run([_step(2, status="failed", failure_class="unknown")])
    assert len(findings) == 1
    assert findings[0]["step_index"] == 2


def test_does_not_fire_when_failed_with_known_class() -> None:
    findings = _run(
        [_step(0, status="failed", failure_class="no_state_change")]
    )
    assert findings == []


def test_does_not_fire_on_non_failed_status() -> None:
    findings = _run(
        [
            _step(0, status="succeeded"),
            _step(1, status="skipped"),
            _step(2, status="recovered", failure_class="unknown"),
        ]
    )
    assert findings == []


def test_fires_once_per_failing_step() -> None:
    findings = _run(
        [
            _step(0, status="succeeded"),
            _step(1, status="failed"),
            _step(2, status="failed", failure_class=""),
            _step(3, status="failed", failure_class="click_outside_viewport"),
            _step(4, status="failed", failure_class="unknown"),
        ]
    )
    assert sorted(f["step_index"] for f in findings) == [1, 2, 4]
