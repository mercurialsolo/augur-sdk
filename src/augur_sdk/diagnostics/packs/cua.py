"""Generic CUA diagnostic rules (spec §15).

Each rule is a function decorated with @rule(id, severity=...). Rules emit
findings with at least one evidence reference.

The set tracks the generic checks in spec §15. Mantis-specific rules live in
the mantis adapter package.
"""

from __future__ import annotations

from typing import Any

from augur_sdk.diagnostics.engine import BundleContext, Rule, RuleResult, rule
from augur_sdk.models import DiagnosticEvidence

# --- helpers ---


def _action_coords(step: dict[str, Any]) -> tuple[float, float] | None:
    action = step.get("action") or {}
    params = action.get("params") or {}
    if "x" in params and "y" in params:
        return float(params["x"]), float(params["y"])
    return None


def _step_evidence(step: dict[str, Any]) -> DiagnosticEvidence:
    idx = step.get("step_index", 0)
    return {"type": "step", "ref": f"steps/{idx:04d}.json"}


def _events_evidence(idx: int) -> DiagnosticEvidence:
    return {"type": "event", "ref": f"events/{idx:04d}.jsonl"}


# --- rules ---


@rule("cua.repeated_action_stable_frame", severity="medium")
def repeated_action_stable_frame(ctx: BundleContext, r: RuleResult) -> None:
    """Two consecutive steps with the same action coordinates and no observed
    state change. Spec §15 ("repeated action with stable frame")."""
    prev: dict[str, Any] | None = None
    for step in ctx.steps:
        cur_coords = _action_coords(step)
        if prev is not None:
            prev_coords = _action_coords(prev)
            if (
                cur_coords is not None
                and prev_coords is not None
                and cur_coords == prev_coords
                and step.get("failure_class") in ("no_state_change", None)
                and prev.get("failure_class") in ("no_state_change", None)
            ):
                r.emit(
                    rule_id=repeated_action_stable_frame.rule_id,
                    severity=repeated_action_stable_frame.severity,
                    summary=(
                        f"Steps {prev['step_index']} and {step['step_index']} "
                        f"clicked the same coordinates with no state change."
                    ),
                    evidence=[_step_evidence(prev), _step_evidence(step)],
                    step_index=step["step_index"],
                    recommendation=(
                        "Inspect grounding provenance and SoM coordinate space "
                        "before retrying with the same target."
                    ),
                )
        prev = step


@rule("cua.click_outside_viewport", severity="high")
def click_outside_viewport(ctx: BundleContext, r: RuleResult) -> None:
    """Action coordinate falls outside the captured viewport.

    Compares action coords (viewport_css_px) against the pre-observation
    viewport if we can read it from `trace.json`. We can't read PNG metadata
    without a dependency, so we rely on the observation being declared.
    """
    for step in ctx.steps:
        coords = _action_coords(step)
        action = step.get("action") or {}
        if coords is None or action.get("coordinate_space") != "viewport_css_px":
            continue
        viewport = _step_viewport(step)
        if viewport is None:
            continue
        w, h = viewport
        x, y = coords
        if x < 0 or y < 0 or x > w or y > h:
            r.emit(
                rule_id=click_outside_viewport.rule_id,
                severity=click_outside_viewport.severity,
                summary=(
                    f"Step {step['step_index']} action at ({x},{y}) is outside "
                    f"the {w}x{h} viewport."
                ),
                evidence=[_step_evidence(step)],
                step_index=step["step_index"],
                recommendation=(
                    "Check grounding output and the coordinate_space label. "
                    "If the screenshot is device_px, action coords need scaling."
                ),
            )


def _step_viewport(step: dict[str, Any]) -> tuple[int, int] | None:
    # The viewport lives on the observation record, which is referenced by
    # path but not embedded in the step. For 0.1 we don't read PNGs; rules
    # that need pixel dimensions should be enabled per-adapter where the
    # adapter can stamp width/height onto the step.
    obs = step.get("observation_pre_meta")
    if isinstance(obs, dict):
        vp = obs.get("viewport") or {}
        if "width" in vp and "height" in vp:
            return int(vp["width"]), int(vp["height"])
    return None


