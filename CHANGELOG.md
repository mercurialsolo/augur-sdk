# Changelog

All notable changes to `augur-sdk` are recorded here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), with semver applied per
`docs/versioning.md` upstream (`MAJOR.MINOR.PATCH`; pre-1.0 minors may break).

## [Unreleased]

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
