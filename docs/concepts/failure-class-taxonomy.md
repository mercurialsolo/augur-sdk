# Failure-class taxonomy

`step.failure_class` is the canonical "what kind of thing went wrong"
field on a `StepTrace`. Producers stamp it from their own classifier;
consumers (the viewer, the diagnostic rules engine, dashboards) group
and filter by it.

The field is an **open string** — adapters MAY extend the vocabulary
without a schema bump — but the rules engine and viewer are tuned to
the generic vocabulary below.

## Generic vocabulary

| Class                          | Means                                                                          |
|--------------------------------|--------------------------------------------------------------------------------|
| `no_state_change`              | Dispatch reported success but the post-screenshot is pixel-identical to pre.   |
| `click_outside_viewport`       | Action coordinate fell outside the viewport bounds (DSF / coord-space bug).    |
| `coordinate_space_mismatch`    | Grounding produced DOM coordinates but the dispatcher consumed CSS pixels.     |
| `verifier_disagrees`           | Verifier event said `failed`/`recoverable` while dispatch reported success.    |
| `dispatch_ok_state_fail`       | Dispatch backend returned ok; downstream state check still flagged failure.    |
| `invalid_action_schema`        | The action record was missing required fields (e.g. `type`).                   |
| `missing_observation`          | Step referenced a screenshot path that is neither on disk nor in `missing[]`.  |
| `infra_failure`                | Network, browser-process, or environment-level failure (not agent fault).      |
| `model_timeout`                | The model call itself timed out before producing a tool call or response.      |
| `som_clicked_container`        | Set-of-marks grounding picked the wrong parent element (overshoot).            |
| `tab_walk_target_absent`       | Keyboard navigation reached the end of the focus order without hitting target. |

These match the canonical
[`failure_class.schema.json`](https://github.com/mercurialsolo/augur/blob/main/packages/schema/augur_schema/json/failure_class.schema.json)
shipped by the `augur-schema` package and are what the generic `cua`
rule pack reasons about.

## Adapter-specific extensions

Adapters MUST namespace their own classes under `<adapter>.<class>`:

| Class                                  | Source adapter | Means                                                |
|----------------------------------------|----------------|------------------------------------------------------|
| `mantis.modal_signature_missing`       | Mantis         | Mantis classifier flagged a modal without a known signature. |
| `mantis.cf_challenge`                  | Mantis         | Cloudflare bot-check page intercepted the run.       |
| `mantis.brain_loop_exhausted`          | Mantis         | The agent looped past its retry budget without progress. |

The adapter pack's rules can match on these directly
(`failure_class == "mantis.modal_signature_missing"`); generic rules
ignore namespaced classes they don't understand.

## What "unknown" means

A producer that runs a step to failure but can't classify it should
either:

- omit `failure_class` entirely, **or**
- set it to the literal `"unknown"`.

Both are treated identically by consumers and trigger the
`cua.uncategorized_failure` rule (severity: low) — hygiene feedback so
adapter authors notice when their classifier missed a real pattern.

## Mapping non-Augur vocabularies

If your producer already has its own taxonomy, write a small mapping
table in the adapter rather than emitting the producer's strings raw.
That keeps consumers (especially dashboards filtering by `failure_class`)
sane across runs from different frameworks. See
[Adapter authoring → Map failure classes](../reference/adapter-authoring.md).