@rule("cua.coordinate_space_mismatch", severity="high")
def coordinate_space_mismatch(ctx: BundleContext, r: RuleResult) -> None:
    """Action and grounding declare different coordinate spaces."""
    for step in ctx.steps:
        action_space = (step.get("action") or {}).get("coordinate_space")
        # Grounding doesn't have its own coordinate_space field today; we
        # infer from provenance + action's space. If provenance is `dom`
        # but action_space is `viewport_css_px`, the coordinate path is at
        # minimum confusing.
        grounding = step.get("grounding") or {}
        provenance = grounding.get("provenance")
        if provenance == "dom" and action_space == "viewport_css_px":
            r.emit(
                rule_id=coordinate_space_mismatch.rule_id,
                severity=coordinate_space_mismatch.severity,
                summary=(
                    f"Step {step['step_index']} grounding provenance is `dom` "
                    f"but action coordinate space is `viewport_css_px`."
                ),
                evidence=[_step_evidence(step)],
                step_index=step["step_index"],
                recommendation=(
                    "DOM-derived targets must remain diagnostic. If the agent "
                    "is acting on them, fix grounding or relabel provenance."
                ),
            )


@rule("cua.dom_used_as_runtime_target", severity="high")
def dom_used_as_runtime_target(ctx: BundleContext, r: RuleResult) -> None:
    """Spec §4 invariant: runtime action selection MUST be screenshot-
    grounded for any adapter claiming CUA semantics. DOM probes are
    diagnostic-only.

    Fires when a step has both:
      - grounding.provenance == "dom", AND
      - action.params carries numeric x/y (the DOM probe was used as
        a runtime coordinate, not just a side-channel sanity check).

    Distinct from cua.coordinate_space_mismatch (which checks the
    narrower "provenance=dom AND coordinate_space=viewport_css_px"
    combo). This one fires on ANY DOM-grounded runtime target,
    regardless of declared coordinate space."""
    for step in ctx.steps:
        grounding = step.get("grounding") or {}
        if grounding.get("provenance") != "dom":
            continue
        action = step.get("action") or {}
        params = action.get("params") or {}
        if not (
            isinstance(params.get("x"), (int, float))
            and isinstance(params.get("y"), (int, float))
        ):
            continue
        idx = step["step_index"]
        r.emit(
            rule_id=dom_used_as_runtime_target.rule_id,
            severity=dom_used_as_runtime_target.severity,
            summary=(
                f"Step {idx} used a DOM-derived coordinate "
                f"({params['x']},{params['y']}) as the runtime click target. "
                f"Spec §4 requires screenshot-grounded runtime targets; "
                f"DOM probes are diagnostic-only."
            ),
            evidence=[_step_evidence(step)],
            step_index=idx,
            recommendation=(
                "Run the action through the pixel grounder and dispatch on "
                "its output instead. If DOM coords are genuinely needed for "
                "a special-case step, mark grounding.provenance='human' "
                "or 'replay' to document the deliberate override."
            ),
        )


@rule("cua.no_state_change", severity="medium")
def no_state_change(ctx: BundleContext, r: RuleResult) -> None:
    """Step is flagged failure_class=no_state_change or verdict.status=recoverable
    with a no-visible-change reason."""
    for step in ctx.steps:
        fc = step.get("failure_class") or ""
        verdict = step.get("verdict") or {}
        reason = (verdict.get("reason") or "").lower()
        triggered = fc == "no_state_change" or (
            verdict.get("status") == "recoverable"
            and "no visible state change" in reason
        )
        if not triggered:
            continue
        idx = step["step_index"]
        r.emit(
            rule_id=no_state_change.rule_id,
            severity=no_state_change.severity,
            summary=f"Step {idx}: no visible state change after the dispatched action.",
            evidence=[_step_evidence(step), _events_evidence(idx)],
            step_index=idx,
            recommendation=(
                "Verify the click landed on the intended control. Compare pre "
                "and post screenshots for sub-pixel diffs; if identical, this "
                "is either a grounding miss or a dispatch-vs-state mismatch."
            ),
        )


