# Changelog

All notable changes to `augur-sdk` are recorded here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), with semver applied per
`docs/versioning.md` upstream (`MAJOR.MINOR.PATCH`; pre-1.0 minors may break).

## [Unreleased]

## [0.2.0] — 2026-05-23

### Schemas now live in the `augur-schema` PyPI package

Closes #20. The SDK no longer vendors its own copy of the canonical
JSON Schemas. They're shipped by the
[`augur-schema`](https://pypi.org/project/augur-schema/) package and
pulled in as a runtime dependency
(`augur-schema>=0.3.1,<0.4`). Single source of truth across the SDK,
the platform server, the viewer, and any third-party reader.

- Deleted `src/augur_sdk/_schema/` (the JSON files and the loader
  module). 17 files removed.
- `from augur_sdk._schema import …` → `from augur_schema import …` in
  `session.py`, `bundle.py`, `validation.py`, and all tests. The
  upstream package re-exports the same surface (`SCHEMA_VERSION`,
  `SchemaError`, `list_schemas`, `load_schema`, `schemas_dir`,
  `validator_for`), so the swap is mechanical for callers.
- `ValidationError` no longer re-exported via `augur_sdk._schema`;
  callers that need it import directly from `jsonschema.exceptions`
  (one-line change in two test modules + `session.py`).
- `bundle.py`'s schema-embed-in-bundle step now copies raw bytes from
  `augur_schema.schemas_dir()` rather than parse-and-reserialise via
  `load_schema()`. The embedded copy is bit-for-bit identical to the
  dep's published schema.

### Schema-side fix consumed in this release

- `branch_context` is now referenced on `debug_session.schema.json`
  as `anyOf [$ref, null]` (parallel to the existing reference on
  `step_trace.schema.json`). The SDK already emitted `branch_context`
  on the session record; with `augur-schema 0.3.1`, validation
  accepts it. Without the fix, `validate_bundle()` rejected its own
  branch bundles after the dep swap. Caught by a one-off field-shape
  diff between the vendored copy and the dep before deletion.

### Minor version bump

The `augur_sdk._schema` module was importable from outside the SDK
(referenced in 0.1.x docstrings and the bundle-layout doc), so
removing it is a semver-minor break even though no other public-API
signature changed. The SDK records, on-disk bundle layout, and
method surface are unchanged from 0.1.14.

### Records that gain canonical schemas

The upstream package ships new canonical schemas for records the SDK
already emitted as raw JSON in 0.1.14:
`reasoning_trace.schema.json`, `outcome_record.schema.json`,
`eval_candidate.schema.json`, plus standalone files for the
previously-inlined `branch_context`, `captured_versions`,
`env_fingerprint`, `judge_decision`, and `side_effect`. Calling
`validator_for(name)` works the same way for these as for every
other schema.

### Tests

- 180 tests pass against `augur-schema 0.3.1`. The full quality gate
  (`uv run pytest`, `uv run mypy -p augur_sdk`, `uv run ruff check`)
  stays green.

## [0.1.14] — 2026-05-23

### Sentry-for-CUA primitives — round two (umbrella #9)

- **`mark_for_eval()`** (closes #16). Tag a step as a
  regression-fixture candidate so server-side promotion can
  one-click it into the eval set. Tags land in
  `eval_candidates.json` at the bundle root and on the live stream
  via `StreamingSink.post_eval_candidate()`. Idempotent on
  `step_index` — last-write-wins. Tagging is allowed before
  `record_step()` lands.
- **`finalize_outcome()`** (closes #18). Couples
  `(verdict, task_class, cost_summary)` into one OutcomeRecord per
  step or session so the platform's cost-per-outcome rollup doesn't
  need to JOIN three independent fields. Session scope rolls up
  per-step `step.costs` for any field absent at the session level
  (session-level `set_costs()` wins ties). Records land in
  `outcomes.json` at the bundle root and on the live stream via
  `StreamingSink.post_outcome()`. New helper
  `session.successful_task_cost_summary()` returns the rolled-up
  summary in-process for budget asserts in tests.
- **`record_reasoning()`** (closes #14). First-class capture for
  models that emit explicit reasoning (Claude extended thinking,
  OpenAI reasoning summaries). Records land in
  `events/reasoning.jsonl` and on the live stream via
  `StreamingSink.post_reasoning()`. Reasoning text gets its own
  redaction hook on `RedactionPolicy` (`add_reasoning_redactor`,
  `apply_reasoning`) distinct from the regular redactors —
  reasoning often carries PII that the action stream doesn't.
  `ModelApiAdapterBase.extract_reasoning_from_response()` pulls
  reasoning blocks out of a Claude or OpenAI response without
  caller wiring.
- **`BranchContext`** (closes #15). New `branch_context=` kwarg on
  `DebugSession` labels replay-branch trajectories with
  `parent_run_id`, `branch_point_step_index`, `mutated_axis`
  (`model|prompt|action|grounder|tool_description`), and the
  mutation payload. The full context lands on the session record;
  a lightweight slice (without the mutation payload) propagates to
  every step so server-side cohort filters can exclude branches
  by default without joining back to the session. Production runs
  omit the field — no regression for callers that don't opt in.
- **Side-effect ledger API** (closes #11). New
  `declare_side_effect(step_index, resource, action, ...)` /
  `commit_side_effect(side_effect_id, observed_result)` /
  `mark_side_effect_aborted(side_effect_id, reason)` /
  `abort_pending_side_effects(reason)` API for irreversible agent
  actions. Declarations land before dispatch so the ledger shows
  the agent's intent even when the run is killed mid-step.
  Records live under `side_effects/<step:04d>-<id>.json` keyed to
  `(run_id, step_id, side_effect_id)`. Redaction policy applies
  to both `resource` and `observed_result`. New
  `Adapter.on_side_effect()` hook so adapters can auto-detect
  known irreversible action types. `StreamingSink.post_side_effect()`
  posts the full lifecycle live. New canonical
  `side_effect.schema.json` bundled with every release.
- **Intervention channel** (closes #12). Server→SDK control plane.
  New `session.bind_intervention(adapter)` starts a long-poll on
  `GET /runs/<run_id>/commands`, dispatching `pause`, `resume`,
  `kill`, `inject_hint`, and `override_action` to the adapter's
  intervention hooks (`on_pause`, `on_resume`, `on_kill`,
  `on_inject_hint`, `on_action_override`). Operator-supplied
  coordinates always carry `provenance="human_override"` so the
  trajectory preserves the SPEC §4 invariant that runtime action
  selection is screenshot-grounded. `kill` couples to the
  side-effect ledger (#11) — the channel aborts every pending
  declared side effect before invoking `adapter.on_kill()`.
  Adapters that don't implement a particular hook see the channel
  degrade to a no-op for that command type. At-least-once
  delivery with idempotency keys on `command_id`; cursor-based
  resumption so a dropped poll doesn't lose commands. Audit
  trail: every received command is logged to the session's
  decision-event stream with the operator id.

### Bundle layout

- New top-level paths: `side_effects/` (ledger),
  `eval_candidates.json` (#16 tags), `outcomes.json` (#18 coupled
  records), `events/reasoning.jsonl` (#14 reasoning). All
  reflected in `manifest.paths` and `manifest.signatures`.

### Models

- `BranchContext`, `SideEffect`, and `InterventionCommand` are now
  re-exported from `augur_sdk` for adapter authors.

### Tests

- 49 new tests across `tests/test_branching.py`,
  `tests/test_eval_candidates.py`, `tests/test_intervention.py`,
  `tests/test_outcomes.py`, `tests/test_reasoning.py`,
  `tests/test_side_effects.py`. Full suite: 180 tests, all green.

## [0.1.13] — 2026-05-23

### Sentry-for-CUA primitives (umbrella #9)

- **`captured_versions` on every StepTrace** (closes #10). Promoted
  from `ReplayFixture`-only to a first-class field. Extended with
  `prompt_hash`, `tool_descriptions_hash`, and `env_fingerprint_ref`.
  New `DebugSession.set_step_versions(step_index, model=…, prompt_hash=…)`
  accepts partial updates and merges last-write-wins.
  `record_modelio()` auto-stamps `model` (from `request.model`) and
  `prompt_hash` onto the corresponding step's `captured_versions`
  when called with `step_index=…`. Silent no-op if the step hasn't
  been recorded yet — late stamping uses the explicit setter.
- **`env_fingerprint` on Observation + StepTrace** (closes #13). New
  `DebugSession.attach_env_fingerprint(step_index, url_host=…,
  url_path_template=…, viewport_hash=…, dom_hash=…, api_shapes=…,
  extensions=…)`. Stored side-by-side with the visual fingerprint
  (`observation.hashes.phash_64`), not merged, so the platform's
  determinism checker can attribute drift to agent/model/env
  independently. SDK never derives `dom_hash` itself — only adapters
  that already probe DOM for diagnostics should populate it
  (preserves the screenshot-grounded core invariant).
- **`record_judge_decision()`** (closes #17). Model, rule, human,
  and hybrid judges land as first-class verdicts on
  `step.judge_decisions`. The operative `step.verdict` is set
  last-write-wins by default; `step.verdict_source` carries
  `<judge_type>:<judge_id>` provenance. `attach_verifier()` now
  emits an implicit `judge_type="rule"` decision alongside its
  verdict patch so the rule-vs-model-vs-human provenance is
  preserved across the legacy entry point too. New
  `StreamingSink.post_judge_decision()` fire-and-forget hook so
  HITL overrides land live.
- **`trajectory_fingerprint` on every manifest** (closes #19).
  Deterministic, hand-crafted digest over the
  `(action.type, failure_class|verdict.status, normalized_target_label)`
  sequence of the run. Same shape → same fingerprint, across SDK
  versions and machines. One-step swap → close-but-different
  fingerprint (Hamming-style proximity on the bigram half). The
  algorithm is pluggable via the `augur_sdk.fingerprints` entry
  point group — adapters can swap in a learned embedding without
  changing the SDK API. Documented at
  `docs/concepts/trajectory-fingerprint.md`. Default = `cua_v1`.

### Models

- `JudgeDecision`, `EnvFingerprint`, and `CapturedVersions` are now
  re-exported from `augur_sdk` for adapter authors.

### Tests

- `tests/test_captured_versions.py`, `tests/test_env_fingerprint.py`,
  `tests/test_judge_decisions.py`, `tests/test_fingerprint.py` — full
  round-trip coverage including streaming hooks, validation against
  the bundled schemas, and backward compat for bundles without the
  new fields.

## [0.1.12] — 2026-05-22

### Docs

- Mirror raw `.md` alongside every published HTML page on the docs
  site — e.g. `…/latest/reference/api.md` returns the canonical
  markdown source. Coding agents can fetch docs directly without
  scraping HTML.
- Emit `llms.txt` and `llms-full.txt` at the root of each versioned
  build (`…/latest/llms.txt`), following the
  [llms.txt](https://llmstxt.org/) convention. `llms.txt` is a
  grouped index of every doc page; `llms-full.txt` is a single-file
  concatenation of the full corpus in nav order.
- Both are produced by a small mkdocs build hook (`hooks/llms_export.py`)
  with no new runtime dependencies. The hook captures each page's
  markdown after the `include-markdown` plugin runs, so transcluded
  content (e.g. the changelog) is inlined in the mirrored `.md`.

## [0.1.11] — 2026-05-22

### Docs

- Document the producer-facing surface for live modelio streaming.
  `Session.record_modelio()` now spells out that, with a DSN
  configured, the same call also POSTs the redacted record to
  `/api/v1/runs/<run_id>/modelio/<relpath>` on a background
  thread, and that a `403` latches the sink off for the session
  while the bundle on disk still owns the record.
- Add `StreamingSink.post_modelio()` and `StreamingSink.post_logs()`
  to the streaming class surface in `reference/api.md` (they
  shipped in 0.1.10 and 0.1.8 respectively but weren't listed).
- Add the `POST /api/v1/runs/{id}/modelio/{relpath}` ingest row +
  curl example to `reference/http-api.md`.

## [0.1.10] — 2026-05-21

### Streaming

- **`StreamingSink.post_modelio()`** (closes #5). When a streaming
  sink is attached, each `DebugSession.record_modelio()` call now
  fires the staged record live to the server's per-tenant ingest
  route at `POST /api/v1/runs/{id}/modelio/{relpath}` in addition to
  staging it for the on-close bundle. If the server returns 403 (the
  tenant hasn't opted in), the SDK latches `_modelio_disabled` and
  stops trying for the rest of the session — the local bundle is
  unaffected and bundle-only consumers see no regression. Paired with
  the upstream server route (mercurialsolo/augur#62).

### Tests

- `tests/test_streaming_modelio.py` (3 tests) — wire format on the
  modelio route, 403 → latch behaviour, and the negative case where
  non-403 errors don't disable streaming.
- `tests/test_record_modelio.py` — extended with a sink-wiring case
  that asserts `post_modelio()` is called with the recorder's
  reserved relpath and the post-redaction payload.

## [0.1.9] — 2026-05-20

### Schema

- **Vendor `prior_steps.schema.json`** (closes #4). The replay
  workbench's sibling artifact `replay/<step_index:04d>.prior.json`
  finally has a vendored schema in the SDK; producers can now
  validate prior-step payloads offline via
  `augur_sdk._schema.validator_for("prior_steps")`. Byte-identical
  with the upstream `mercurialsolo/augur` monorepo. Surfaced during
  the augur#55 schema v1.0 freeze review.

### Tests

- `tests/test_prior_steps_schema.py` (13 tests) — required-field
  failures, additionalProperties on the item level, action.type +
  verdict.status / verdict.score validation, and a bundle-disk
  round-trip alongside the existing replay fixture coverage.

## [0.1.8] — 2026-05-20

### Added — producer-side helpers for the 0.1.6 training-data substrate

Closes the three open SDK issues (#1, #2, #3). Until 0.1.8 the
costs/score/modelio schema fields existed but adapters had to mutate
session internals to emit them.

- **`DebugSession.set_costs(*, total_usd=…, model_usd=…, gpu_usd=…,
  proxy_usd=…, tokens_in=…, tokens_out=…, cache_hit_tokens=…)`**:
  stamp a structured cost rollup on the session. Surfaces on both
  the session record (`trace.json`) and the manifest
  (`manifest.json#/costs`) so cost-aware consumers (run-list
  dashboards, training pipelines) can read either. Repeat-call merge
  semantics; unset dimensions are preserved. Closes #1.
- **`DebugSession.set_step_costs(step_index, *, total_usd=…,
  model_usd=…, tokens_in=…, tokens_out=…, cache_hit_tokens=…)`**:
  patch a recorded step's `costs` object. Merge semantics; raises
  `ValueError` if no step exists at `step_index`. Closes #1.
- **`DebugSession.record_modelio(record, *, step_index=None,
  layer=None, validate=True)`**: canonical producer-side helper for
  one model call. Validates against the vendored
  `modelio.schema.json`, stages under
  `modelio/<step_index:04d>-<layer>-<seq>.json` (or
  `modelio/run-<layer>-<seq>.json` when `step_index` is None), and
  is **idempotent on `prompt_hash`** — repeat calls with the same
  hash return the existing path without staging a duplicate.
  Applies the session's `RedactionPolicy` and stamps
  `redaction_applied: true`. Stamps `layer` onto the record when
  the kwarg is provided and the record doesn't already carry one.
  Closes #2.
- **`DebugSession.set_score(step_index, score, *, comparator=None,
  components=None)`**: attach a continuous reward signal (0..1) to
  a recorded step's verdict. Merges into the existing verdict
  (status/reason preserved); score clamped to `[0.0, 1.0]`;
  `comparator` validated against the canonical enum
  (`verifier | model-judge | exact-match | human`). Closes #3.

### Schema

- `manifest.schema.json` gains optional `costs` (mirrors the
  session-level rollup) and two new path constants in `paths`:
  `modelio` → `modelio/` and `preferences` → `preferences/`.
  Additive; every prior 0.1.x manifest continues to validate.
- Bundle layout: new `modelio/` directory is written automatically
  when `record_modelio` is called. The path tree in
  `docs/concepts/bundle-layout.md` reflects the new entries.

### Notes for producer authors

- Step → modelio linkage is **path-based** (`<step:04d>-…`), not
  field-based — `step_trace.schema.json` doesn't carry a
  `modelio_refs` array. Consumers locate model calls for step N by
  globbing `modelio/N*.json`.

## [0.1.7] — 2026-05-20

### Added

- **`ModelApiAdapterBase`**: shared scaffolding for adapters whose
  native format is a message log (OpenAI Responses, Anthropic
  Messages, similar). Subclasses implement two methods —
  `iter_tool_calls(messages)` and optionally `load_messages(path)`
  — and inherit `bundle_from_input(input, output)` which walks the
  log, opens a DebugSession, emits one StepTrace per tool call,
  and resolves sidecar screenshots from a `screens/` directory.
  Reduces the OpenAI / Anthropic Computer-Use adapter footprint
  by ~70%. Closes upstream augur#53.

## [0.1.6] — 2026-05-20

### Added — training-data substrate schemas (mirrors upstream augur 0.1.2 schema)

- **`modelio.schema.json`** (new): canonical record for one model
  call's full input + output. Loaded under short name `modelio`.
  Pinned shape lets downstream SFT/DPO pipelines harvest training
  data from any compliant producer without adapter-specific parsers.
  Closes upstream augur#56.
- `step_trace.schema.json`: new optional `costs` and `latency`
  objects on each step (token counts, USD breakdown, per-layer ms).
  Closes part of upstream augur#58.
- `debug_session.schema.json`: new optional `costs` rollup on the
  session. Closes the rest of upstream augur#58.
- `step_trace.schema.json` → `verdict`: new optional `score`
  (0..1), `score_components`, `comparator` enum
  (verifier|model-judge|exact-match|human). The `status` enum
  stays the canonical pass/fail bucket; score is additive for
  RL/SFT pipelines needing partial credit. Closes upstream
  augur#59.
- **`preference.schema.json`** (new): preference / counterfactual
  record for DPO + RLHF training data. Stored at
  `preferences/<step_index:04d>.json`, decoupled from the
  immutable trace so a human rater can add comparisons days
  after the run completes. Captures `preferred_action`, ranked
  `alternatives` with optional `reward_estimate`, and the
  `comparator` (verifier | model-judge | human-rater |
  replay-diff). Closes upstream augur#57.

All additions are optional + additive. Every 0.1.x bundle still
validates.

## [0.1.5] — 2026-05-20

### Added

- **`DebugSession.attach_verifier(step_index, status=..., reason=..., check=..., expected=..., actual=..., evidence_refs=...)`**:
  let an external harness add a post-hoc verdict to a step the
  producer didn't categorize. Useful for traces from frameworks
  with no native verifier signal (OpenAI / Anthropic Computer-Use,
  raw OSWorld). Replaces the step's `verdict` field in-place.
  Streams the patched step through the live sink so viewers see
  the update without waiting for close(). Closes upstream augur#51.
- New `cua.dom_used_as_runtime_target` diagnostic rule (severity:
  high). Fires when a step's `grounding.provenance == "dom"` AND
  `action.params` carries numeric x/y — a spec §4 invariant
  violation (runtime targets must be screenshot-grounded; DOM
  probes are diagnostic-only). Closes upstream augur#50.

## [0.1.4] — 2026-05-19

### Added

- New `cua.uncategorized_failure` diagnostic rule (severity: low).
  Fires when a step has `status: "failed"` but `failure_class` is
  empty or the literal `"unknown"` — the producer's classifier
  didn't match any rule. Surfaces as hygiene feedback to adapter
  authors; the recommendation points at the step's intent + the
  verdict.reason so a maintainer can extend the classify() rules.

## [0.1.3] — 2026-05-20

### Added

- **`DebugSession.set_capture_mode(mode)`**: change the active
  capture mode mid-run. The next `record_step` (and every subsequent
  one) gets an explicit `capture_mode` field stamped on the
  StepTrace. Lets a CUA start in `metadata` (cheap) and upgrade to
  `screenshots` after the first failed verifier check, without
  restarting the session. Matches `step_trace.schema.json`'s new
  optional `capture_mode` field (closes upstream augur#36).
- **`DebugSession.append_log(text, step_index=None, name="run")`**:
  convenience to stream a runner-log chunk to the server's
  `POST /api/v1/runs/<id>/logs` endpoint. Routes to
  `logs/step-<idx>.log` when `step_index` is set, else
  `logs/<name>.log`. No-op when streaming is disabled
  (the bundle on disk owns local logs). Closes upstream augur#17.

### Schema

- Vendored `step_trace.schema.json` mirrors the upstream addition of
  the optional `capture_mode` field. Additive; every 0.1 bundle
  still validates.

## [0.1.2] — 2026-05-19

### Fixed

- Heartbeat POST now sends a JSON body with `Content-Type:
  application/json`. Previously it used `urllib3`'s `fields=` kwarg,
  which produces `multipart/form-data` — the server parsed that as an
  empty JSON body and returned **HTTP 422 "client_id field required"**,
  silently breaking the connection-status badge against any server
  shipped after the JSON-only heartbeat parser landed.
- Added `tests/test_streaming_heartbeat.py` to pin the wire format so
  this can't regress.

## [0.1.1] — 2026-05-19

### Changed

- `StreamingSink` now fires one immediate `session_opened` heartbeat
  at construction time (i.e. on `DebugSession(dsn=…)`), so the
  workspace's connection list shows the client before the first step
  is recorded. The periodic 15 s heartbeat loop continues to start at
  `__enter__` as before.
- Heartbeat payload gains an optional `last_event` field used by the
  initial fire. Existing servers ignore unknown fields; no client or
  server upgrade required.

### Spec

- §4.4 now documents the initial-fire requirement.
- §4.9 now reflects that side effects begin at `DebugSession(...)`
  construction when `dsn` is configured, not at `__enter__`.

## [0.1.0] — 2026-05-19

Initial standalone release.

### Added

- `DebugSession` context manager — the only API a CUA needs to integrate.
- Capture modes (`off` / `metadata` / `trace` / `screenshots` / `model_io` / `dispatch` / `replay` / `full`) spec'd in `augur_sdk.CaptureMode`.
- Atomic local bundle writer with path-stable layout (`manifest.json`, `trace.json`, `steps/`, `events/`, `screenshots/`, `AGENT.md`, `schema/`).
- DSN-based streaming sink (Sentry-style). Set `AUGUR_DSN=…` or pass `dsn=` directly; per-step + per-screenshot POSTs with a 15 s heartbeat. Bundle on disk is always written even if the network is flapping.
- Vendored JSON Schemas (`augur_sdk._schema`) — zero monorepo dependency at install time.
- `RedactionPolicy` + shipped `default-pii-v1` policy: drops `Authorization` / `Cookie` / `Set-Cookie` / `X-API-Key`; masks `token` / `api_key` / `ssn` / `credit_card` / `cvv`; regex-scrubs bearer tokens, AWS keys, JWTs, and password=… patterns.
- Diagnostic rules engine + generic `cua` rule pack (10 rules). Adapter packs land via the `augur.rule_packs` entry-point group.
- Adapter base protocol (`augur_sdk.Adapter`) + contract for adapter authors.
- `LocalFSStore` (default) + `S3Store` stub for forward compatibility.
- `validate_bundle()` — schema-validates every record in a bundle against the vendored JSON Schemas.

### Compatibility

- Schema version: `0.1`.
- Python: ≥ 3.11.
- Compatible with the Augur server's `/api/v1/*` ingest endpoints at server version 0.1.x.
