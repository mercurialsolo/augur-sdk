# augur-sdk — normative spec

**Status:** Draft, v0.1.
**Audience:** Implementers of the Augur SDK and anyone integrating a
CUA with it.
**Purpose:** Pin down the contract the SDK exposes — public surface,
behavioural guarantees, and version boundaries — so coding agents,
framework owners, and downstream tools can rely on it without reading
the source.

This document uses RFC-2119 keywords (`MUST`, `SHOULD`, `MAY`).

The umbrella product spec (architecture, the full debugger surface,
non-goals) is maintained alongside the hosted Augur service and is not
publicly mirrored. This file is the **SDK-only slice** — the contract
the public client exposes.

---

## 1. What the SDK is

A Python library that an authoring CUA imports to:

1. **Capture** a per-run trace at a configurable level of detail.
2. **Redact** sensitive material before it lands on disk or hits the network.
3. **Bundle** captured records onto disk in a path-stable, schema-validated
   layout.
4. **Stream** captured records to an Augur server (Sentry-style DSN),
   when configured. Streaming is observe-only on top of (1)–(3) — the
   local bundle is the canonical artefact; the network sink is an
   optimisation.

The SDK does **NOT**:

- Provide a UI (that's the Augur viewer, upstream).
- Provide a CLI (that's `augur-cli`, upstream).
- Make decisions for the CUA. The SDK never reads back from the server
  during a run to influence the agent's behaviour. (See §6.)

## 2. CUA contract preservation

The SDK MUST NOT promote DOM-derived coordinates to runtime inputs. Per
the umbrella spec §4, **runtime action selection is screenshot-grounded.**
Adapters MAY emit DOM/CDP records as `provenance: "dom"` for diagnostic
evidence, but the SDK will not interpret them as the agent's real
target. The diagnostic-rules engine (`augur_sdk.diagnostics`) flags any
rule that treats a non-`screenshot` provenance as a runtime input.

## 3. Public surface (the supported API)

These are the symbols the SDK considers public. Stable across patch
versions; **may break** across minor versions while pre-1.0; **strictly
additive** across minors post-1.0.

### Top-level (`augur_sdk`)

```python
from augur_sdk import (
    DebugSession,
    CaptureMode, resolve_capture_mode,
    DefaultRedactionPolicy, RedactionPolicy, DEFAULT_POLICY_ID,
    LocalFSStore, S3Store, Store,
    Adapter,
    ModelApiAdapterBase,  # since 0.1.7
    SUPPORTED_SCHEMA_RANGE, __version__,
)
```

`DebugSession` public methods:
`attach_observation`, `record_step`, `record_event`, `set_status`,
`add_tag`, `set_capture_mode` (since 0.1.3), `append_log` (since 0.1.3),
`attach_verifier` (since 0.1.5), `set_score` / `set_costs` /
`set_step_costs` / `record_modelio` (since 0.1.8), `close`.

### Models (`augur_sdk.models`)

Every record type the SDK accepts or produces is a `TypedDict`:

- `DebugSession`, `StepTrace`, `Observation`, `DecisionEvent`,
  `ReplayFixture`, `DiagnosticFinding`, `BundleManifest`, `BundleTrace`.

Enum types are `Literal`s — implementers can use them at the boundary
without runtime imports.

### Diagnostics (`augur_sdk.diagnostics`)

- `BundleContext`, `Rule`, `RuleResult`, `RulesEngine`
- `load_pack(name: str) -> list[Rule]`
- `rule(rule_id: str, *, severity: str = "medium")` decorator
- `CUA_RULES` — the generic rule pack

### Streaming (`augur_sdk.streaming`)

- `DSN` — parser
- `StreamingSink` — best-effort POSTs

Anything not listed here is **private**. Names starting with `_` are
private regardless.

## 4. Behavioural guarantees

The SDK MUST behave as follows. These are the only invariants downstream
consumers may rely on.

### 4.1 Bundle writes are atomic per file

Every file in a bundle is written via `<file>.tmp` + `os.replace`. A
reader observing the bundle mid-run never sees a partial file.

### 4.2 The bundle is always written

If `capture_mode != "off"`, the bundle is written to `out_dir` even when:
- Streaming is disabled.
- The network is unreachable.
- The DSN's `api_key` is rejected.
- The Augur server returns 4xx/5xx.

The bundle is the source of truth; streaming is observe-only.

### 4.3 Streaming failures are never fatal

The SDK MUST NOT raise on network errors. The streaming sink runs on
background threads and logs failures at DEBUG; never WARN or higher.
This means an instrumented CUA cannot be made to crash by toggling a
firewall rule.

### 4.4 Heartbeat cadence

When `dsn` is configured, the SDK MUST emit one initial
`session_opened` heartbeat as soon as the `StreamingSink` is constructed
(i.e. on `DebugSession(dsn=…)`), so the server's connection list shows
the client before any step has been recorded. While the session is
open, the SDK then heartbeats at intervals of **15 seconds ± 1 s**.
Operators set the server's heartbeat window via
`AUGUR_HEARTBEAT_WINDOW_S` (default 60 s).

### 4.5 No reads from the server during a run

The SDK MUST NOT issue HTTP `GET` against the Augur server while a
session is open. Live attach (Phase 4) introduces SSE/WS reads in a
viewer-side path; the SDK side stays write-only.

### 4.6 Redaction runs before bytes leave the SDK

Both local bundle writes and streaming POSTs run through the active
`RedactionPolicy` before serialization. There is no opt-out path.

### 4.7 Schema validation on close

`session.close()` MUST validate every record against the canonical
schemas under `augur_sdk._schema/json/`. Validation failure raises;
this is the one place the SDK is allowed to be loud (the alternative
is to ship a broken bundle).

### 4.8 Path stability

Every file in a bundle is at a path predictable from the step index
(or constant for top-level files). See [docs/concepts/bundle-layout.md].

### 4.9 No side-effecting imports

`import augur_sdk` MUST NOT open files, sockets, or threads. Side
effects begin at `DebugSession(...)` construction (network heartbeat
and thread spawn, when `dsn` is set) and at `DebugSession.__enter__`
(bundle directory creation, periodic heartbeat loop).

### 4.10 Thread safety

`DebugSession.record_step`, `record_event`, and `attach_observation`
MUST be safe to call from multiple threads on the same session. The SDK
uses an internal `threading.Lock` around the `EventRecorder`.

### 4.11 Mid-run capture-mode override (since 0.1.3)

`DebugSession.set_capture_mode(mode)` MUST NOT mutate the manifest's
`capture_mode`. Instead, every subsequent `record_step` gets an
explicit `capture_mode` field stamped on the StepTrace, per the
optional field on `step_trace.schema.json`. A `capture_mode` already
present on the StepTrace passed by the caller MUST NOT be overwritten.
The override persists for the rest of the session unless changed again
by another `set_capture_mode` call.

### 4.12 `append_log` is streaming-only (since 0.1.3)

`DebugSession.append_log(text, …)` MUST be a no-op when streaming is
disabled — the bundle on disk is the source of truth for local logs,
and producers that want them write to `logs/` directly via the
configured `Store`. With streaming enabled, the SDK POSTs to
`/api/v1/runs/<run_id>/logs` with a JSON body; the server routes the
chunk to `logs/<name>.log` (or `logs/step-<idx>.log` when
`step_index` is set).

### 4.13 `attach_verifier` post-hoc verdict (since 0.1.5)

`DebugSession.attach_verifier(step_index, status=…, …)` MUST replace
the target step's `verdict` field in-place. The previous verdict is
discarded — precedence is documented as
`native verdict > attach_verifier > inferred default`, i.e. an
external harness opting in to `attach_verifier` is asserting authority
over the producer's classification. When streaming is enabled, the
SDK MUST echo the patched step through the live sink (so viewers see
the updated verdict without waiting for `close()`); when streaming is
off, the patched verdict is written to disk on `close()`. Raises
`ValueError` if no step exists at `step_index`.

### 4.14 Training-data substrate schemas (since 0.1.6)

The vendored JSON Schemas gain four additive surfaces so a single
bundle can serve both debugging and SFT/DPO/RL training pipelines:

- `modelio.schema.json` (new short name `modelio`): canonical
  one-model-call record (`request`, `response`, `usage`,
  `prompt_hash`, …). Producers MUST write these under
  `<bundle>/modelio/<step_index:04d>-<layer>-<seq>.json` when
  `capture_mode` is `model_io` or `full`; lower modes MAY omit the
  directory entirely.
- `step_trace.costs` + `step_trace.latency` (optional): per-step
  token counts, USD breakdown, and per-layer wall-clock.
- `debug_session.costs` (optional): session-level rollup of the above.
- `verdict.{score, score_components, comparator}` (optional):
  continuous reward signal (0..1) alongside the categorical
  `status`. Default mapping when `score` is absent:
  `passed → 1.0`, `recoverable → 0.5`, `failed|skipped|unknown → 0.0`.
- `preference.schema.json` (new short name `preference`): DPO /
  RLHF preference record stored at
  `<bundle>/preferences/<step_index:04d>.json`. Decoupled from
  the immutable trace so raters MAY add comparisons after the
  run completes; the schema requires `preferred_action` +
  `alternatives[]` (each with an `action` and optional
  `reward_estimate`) and accepts a `comparator` of
  `verifier | model-judge | human-rater | replay-diff`.
- `prior_steps.schema.json` (new short name `prior_steps`, since
  0.1.9): sibling of `replay_fixture` written to
  `<bundle>/replay/<step_index:04d>.prior.json` when a fixture's
  `prior_steps` is non-null. Compact list of the steps that
  preceded the fixture's target — intentionally a thin subset of
  `step_trace` (action + verdict + intent only) so the replay
  agent sees the same context the original run had without
  inheriting observations/costs. Resolves a gap surfaced during
  the upstream augur#55 v1.0 freeze review.

Every field is additive and optional; all 0.1.x bundles produced by
prior SDK versions continue to validate. Producer-side helpers
(`attach_costs`, `attach_score`, `record_modelio`) ship in 0.2.0;
until then, adapters MAY populate the new fields directly on the
`StepTrace` dict they pass to `record_step()`.

### 4.16 Training-data producer-side helpers (since 0.1.8)

The 0.1.6 schema substrate (modelio, costs, verdict.score) gains
producer-side SDK helpers so adapters don't have to mutate session
internals to emit the new fields:

- `DebugSession.set_costs(...)` and `set_step_costs(step_index, ...)`
  MUST be merge-on-call (later kwargs win; unset dimensions are
  preserved). `set_costs` surfaces on **both** the session record
  and the manifest (`manifest.json#/costs`); `set_step_costs`
  patches the step's `costs` object on disk.
- `DebugSession.set_score(step_index, score, *, comparator,
  components)` MUST merge into the existing verdict (the
  categorical `status` is preserved); `score` MUST be clamped to
  `[0.0, 1.0]`; `comparator`, when set, MUST be one of
  `verifier | model-judge | exact-match | human`. Default
  status→score mapping for absent score remains the consumer's
  responsibility (passed→1.0, recoverable→0.5, failed/skipped/
  unknown→0.0).
- `DebugSession.record_modelio(record, *, step_index, layer,
  validate=True)` MUST validate `record` against
  `modelio.schema.json` (Draft 2020-12) unless `validate=False`,
  apply the session's `RedactionPolicy` before persistence (stamping
  `redaction_applied: true`), and be **idempotent on the record's
  `prompt_hash`** — repeat calls with the same hash MUST return the
  existing bundle-relative path without staging a duplicate file.
  Path convention: `modelio/<step_index:04d>-<layer>-<seq>.json`
  for step-scoped calls, `modelio/run-<layer>-<seq>.json` for
  run-scoped (`step_index=None`); `<seq>` is a monotonic per-(step,
  layer) counter starting at 0.

Step → modelio linkage is **path-based**, not field-based:
`step_trace.schema.json` carries no `modelio_refs` field. Consumers
locate the model calls for step N by globbing `modelio/N*.json`.

### 4.15 `ModelApiAdapterBase` scaffolding (since 0.1.7)

`augur_sdk.ModelApiAdapterBase` is shared scaffolding for adapters
whose native format is a message log (OpenAI Responses, Anthropic
Messages, similar). The base provides
`bundle_from_input(input_path, output_dir, *, screens_dir=None, run_id=None)`
— the canonical entry point the `augur.adapters` group looks for —
and resolves it through two subclass hooks:

- `iter_tool_calls(messages) -> Iterator[(turn_idx, tc_idx, action_dict)]`
  (**MUST** override): walks the message log in dispatch order and
  yields one canonical-shaped action per tool call.
- `load_messages(path) -> (messages, metadata)` (default reads a
  single JSON file with `{"messages": [...], "metadata": {...}}`):
  override for vendor-specific layouts (jsonl, split metadata, etc.).

Sidecar screenshots are looked up via `find_screenshot(screens_dir,
step_index, kind)`; the default template is
`{step_index:04d}_{kind}.png`. Steps the base writes default to
`status="succeeded"` with `verdict={"status": "unknown", "reason":
"no native verifier"}` — external harnesses MAY refine this via
`DebugSession.attach_verifier` (§4.13).

The base MUST produce a bundle that passes `validate_bundle()` for
every conforming subclass. Reference subclasses ship in separate
user-org packages (`augur-adapter-openai-cua`,
`augur-adapter-anthropic-cua`) to keep this SDK vendor-free.

## 5. Version policy

- The SDK follows semver per `MAJOR.MINOR.PATCH`.
- Pre-1.0: minors MAY break public surface but MUST ship a migration
  note in `CHANGELOG.md`.
- Post-1.0: minors are strictly additive; only majors break.
- `__version__` and `SUPPORTED_SCHEMA_RANGE` are introspectable at runtime.
- The bundled JSON Schemas under `augur_sdk._schema/json/` track the
  upstream schemas at the version pinned in `SUPPORTED_SCHEMA_RANGE`.

## 6. Non-goals (don't ask the SDK for these)

The SDK does not:

- Render the UI (use the Augur viewer, upstream).
- Provide a CLI (use `augur-cli`, upstream).
- Implement an HTTP server (use `augur-server`, upstream).
- Manage tenants, users, or DSNs (those are operator concerns; mint
  DSNs via `augur admin dsn-issue` upstream).
- Run a coding agent (use Claude Code / Cursor; this SDK produces the
  bundle they read).
- Schedule, retry, or replay runs (those are framework concerns).
- Validate adapter code (see the contract test suite upstream).

## 7. Status

- **Schema version**: `0.1`
- **SDK version**: `0.1.9`
- **Supported Python**: 3.11, 3.12, 3.13
- **Runtime deps**: `jsonschema`, `referencing`, `urllib3`

Anything beyond `0.1.x` may break this spec; check `CHANGELOG.md`.
