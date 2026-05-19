# Diagnostics

Augur ships a **rules engine** that runs over a bundle and emits findings
with citations back to the exact step/event/screenshot the rule fired
on. Bundle in, JSON out — perfect for a coding agent.

## Run from Python

```python
from augur_sdk.diagnostics import RulesEngine, load_pack

engine = RulesEngine(load_pack("cua"))
findings = engine.evaluate("/path/to/bundle")
for f in findings:
    print(f["severity"], f["rule_id"], f["summary"])
    for e in f["evidence"]:
        print(f"  ↳ {e['type']}: {e['ref']}")
```

## Run from the CLI

```bash
augur diagnose /path/to/bundle --rules cua
# Or as JSON for a coding agent
augur diagnose /path/to/bundle --rules cua --json
# Exit non-zero on high-or-worse findings (CI-friendly)
augur diagnose /path/to/bundle --rules cua --fail-on high
```

## What a finding looks like

```json
{
  "rule_id": "cua.no_state_change",
  "severity": "medium",
  "summary": "Step 2: no visible state change after the dispatched action.",
  "recommendation": "Verify the click landed on the intended control. Compare pre/post screenshots for sub-pixel diffs.",
  "step_index": 2,
  "evidence": [
    {"type": "step", "ref": "steps/0002.json"},
    {"type": "event", "ref": "events/0002.jsonl"}
  ]
}
```

`evidence[].ref` is a **bundle-relative path** an agent (or human) can
`read_file` directly. No discovery, no glob, no guessing.

## Generic CUA rules (ship with the SDK)

| Rule ID                          | Severity | Catches                                                    |
|----------------------------------|----------|------------------------------------------------------------|
| `cua.repeated_action_stable_frame` | medium  | Two clicks at the same coord with no state change         |
| `cua.click_outside_viewport`     | high     | Action coord outside the viewport (DSF / space mismatch)   |
| `cua.coordinate_space_mismatch`  | high     | Grounding provenance=dom + action in viewport_css_px       |
| `cua.no_state_change`            | medium   | failure_class=no_state_change OR verdict==recoverable      |
| `cua.verifier_disagrees`         | high     | Verifier failed AND a verifier event exists for the step   |
| `cua.dispatch_ok_state_fail`     | high     | Dispatch reported success but post-state didn't change     |
| `cua.invalid_action_schema`      | critical | Action missing `type`                                     |
| `cua.missing_observation`        | low      | Step refs a PNG that's neither on disk nor in `missing[]`  |
| `cua.replay_diff`                | medium   | Replay fixture available for a failing step               |
| `cua.high_cost_infra_failure`    | high     | Early-run infra failure on a long-running plan             |

## Adapter packs

Adapter packs add framework-specific rules. They register via the
`augur.rule_packs` entry-point group; if you `pip install
augur-adapter-mantis` (or similar), the pack appears automatically:

```python
load_pack("mantis")   # generic CUA rules + Mantis pack
```

See [adapter-authoring.md](../reference/adapter-authoring.md) to write
your own.

## Writing a rule

```python
from augur_sdk.diagnostics import rule, BundleContext, RuleResult

@rule("myorg.click_after_modal", severity="high")
def click_after_modal(ctx: BundleContext, r: RuleResult) -> None:
    for step in ctx.steps:
        if step.get("step_type") != "click":
            continue
        for ev in ctx.events_for_step(step["step_index"]):
            if ev.get("summary", "").startswith("modal opened"):
                r.emit(
                    rule_id=click_after_modal.rule_id,
                    severity=click_after_modal.severity,
                    summary=f"Step {step['step_index']}: clicked while a modal was open.",
                    evidence=[
                        {"type": "step", "ref": f"steps/{step['step_index']:04d}.json"},
                        {"type": "event", "ref": f"events/{step['step_index']:04d}.jsonl"},
                    ],
                    step_index=step["step_index"],
                    recommendation="Wait for modal close before dispatching.",
                )
```

Register it in your `pyproject.toml`:

```toml
[project.entry-points."augur.rule_packs"]
myorg = "myorg_augur_rules:rule_pack"
```

Then `load_pack("myorg")` picks it up.

## Cite evidence

The whole point: a finding *cites* its evidence. When a coding agent
proposes a code change, instruct it to format citations as:

```
<rule_id> @ <bundle-relative path>
```

For example: `cua.verifier_disagrees @ steps/0011.json`. Anyone reviewing
the patch can verify in O(1) by reading that one file.
