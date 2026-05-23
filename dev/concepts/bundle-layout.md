# Bundle layout

Every Augur trace lands on disk as a **path-stable directory** — same
shape on every host, every tenant, every framework. That's what lets the
viewer, CLI, and coding agents read bundles without configuration.

## On disk

```text
<bundle>/
  manifest.json                      # envelope: schema_version, paths, signatures, missing[]
  trace.json                         # session + ordered steps[] (everything in one file)
  AGENT.md                           # coding-agent-friendly index (first-read hints)
  steps/
    0000.json                        # one StepTrace per file (zero-padded index)
    0001.json
    ...
  events/
    0000.jsonl                       # decision events for step N (one event per line)
    run.jsonl                        # run-level events (when present)
  screenshots/
    0000_pre.png
    0000_post.png
    ...
  diagnostics/
    findings.json                    # output of `augur diagnose` (when run)
  logs/
    run.log                          # default destination for append_log(name="run")
    runner.log                       # adapter-supplied logs (any logs/<name>.log)
    step-0007.log                    # append_log(text, step_index=7) routes here
  schema/
    manifest.schema.json             # canonical record schemas — vendored so an
    step_trace.schema.json           #   offline agent can validate without a network
    ...
  replay/
    0011_fixture.json                # replay fixtures (capture_mode=replay or full)
    0011.prior.json                  # prior-step context for the fixture (since 0.1.9)
  modelio/
    0000-planner-0.json              # one ModelIORecord per call (since 0.1.6)
    0000-grounding-0.json             #   <step:04d>-<layer>-<seq>.json
    0011-verifier-0.json             # capture_mode=model_io or full
  preferences/
    0011.json                        # DPO / RLHF preference record (since 0.1.6)
```

## Why path-stable

A coding agent should not have to *discover* anything. Once it sniffs
`manifest.json` and sees `bundle_format == "augur-bundle"`, every other
file is at a predictable path. The Augur diagnostic-rule findings cite
evidence by these exact paths so an agent can `read_file` and quote.

## File-format choices

| File              | Format    | Why                                                         |
|-------------------|-----------|-------------------------------------------------------------|
| `*.json`          | JSON      | Schema-validated; agent-readable; diffable                  |
| `*.jsonl`         | JSON Lines | Append-only friendly; one decision event per line          |
| `*.png`           | PNG       | Loss-less; multimodal-model-friendly                        |
| `*.log`           | UTF-8 text | Grep-friendly; line-anchored citations (`#L120-L220`)      |
| `AGENT.md`        | Markdown  | A coding agent reads it first; humans can too               |
| `schema/*.json`   | JSON Schema | Local validation — no need to hit the network              |

## Atomic writes

Every file is written via `<file>.tmp + os.replace`. A bundle is always
*consistent up to the last completed step* — even if the runner crashes
mid-write you never see a half-step JSON.

## Identifying an Augur bundle

Sniff `manifest.json` for:

```json
{ "bundle_format": "augur-bundle", "schema_version": "0.1", ... }
```

Both fields are mandatory and stable; that's enough to discriminate from
other tools' debug exports.

## Missing artifacts (late attach)

If a step references `screenshots/0007_pre.png` but the file isn't on
disk (e.g. the SDK was attached only after step 5), the producer lists
the path in `manifest.missing[]`. Consumers MUST treat that as
"intentionally absent" rather than "broken bundle."

## Full spec

The normative path/format rules are split between the SDK's
[SPEC.md](../spec.md) (producer behaviour) and the vendored JSON
Schemas at `<bundle>/schema/*.schema.json`, which are bit-for-bit
identical to `src/augur_sdk/_schema/json/*.schema.json` in this repo —
that's how an offline consumer validates without a network.
