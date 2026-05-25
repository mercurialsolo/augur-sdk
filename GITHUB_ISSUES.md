# GitHub issues — augur-sdk

Parallelisable work, organized so a coding agent (or several in parallel)
can pick a single bullet and ship it without stepping on another agent.

Each issue has the same shape:

- **What** — the deliverable
- **Why** — the user value
- **Done when** — testable acceptance criteria
- **Touches** — files / modules likely to change (so two agents don't collide)
- **Depends on** — other issues that must land first (most are independent)

Issues are sized to ship one PR. If a bullet feels bigger than that, split
it before opening it.

The umbrella repo (`mercurialsolo/augur`) has its own `GITHUB_ISSUES.md`
for server, viewer, CLI, and adapter work — **don't duplicate** those
here. This file is SDK-only.

---

## 0. Test fixtures

### 0.1. Generate `examples/sample-bundle/`
- **What:** Land a committed sample bundle under `examples/sample-bundle/`
  that exercises every CUA rule (no_state_change, verifier_disagrees,
  replay_diff at minimum). Write a `scripts/build_sample_bundle.py` that
  regenerates it deterministically.
- **Why:** Diagnostic tests can't assert real behaviour against the
  rules engine until a fixture exists.
- **Done when:**
  - Re-add `test_bundle_context_lazy_load`,
    `test_engine_emits_no_state_change_on_sample`,
    `test_engine_emits_verifier_disagrees_on_sample`,
    `test_replay_diff_finds_fixture` against the committed bundle.
  - CI runs them without skips.
- **Touches:** `examples/sample-bundle/**`, `scripts/build_sample_bundle.py`,
  `tests/test_diagnostics.py`.
- **Depends on:** none.

---

## A. Storage backends

### A1. S3Store hardening
- **What:** `S3Store` exists but is a stub. Wire up real `boto3.upload_fileobj`,
  preserve the atomic-write semantics (multipart upload + finalise) and
  the path-stable layout from §4.1 / §4.8 of SPEC.md.
- **Why:** Operators want to write straight to S3 without a sidecar
  uploader.
- **Done when:**
  - Round-trip test: write a session, read manifest + every screenshot
    back via `boto3.list_objects_v2`, assert byte equality with the
    in-memory artefacts.
  - `botocore` is an extras-marker dep (`pip install augur-sdk[s3]`),
    NOT a runtime dep.
  - Partial-upload failure is observable in `manifest.json` `missing[]`.
- **Touches:** `src/augur_sdk/storage.py`, `tests/test_storage.py`,
  `pyproject.toml`.
- **Depends on:** none.

### A2. GCSStore
- **What:** New backend `GCSStore` for Google Cloud Storage. Mirror the
  `S3Store` contract.
- **Why:** Parity for GCS-first shops.
- **Done when:** same round-trip test as A1, on a GCS fixture (or
  `gcsfs` in-memory).
- **Touches:** `src/augur_sdk/storage.py`, `tests/test_storage.py`,
  `pyproject.toml` (extras `[gcs]`).

### A3. Pluggable `Store` registry
- **What:** Resolve a `Store` from a URI prefix:
  `local://`, `s3://`, `gs://`. Entry-point group `augur_sdk.stores`.
- **Why:** Operators (and the CLI later) pick storage by URI without
  importing the class.
- **Done when:** `from_uri("s3://bucket/prefix")` returns a working
  `S3Store`; unknown scheme raises `ValueError`.
- **Touches:** `src/augur_sdk/storage.py`, new `_registry.py`,
  `tests/test_storage_registry.py`.
- **Depends on:** A1.

---

## B. Capture & redaction

### B1. Configurable redaction policies via entry-points
- **What:** Allow third parties to register a `RedactionPolicy` under
  entry-point group `augur_sdk.redaction_policies`. SDK picks by id.
- **Why:** Enterprise teams want HIPAA / PII-Plus policies without
  forking.
- **Done when:**
  - `DebugSession(redaction_policy_id="acme.pii_plus")` resolves and
    runs that policy.
  - Unknown id raises with a list of available ids.
  - `tests/test_redaction.py` exercises a fake third-party policy.
- **Touches:** `src/augur_sdk/redaction.py`, `tests/test_redaction.py`.

### B2. `capture_mode="diff"` — only changed regions
- **What:** New capture mode that screenshots only when a perceptual
  hash exceeds threshold from the previous frame. Falls back to full
  screenshot every N steps.
- **Why:** Cuts bundle size 10–20× on slow-changing UIs.
- **Done when:**
  - Bundle for a synthetic "loading spinner" CUA is < 25% the size of
    `capture_mode="full"`.
  - First step is always captured; cadence floor is configurable.
- **Touches:** `src/augur_sdk/capture.py`, `src/augur_sdk/models.py`
  (extend `CaptureMode` literal), schema bump (coordinate with
  upstream).

### B3. Streaming-friendly `record_observation` chunking
- **What:** When an observation > 256 KiB JSON is recorded, chunk into
  multiple POSTs with an `observation_chunk` envelope.
- **Why:** Big DOM dumps currently buffer in memory and stall the
  heartbeat thread.
- **Done when:** Posting a 5 MiB observation does not delay the next
  heartbeat by more than 1 s (measured).
- **Touches:** `src/augur_sdk/streaming.py`, `src/augur_sdk/session.py`.

---

## C. Networking & streaming

### C1. Outbound HTTP proxy support
- **What:** Respect `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` in
  `StreamingSink`. Add `dsn.proxy = ...` override.
- **Why:** Customers behind corporate proxies can't ship today.
- **Done when:** Setting `HTTPS_PROXY` to a local mitmproxy receives
  every POST; `NO_PROXY` exempts the configured host.
- **Touches:** `src/augur_sdk/streaming.py`,
  `tests/test_streaming_proxy.py`.

### C2. Local-buffer fallback on extended outage
- **What:** When the sink's POSTs fail for > `flush_interval × 6`, spill
  to `~/.cache/augur/spool/<dsn-fp>/` and replay on success.
- **Why:** A flaky VPN currently drops minutes of run telemetry on the
  floor.
- **Done when:**
  - Sim test: block POSTs for 90 s mid-session, then unblock. All
    pre-block records arrive at the server.
  - Spool directory is gone after replay.
- **Touches:** `src/augur_sdk/streaming.py`, new `_spool.py`,
  `tests/test_streaming_spool.py`.
- **Depends on:** must NOT violate SPEC.md §4.3 (no exceptions raised).

### C3. mTLS / client-cert support on the DSN
- **What:** Accept `client_cert` / `client_key` paths on the `DSN` or
  via env vars `AUGUR_CLIENT_CERT` / `AUGUR_CLIENT_KEY`.
- **Why:** Some operators front Augur with mTLS at the LB.
- **Done when:** Sink presents cert to a self-signed test server and
  succeeds.
- **Touches:** `src/augur_sdk/streaming.py`.

---

## D. Diagnostics

### D1. Rule pack discovery via entry-points
- **What:** Discover rule packs from the entry-point group
  `augur_sdk.rule_packs`. `load_pack("foo")` walks installed packs.
- **Why:** Frameworks (Playwright, Stagehand, Mantis) want to ship
  their own pack alongside their package.
- **Done when:** Installing a sibling package that registers a pack
  exposes it via `load_pack("sibling.foo")`; tests cover dedupe and
  precedence.
- **Touches:** `src/augur_sdk/diagnostics.py`,
  `tests/test_diagnostics.py`.

### D2. Severity-aware diff between two bundles
- **What:** `diagnose_pair(bundle_a, bundle_b)` highlights findings
  that appear in B but not A. Useful for regression-checking a fix.
- **Why:** Today users diff two `findings.json` files by hand.
- **Done when:** `diagnose_pair(prev, curr)` returns a list of "new",
  "resolved", "promoted" finding deltas, with stable ordering.
- **Touches:** new `src/augur_sdk/diagnostics_diff.py`, tests.

### D3. Repro fixture exporter
- **What:** `session.replay_fixture()` already exists; add an exporter
  that writes a self-contained pytest file that loads the fixture and
  re-runs the agent's `decide()` against the captured observation,
  asserting the captured grounding coordinate.
- **Why:** Lets users land regression tests straight from a bundle.
- **Done when:** Generated pytest file runs green against the bundled
  fixture out-of-the-box; failing the agent under test produces a
  meaningful diff.
- **Touches:** `src/augur_sdk/replay.py`,
  `tests/test_replay_export.py`.

---

## E. Adapter ergonomics

### E1. Contract test harness for third-party adapters
- **What:** A pytest plugin that, given an `Adapter` instance + a tiny
  golden input, asserts the produced bundle round-trips through schema
  validation, has stable step ordering, and respects the redaction
  policy.
- **Why:** Adapter authors today copy the Mantis adapter tests by hand.
- **Done when:** A third-party adapter package can `pip install
  augur-sdk[adapter-tests]` and import the fixtures.
- **Touches:** `src/augur_sdk/testing/adapter_contract.py` (new),
  `pyproject.toml` (`[adapter-tests]` extra), `tests/`.

### E2. JSONL streaming converter for adapters
- **What:** Adapter helper `iter_steps_from_jsonl(path)` so adapter
  authors don't have to load 10 GB of trace into memory.
- **Why:** Large Mantis traces OOM today.
- **Done when:** Round-trip of a 100k-step synthetic trace stays under
  200 MiB RSS.
- **Touches:** new `src/augur_sdk/adapter_utils.py`, tests.

---

## F. Tooling & DX

### F1. Type stubs for downstream consumers
- **What:** Ship `py.typed` and audit public API for `Protocol` /
  `Final` / strict typing. Run `mypy --strict` in CI.
- **Why:** Internal CUAs in TS-influenced shops want strict types from
  the boundary.
- **Done when:** `mypy --strict src/augur_sdk` is clean on 3.11 / 3.12
  / 3.13, gated in `.github/workflows/ci.yml`.
- **Touches:** `pyproject.toml`, `src/augur_sdk/py.typed` (new),
  type-ignore audit across the package.

### F2. Conformance test against the upstream schemas
- **What:** Nightly CI job that fetches the latest schemas from
  `mercurialsolo/augur@main:packages/schema/...` and diffs them against
  the vendored ones. Fail fast if drift is detected.
- **Why:** Today a schema bump upstream silently breaks the SDK until
  someone notices.
- **Done when:** Drift produces an actionable diff in CI logs; greenness
  reflects in-sync state.
- **Touches:** new `.github/workflows/schema-drift.yml`,
  `scripts/check_schema_drift.py`.

### F3. `augur-sdk doctor` CLI command
- **What:** A small `python -m augur_sdk.doctor` (or
  `augur-sdk-doctor`) that probes the DSN, reports schema_version
  compatibility, and surfaces the active redaction policy.
- **Why:** First-time integrators don't know why nothing is showing up
  in the viewer. Sentry's `sentry-cli send-event` is the model.
- **Done when:** Running it with a bad DSN explains why; with a good
  DSN, posts a synthetic step that appears in the viewer.
- **Touches:** new `src/augur_sdk/doctor.py`,
  `pyproject.toml` (`project.scripts` entry).

### F4. Wheels-only sdist
- **What:** Publish `augur-sdk` as a pure-Python wheel; verify the
  sdist contains schemas and is reproducible.
- **Why:** Customers in air-gapped envs need an sdist they can audit.
- **Done when:** `pyx tar tf` shows `_schema/json/*.schema.json`; SHA
  is stable across two CI runs.
- **Touches:** `pyproject.toml`, `MANIFEST.in` (if needed),
  `.github/workflows/release.yml`.

---

## G. Docs & examples

### G1. End-to-end Browser-Use adapter cookbook
- **What:** A docs page + example script integrating Augur with
  Browser-Use, mirroring `docs/integrations/playwright.md`.
- **Why:** Browser-Use is a common CUA framework.
- **Done when:** Following the cookbook end-to-end produces a bundle
  that opens cleanly in the viewer.
- **Touches:** `docs/integrations/browser-use.md` (new),
  `examples/capture_from_browser_use.py` (new).

### G2. Recipe: regression-test a specific failure class
- **What:** A docs page that walks through `bundle → diagnose →
  replay_fixture → pytest` for the
  `incorrect_target_screenshot_grounded` failure class.
- **Why:** Closes the loop on the "evidence package" pitch.
- **Done when:** A reader who has never used Augur can run the recipe
  in < 10 minutes.
- **Touches:** `docs/recipes/regression-test-a-failure-class.md` (new).

### G3. Migration guide from "raw logs" to Augur
- **What:** Side-by-side guide showing the shape of typical
  `print()` / `logger.info(...)` traces and how to map them to
  `DebugSession` calls. Aimed at teams shipping their first integration.
- **Why:** Removes the "where do I even start" friction.
- **Touches:** `docs/recipes/from-raw-logs-to-augur.md` (new).

---

## I. Step semantics & iteration accounting

The SDK currently records one `StepTrace` per canonical step and collapses
any re-emission with the same `step_index`. Producers (Mantis especially)
think in *iterations* — brain-loop turns inside a single canonical step —
and want to surface that cardinality without leaking decision-event
internals to every consumer. These two issues unlock that.

### I1. `step_iterations` field on `StepTrace`
- **What:** Add an optional `step_iterations: int` field to `StepTrace`
  (default treated as 1 when absent). Ship a producer-side helper
  `Session.record_step_iteration(step_id_or_index, ...)` that appends an
  iteration under an existing canonical step and bumps the counter.
  `record_step()` keeps its existing single-emission semantics.
- **Why:** Consumers (Augur viewer runs-list, OTel export, CSV dumps)
  want to show *"7 (175)"* — 7 canonical steps with 175 iterations
  underneath — without crawling decision events. Today the steps
  column collapses to canonical count and loses the *"the model
  thrashed for 30 turns inside step 3"* signal that triagers care
  about. Producer-owned semantics is the right surface: only the
  producer knows what a "turn" means for its agent loop.
- **Done when:**
  - `StepTrace` TypedDict carries optional `step_iterations: int`.
  - JSON Schema in `schemas/step-trace.json` (or equivalent) updated
    + schema version bumped.
  - `Session.record_step_iteration()` exists, takes a step_id or
    step_index + an iteration payload, increments
    `step_iterations` atomically on the canonical step.
  - Round-trip test: emit 1 canonical step + 5 iterations, close
    bundle, reload — `step_iterations == 6`, all 6 iteration
    payloads addressable.
  - `record_step()` for a step_index that already exists emits a
    `DeprecationWarning` pointing at `record_step_iteration`.
  - `CHANGELOG.md` + `SPEC.md` note the schema bump and the new API.
- **Touches:** `src/augur_sdk/models.py`, `src/augur_sdk/recorder.py`,
  `src/augur_sdk/session.py`, `src/augur_sdk/bundle.py`,
  `tests/test_recorder.py`, `tests/test_bundle_roundtrip.py`,
  `CHANGELOG.md`, `SPEC.md`, `schemas/*.json`.
- **Depends on:** I2 (otherwise iterations collapse into one
  storage record and the counter is the only signal that survives).

### I2. Key recorder + bundle writer by `step_id`, not `step_index`
- **What:** Make `Recorder._steps` and `bundle._step_path()` key by
  `step_id` instead of `step_index`. Today both collapse multiple
  emissions sharing a `step_index` into a single in-memory slot and
  single on-disk file (`steps/0007.json`), silently overwriting
  earlier iterations. The producer-side fix in `mantis-cua#660`
  already makes `step_id` unique per emission — the SDK just
  ignores it.
- **Why:** Without this, I1's `step_iterations` counter is the
  *only* surviving artifact of every iteration past the first; the
  per-iteration payloads, decision events, and screenshots are
  lost to overwrite. #660's behavior change is currently a no-op
  end-to-end because the storage layer collapses what the producer
  carefully kept distinct.
- **Done when:**
  - `Recorder._steps` keyed by `step_id` (step_index still
    derivable for ordering / first-failed lookup).
  - `bundle._step_path()` produces a non-colliding path —
    `steps/<NNNN>/<short_id>.json` (per-iteration sub-files under a
    canonical-step dir) is preferred because it preserves the
    "scan steps/ to count canonical steps" invariant that the
    Augur server's live aggregator relies on
    (`store.py:849-856`).
  - Two `record_step()` calls with same step_index, different
    step_id → two on-disk files, both addressable on reload.
  - Existing single-emission bundles round-trip byte-identical.
  - Augur server (downstream consumer) verified to read both old
    and new layouts without code change.
- **Touches:** `src/augur_sdk/recorder.py`, `src/augur_sdk/bundle.py`,
  `src/augur_sdk/session.py`, `tests/test_recorder.py`,
  `tests/test_bundle_roundtrip.py`, `SPEC.md` (§4 layout).
- **Depends on:** none. Ship before I1 so I1's iteration payloads
  actually persist.

---

## H. Future / 1.0 blockers

These are bigger and need design first. Open as RFCs in the upstream
repo before sizing into the SDK.

- **H1. Async-native `DebugSession`** — `async with DebugSession(...)`
  that uses `httpx` instead of `urllib3`. Coordinate with C1/C2.
- **H2. OpenTelemetry exporter for `cua.*` spans** — surface step
  boundaries as OTel spans so platform teams can correlate with
  existing tracing.
- **H3. TypeScript SDK port** — separate package, separate repo,
  consumes the same vendored schemas.
- **H4. Multi-language schema validators** — the JSON Schemas are the
  contract, but a Rust validator (via `pyo3`) would speed up
  large-bundle `close()` by 10×.

---

## How to pick one

1. Skim `SPEC.md` so you know which invariants you cannot cross.
2. Pick a bullet from §A–G — those are PR-shaped.
3. Check the **Touches** line — if another open issue overlaps, ping
   in the issue thread before starting.
4. PR title: `[<area-code>] <issue title>` (e.g. `[A1] S3Store
   hardening`). Link the issue in the body.

If a section here feels stale, edit it in the same PR that ships the
change — this file is part of the repo, not a wiki.
