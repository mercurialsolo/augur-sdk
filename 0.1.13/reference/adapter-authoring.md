# Adapter authoring

An **adapter** maps a specific CUA framework into the Augur portable
schema. Adapters live in their own pip packages (one per framework);
this SDK ships the `Adapter` protocol they implement.

## When to write an adapter

| Situation                                                              | Path                                |
|------------------------------------------------------------------------|-------------------------------------|
| You control the CUA's source                                           | Don't write an adapter — call `DebugSession` directly |
| The CUA already emits its own trace format on disk                     | Write an adapter that reads the format and emits Augur records |
| The CUA is operated by someone else (Mantis-style ingest)              | Adapter (post-hoc)                  |
| You want a Mantis-like rule pack with framework-specific diagnostics   | Adapter + rule pack                 |

## Minimal adapter shape

```python
# myorg_augur_adapter/adapter.py
from pathlib import Path
from typing import ClassVar
from augur_sdk import CaptureMode, DebugSession

class MyOrgAdapter:
    name: ClassVar[str] = "myorg"
    SUPPORTED_SCHEMA_RANGE: ClassVar[tuple[str, str]] = ("0.1", "0.1")

    @staticmethod
    def bundle_from_input(input_dir: str | Path, output_dir: str | Path) -> Path:
        """Convert framework-native input into an Augur bundle."""
        with DebugSession(
            run_id=...,
            client_name=MyOrgAdapter.name,
            client_version=...,
            capture_mode=CaptureMode.FULL,
            out_dir=output_dir,
        ) as session:
            # Read your framework's native output; for each step,
            # translate + record into the session.
            ...
        return Path(output_dir).resolve()
```

## Shortcut: message-log adapters (since 0.1.7)

OpenAI Responses, Anthropic Messages, and similar message-log-based
CUAs share ~80% of the adapter pattern: walk a message log, find tool
calls, emit one StepTrace per tool call, attach sidecar screenshots.
Subclass `ModelApiAdapterBase` and you implement *two* methods
instead of the whole `bundle_from_input` flow:

```python
from collections.abc import Iterator
from typing import Any
from augur_sdk import ModelApiAdapterBase

class OpenAICuaAdapter(ModelApiAdapterBase):
    name = "openai-cua"

    def iter_tool_calls(
        self, messages: list[dict[str, Any]]
    ) -> Iterator[tuple[int, int, dict[str, Any]]]:
        for turn_idx, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                continue
            for tc_idx, tc in enumerate(msg.get("tool_calls", [])):
                if tc.get("type") != "computer_use_preview":
                    continue
                yield (turn_idx, tc_idx, self._action_from_tc(tc))

    def grounding_provider(self) -> str:
        return "openai.computer_use_preview"
```

`bundle_from_input(input_path, output_dir, *, screens_dir=None,
run_id=None)` is inherited. Sidecar screenshots are auto-resolved
from `<input_path.parent>/screens/<step_index:04d>_{pre,post}.png`
(override `screenshot_filename_template` or `find_screenshot` per
provider). Steps land with `verdict={"status": "unknown", ...}` —
external harnesses can refine via `DebugSession.attach_verifier`
once an authoritative check is available.

Override `load_messages(path)` when your input isn't a single JSON
file with `{"messages": [...], "metadata": {...}}` shape (e.g.
conversation `.jsonl`, separate metadata file).

## Register via entry points

```toml
# pyproject.toml
[project]
name = "augur-adapter-myorg"
dependencies = ["augur-sdk"]

[project.entry-points."augur.adapters"]
myorg = "myorg_augur_adapter:MyOrgAdapter"

[project.entry-points."augur.rule_packs"]
myorg = "myorg_augur_adapter.rules:rule_pack"
```

The `augur bundle --adapter myorg` CLI (in the upstream tooling)
discovers your adapter automatically; same for `augur diagnose --rules
myorg`.

## Contract requirements

Every adapter MUST:

1. **Preserve the CUA contract.** Tag every grounded coordinate with
   `provenance: "screenshot"`. DOM probes MAY be emitted as `provenance:
   "dom"` for diagnostic-only use, but MUST NOT be the agent's runtime
   target.
2. **Use the canonical coordinate spaces.** `viewport_css_px`,
   `device_px`, `screenshot_px`, or `dom_client_rect`. The validator
   rejects anything else.
3. **Map failure classes.** Free-form framework failure strings get
   canonicalised against the vocabulary fixed by
   `src/augur_sdk/_schema/json/failure_class.schema.json`.
4. **Produce a bundle that passes `validate_bundle()`.** The schemas are
   vendored at `augur_sdk._schema/json/`; the SDK runs them on every
   write.

## Rule pack — write your own diagnostic rules

```python
# myorg_augur_adapter/rules.py
from augur_sdk.diagnostics import BundleContext, Rule, RuleResult, rule

@rule("myorg.click_after_modal", severity="high")
def click_after_modal(ctx: BundleContext, r: RuleResult) -> None:
    for step in ctx.steps:
        if step.get("step_type") != "click":
            continue
        for ev in ctx.events_for_step(step["step_index"]):
            if "modal opened" in (ev.get("summary") or ""):
                r.emit(
                    rule_id=click_after_modal.rule_id,
                    severity=click_after_modal.severity,
                    summary=f"Step {step['step_index']}: clicked while a modal was open.",
                    evidence=[
                        {"type": "step", "ref": f"steps/{step['step_index']:04d}.json"},
                        {"type": "event", "ref": f"events/{step['step_index']:04d}.jsonl"},
                    ],
                    step_index=step["step_index"],
                )

MANTIS_RULES: list[Rule] = [click_after_modal]

def rule_pack() -> list[Rule]:
    """Combine generic CUA rules with this adapter's rules."""
    from augur_sdk.diagnostics import load_pack
    return load_pack("cua") + MANTIS_RULES
```

`load_pack("myorg")` from a consumer's code now returns the generic +
adapter rules combined.

## Reference adapter

Mantis is the canonical example. The adapter is maintained alongside
the hosted Augur service (not currently open source); the
[Mantis runtime itself](https://github.com/mercurialsolo/mantis) is
public. The adapter demonstrates:

- Reading on-disk Mantis `TraceExporter` files (epoch timestamps,
  POST-only screenshots, free-form `data` failure strings).
- Re-implementing Mantis's `failure_class.classify()` so we don't import
  Mantis Python.
- Mapping Mantis's `layer` vocabulary (`critic-frontier`,
  `agentic-recovery`, `som-click`, `gate-decision`) onto the Augur
  `DecisionEvent.layer` enum.
- A rule pack with framework-specific rules (`mantis.wrong_target`,
  `mantis.brain_loop_exhausted`, `mantis.no_state_change_after_click`,
  …).

Read its source as a template.