@rule("cua.verifier_disagrees", severity="high")
def verifier_disagrees(ctx: BundleContext, r: RuleResult) -> None:
    """Verifier output contradicts the textual evidence summary."""
    for step in ctx.steps:
        verdict = step.get("verdict") or {}
        fc = step.get("failure_class") or ""
        if fc == "verifier_disagrees" or verdict.get("status") == "failed":
            idx = step["step_index"]
            # Strengthen the signal: only emit if a verifier event exists.
            events = ctx.events_for_step(idx)
            if any(e.get("layer") == "verifier" for e in events):
                r.emit(
                    rule_id=verifier_disagrees.rule_id,
                    severity=verifier_disagrees.severity,
                    summary=(
                        f"Step {idx}: verifier disagrees with the action's "
                        f"reported success."
                    ),
                    evidence=[_step_evidence(step), _events_evidence(idx)],
                    step_index=idx,
                    recommendation=(
                        "Inspect the verifier event; if the textual evidence is "
                        "correct, the action's reported success is the bug."
                    ),
                )


@rule("cua.dispatch_ok_state_fail", severity="high")
def dispatch_ok_state_fail(ctx: BundleContext, r: RuleResult) -> None:
    """Dispatch layer reported OK but the post-action state shows no change."""
    for step in ctx.steps:
        if step.get("failure_class") != "dispatch_ok_state_fail":
            continue
        idx = step["step_index"]
        r.emit(
            rule_id=dispatch_ok_state_fail.rule_id,
            severity=dispatch_ok_state_fail.severity,
            summary=(
                f"Step {idx}: dispatch reported success but state did not change."
            ),
            evidence=[_step_evidence(step), _events_evidence(idx)],
            step_index=idx,
            recommendation=(
                "Likely an SoM/CDP coordinate-space drift. Capture device_px "
                "viewport and compare against the action's coordinate_space."
            ),
        )


@rule("cua.invalid_action_schema", severity="critical")
def invalid_action_schema(ctx: BundleContext, r: RuleResult) -> None:
    """Model emitted an action object missing the required `type` or `params`."""
    for step in ctx.steps:
        action = step.get("action") or {}
        if not action.get("type"):
            idx = step["step_index"]
            r.emit(
                rule_id=invalid_action_schema.rule_id,
                severity=invalid_action_schema.severity,
                summary=(
                    f"Step {idx}: action is missing the required `type` field."
                ),
                evidence=[_step_evidence(step)],
                step_index=idx,
                recommendation="Validate model outputs against the action schema before dispatch.",
            )


@rule("cua.missing_observation", severity="low")
def missing_observation(ctx: BundleContext, r: RuleResult) -> None:
    """A step references an observation path that is not on disk and not
    declared in `manifest.missing`."""
    for step in ctx.steps:
        for key in ("observation_pre", "observation_post"):
            ref = step.get(key)
            if not isinstance(ref, str) or not ref.startswith("screenshots/"):
                continue
            if (ctx.bundle_dir / ref).exists():
                continue
            if ref in ctx.declared_missing:
                continue
            idx = step["step_index"]
            r.emit(
                rule_id=missing_observation.rule_id,
                severity=missing_observation.severity,
                summary=(
                    f"Step {idx}: {key} references {ref} but the file is "
                    f"missing and not listed in manifest.missing."
                ),
                evidence=[_step_evidence(step)],
                step_index=idx,
                recommendation=(
                    "Either capture the screenshot or list the path in "
                    "manifest.missing to mark it intentionally absent."
                ),
            )


@rule("cua.replay_diff", severity="medium")
def replay_diff(ctx: BundleContext, r: RuleResult) -> None:
    """A replay fixture exists for a step whose verdict is failed/recoverable.

    For `0.1` we don't actually run the replay; we surface the fixture as a
    starting point. Phase 3 replaces this with a real replay-output comparison.
    """
    replay_dir = ctx.bundle_dir / "replay"
    if not replay_dir.exists():
        return
    for path in sorted(replay_dir.glob("*_fixture.json")):
        rel = f"replay/{path.name}"
        # Pair with the failed step if we can.
        try:
            idx = int(path.stem.split("_", 1)[0])
        except ValueError:
            continue
        step = next((s for s in ctx.steps if s.get("step_index") == idx), None)
        if step is None:
            continue
        verdict = step.get("verdict") or {}
        if verdict.get("status") in ("failed", "recoverable"):
            r.emit(
                rule_id=replay_diff.rule_id,
                severity=replay_diff.severity,
                summary=(
                    f"Step {idx}: replay fixture available for a failing step. "
                    f"Run `augur replay-step` (Phase 3) to confirm whether the "
                    f"current code reproduces the failure."
                ),
                evidence=[_step_evidence(step), {"type": "step", "ref": rel}],
                step_index=idx,
            )


@rule("cua.high_cost_infra_failure", severity="high")
def high_cost_infra_failure(ctx: BundleContext, r: RuleResult) -> None:
    """A long-running run halted early on an infra failure.

    Heuristic: step duration > 0 AND failure_class in the infra family AND
    step is one of the first three.
    """
    INFRA = {"infra_failure", "mantis.modal_signature_missing"}
    for step in ctx.steps[:3]:
        fc = step.get("failure_class")
        if fc in INFRA:
            idx = step["step_index"]
            r.emit(
                rule_id=high_cost_infra_failure.rule_id,
                severity=high_cost_infra_failure.severity,
                summary=(
                    f"Run halted early on an infra failure at step {idx} "
                    f"({fc}). High-cost runs failing this early usually "
                    f"indicate environment or deploy issues, not agent bugs."
                ),
                evidence=[_step_evidence(step)] + (
                    [{"type": "log", "ref": p} for p in ctx.log_paths()]
                ),
                step_index=idx,
                recommendation=(
                    "Verify the deployment signature and proxy/tunnel health "
                    "before rerunning."
                ),
            )


@rule("cua.uncategorized_failure", severity="low")
def uncategorized_failure(ctx: BundleContext, r: RuleResult) -> None:
    """A step failed but its `failure_class` is missing or the literal
    string "unknown" — the producer's classifier didn't match any
    rule. Useful for adapter authors to spot gaps in their failure
    taxonomy. Not a runtime bug; surfaces as low-severity hygiene."""
    for step in ctx.steps:
        if step.get("status") != "failed":
            continue
        fc = step.get("failure_class")
        if fc and fc != "unknown":
            continue
        idx = step["step_index"]
        intent = step.get("intent") or "(no intent)"
        r.emit(
            rule_id=uncategorized_failure.rule_id,
            severity=uncategorized_failure.severity,
            summary=(
                f"Step {idx} failed but `failure_class` is "
                f"{fc!r} — the producer's classifier didn't catch this case."
            ),
            evidence=[_step_evidence(step)],
            step_index=idx,
            recommendation=(
                f"Inspect step {idx} ({intent!r}) and the verdict.reason "
                f"to identify the failure pattern, then extend the producer's "
                f"classify() rules. Canonical vocabulary: "
                f"https://mercurialsolo.github.io/augur-sdk/concepts/failure-class-taxonomy/"
            ),
        )


CUA_RULES: list[Rule] = [
    repeated_action_stable_frame,
    click_outside_viewport,
    coordinate_space_mismatch,
    dom_used_as_runtime_target,
    no_state_change,
    verifier_disagrees,
    dispatch_ok_state_fail,
    invalid_action_schema,
    missing_observation,
    replay_diff,
    high_cost_infra_failure,
    uncategorized_failure,
]
