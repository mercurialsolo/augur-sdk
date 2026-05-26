# Changelog

All notable changes to `augur-sdk` are recorded here. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/), with semver applied per
`docs/versioning.md` upstream (`MAJOR.MINOR.PATCH`; pre-1.0 minors may break).

## [Unreleased]

## [0.6.1] — 2026-05-25

### Admit augur-schema 0.5.0 + 0.6.0 (closes #44)

Bump the `augur-schema` upper bound from `<0.5` to `<0.7` so consumers
can install the SDK alongside the new server-side schemas:

- **augur-schema 0.5.0** — adds `reward_aggregate.schema.json` (the
  per-formula sidecar written by the new `POST /api/v1/runs/{id}/reward`
  endpoint).
- **augur-schema 0.6.0** — adds `trajectory_preference.schema.json` (the
  pairwise-review records written by `POST /api/v1/preferences`).

Both are additive, server-side **outputs** the SDK doesn't produce —
the SDK just needs to not block consumers that want to install the
newer schema package in the same env (e.g. an RL trainer hitting both
the run-sampling endpoints and the SDK-driven worker bundles). No
producer-side behavior change; every shape the SDK does validate
against (manifest, debug_session, step_trace, modelio, side_effect,
branch_context, captured_versions, task_spec, subgoal, outcome_record,
judge_decision, env_fingerprint, preference, observation) is unchanged
in 0.5.0 / 0.6.0.

Full suite 277 green under augur-schema 0.6.0; no SDK code touched.

## [0.6.0] — 2026-05-25

### Producer support for augur-schema 0.4.0 — RL training metadata (closes #41)

`augur-schema 0.4.1` adds the metadata that makes Augur a portable
**online-RL training platform**: session-level `TaskSpec`, per-step
`subgoals_completed`, `group_id` for grouped-rollout RL (GRPO),
`verdict.should_stop` + `verdict.uncertainty`, and a documented
canonical `score_components` vocabulary. 0.6.0 surfaces those cleanly
on the SDK so producers don't have to poke at raw schema dicts.

- **`DebugSession(task_spec=..., task_spec_id=..., group_id=...)`** —
  three new constructor kwargs. `task_spec` is the full structured
  definition (instruction, max_steps, prohibited_actions,
  success_conditions, subgoals, reset_state_id, task_seed, env_id);
  `task_spec_id` is the shortcut for producers maintaining an
  external task-spec library; `group_id` correlates rollouts
  spawned by the same training-loop batch.
- **`session.set_task_spec(...)`** / **`set_task_spec_id(...)`** /
  **`set_group_id(...)`** — setters for post-construction adjustment.
- **`group_id` auto-propagates to every recorded step.** Mirrors the
  branch_context propagation pattern from 0.2.1 — RL pipelines can
  group siblings by `step.group_id` without joining back to the
  session record.
- **`session.record_subgoal_completion(step_index, subgoal_id, completion)`**
  — patches `step.subgoals_completed` with the canonical
  `{subgoal_id, completion, first_completed_at_step?}` entry. The
  SDK tracks first-time-1.0 across the session and auto-fills
  `first_completed_at_step` so producers don't need bookkeeping.
  Warns when `subgoal_id` isn't declared in `task_spec.subgoals`
  (the schema still accepts unknown ids; warn is producer-facing).
- **`session.set_loop_detected(step_index, value=True)`** — stamps
  `step.loop_detected`. Producers SHOULD set this when their own
  state-repetition check (typically observation phash adjacency)
  flags a step; consumers then skip rediscovering loops.
- **`session.set_score(..., should_stop=..., uncertainty=...)`** —
  the existing setter gains two RL kwargs. `should_stop` is the
  producer-side recommendation that the agent halt here (positive =
  task complete, negative paired with high `safety_risk` /
  `loopiness` = continued action unsafe / pointless). `uncertainty`
  is the verdict-level confidence summary in [0, 1].
- **`ScoreComponents` canonical-key constants** — new module
  (`augur_sdk.rewards`) and re-export. Producers can write
  `ScoreComponents.PROGRESS` instead of typing `"progress"`,
  nudging cross-producer training toward the documented vocabulary
  without rejecting adapter-specific keys (the schema is open via
  `additionalProperties: true`).
- **`TaskSpec`, `Subgoal`, `SuccessCondition`, `SubgoalCompletion`**
  TypedDicts added to `augur_sdk.models` and re-exported. Pass dicts
  directly to the SDK — no construction step.
- **Schema dep bumped to `augur-schema>=0.4.1,<0.5`.** 0.4.1 fixes
  an upstream loader bug where `task_spec.schema.json` and
  `subgoal.schema.json` shipped in the wheel but weren't registered
  with `_SCHEMA_FILES`, making `$ref: task_spec.schema.json` from
  `debug_session.schema.json` unresolvable. The SDK can't usefully
  pin to 0.4.0.

Additive — sessions that don't touch any of the new surface emit
bundles indistinguishable from 0.5.x output.

### Tests

- `tests/test_task_spec.py` (22 tests) — TaskSpec on session record
  + the task_spec_id shortcut; post-construction setters; missing-
  instruction and duplicate-subgoal_id guards; group_id propagation
  (constructor, late-set, explicit-step-override-wins);
  record_subgoal_completion happy path + auto
  `first_completed_at_step` across multiple steps + clamping +
  unknown-id warning + no-task_spec quiet path + same-subgoal
  last-write-wins; set_loop_detected; set_score should_stop +
  uncertainty (incl. clamping); ScoreComponents constants stay in
  sync with the canonical set; end-to-end round-trip validating
  against `augur-schema 0.4.1`; back-compat (no new fields → still
  valid). **Full suite: 277 tests, all green.**

## [0.5.0] — 2026-05-25

### Per-token logprob capture in modelio.response (closes #40)

Augur-captured bundles are already strong for behavior cloning, outcome
/ process reward modeling, counterfactual off-policy learning, DPO, and
verifier / judge training. The one paradigm they couldn't drive is
**policy-gradient methods (PPO / GRPO and friends)** because those need
behavior-policy probabilities for importance weighting. DPO /
preference learning also benefits — without captured logprobs,
consumers have to recompute them from the trajectory at training time,
which is expensive and lossy.

0.5.0 wires the SDK to populate the new `response.logprobs` field
shipped in `augur-schema 0.3.3`.

- **`DebugSession(capture_logprobs=True)`** — new producer-level
  opt-in. **Off by default** because logprobs roughly double the
  response payload size on OpenAI and add a small cost on some
  providers. Adapters read `session.capture_logprobs` to decide
  whether to pass `top_logprobs=N` on outbound model calls.
- **Empty-vs-absent semantics in `record_modelio`.** When
  `capture_logprobs=True` and the producer didn't stamp anything on
  the response, the SDK defaults `response.logprobs = []` so
  consumers can tell "requested but vendor returned nothing" (empty
  array) from "not requested" (field absent / null). Producers that
  DID receive logprobs put them on `response.logprobs` themselves
  and the SDK passes them through verbatim.
- **`ModelApiAdapterBase.extract_logprobs_from_response(response)`**
  — new static helper. Maps OpenAI Chat Completions / Responses
  (`choices[].logprobs.content[]`) and Anthropic Messages
  (`content[].logprobs[]`) shapes to the canonical
  `[{token, token_id, logprob, top_alternatives}]` list. Returns
  `None` when the response has no recognisable logprob block. Same
  pattern as `extract_reasoning_from_response` from 0.1.14.
- **Context-aware redaction.** The default policy masks bare `token`
  keys (intended for API/bearer tokens), but in a logprob entry
  `token` is the decoded model output. The policy now skips the
  mask when the parent dict carries a numeric `logprob` — preserving
  the training signal while the generic rule still defends elsewhere.
- **Schema dep bumped to `augur-schema>=0.3.3,<0.4`** to pick up the
  new optional `response.logprobs` field. Bundles emitted by 0.4.x
  against the old schema continue to validate — the field is
  additive.

### Tests

- `tests/test_logprobs.py` (14 tests) — session opt-in flag, the
  empty-vs-absent semantics in `record_modelio`, schema round-trip
  for canonical entries, OpenAI / Anthropic vendor-mapping shapes,
  edge cases (empty choices, `top_logprobs=0`, vendor-surfaced
  `token_id`), and the redaction carve-out. Full suite: 255 tests,
  all green.

## [0.4.0] — 2026-05-25

### Fanout-orchestrator helper + grouping contract (closes #38)

When a producer fans out work across N sibling sessions that share a
`branch_context.parent_run_id`, the viewer's job is to group them
under a single parent row — replay branches and fanout workers reach
the platform through the same shape and deserve the same treatment.
0.4.0 pins the contract and ships the producer-side ergonomic.

- **`DebugSession.open_orchestrator(...)`** — new classmethod. Opens
  a parent-only session that carries aggregate tags / costs /
  metadata (phase counts, fanout strategy, total budget) but records
  no steps of its own. `record_step`, `record_step_iteration`, and
  `attach_observation` raise `RuntimeError` on these sessions —
  record steps on the children. `set_costs`, `add_tag`,
  `set_live_endpoints`, `finalize_outcome` and the rest of the
  session-level helpers work normally.
- **Session-shape marker via tags.** Orchestrator sessions land with
  `tags["augur.session_type"] = "orchestrator"` (exported as
  `augur_sdk.ORCHESTRATOR_TAG_KEY` / `_VALUE`) so the server can
  render them as parent rows (aggregate stats, no step list). The
  marker rides on `session.tags`, so no schema bump is needed —
  every prior bundle continues to validate.
- **`session.is_orchestrator`** — new property that's True for
  sessions opened via `open_orchestrator(...)`, False otherwise.
  Useful for callers asserting the mode after construction.
- **Grouping contract pinned in docs.** New page at
  [concepts/fanout-grouping.md](https://mercurialsolo.github.io/augur-sdk/concepts/fanout-grouping/)
  spec'ing the rule: sessions sharing `branch_context.parent_run_id`
  are siblings of one logical orchestrator; viewers SHOULD group them
  under a parent row (explicit when the orchestrator session exists,
  synthetic otherwise). Covers both the replay-branch and fanout-worker
  cases.
- **Convenience kwargs** — `session_name` and `tenant_id` on
  `open_orchestrator(...)` land in `session.tags` under those keys.
  Explicit `tags={...}` entries win, so callers that already use those
  keys keep their values.

Additive, no schema touch, no behaviour change for producers that
don't call `open_orchestrator(...)`. Paired with the server-side
runs-list grouping shipped in `mercurialsolo/augur#138`.

### Tests

- `tests/test_orchestrator_session.py` (10 tests) — tag stamping,
  empty-step bundle validates, the three forbidden methods raise,
  `set_costs` + `add_tag` round-trip, `session_name`/`tenant_id`
  convenience, explicit-tags precedence, and a grouping-contract
  end-to-end fixture (one parent + two children that share
  `parent_run_id`). Full suite: 241 tests, all green.

## [0.3.1] — 2026-05-24

### `set_costs` now streams live (closes #34)

`DebugSession.set_costs(...)` no longer waits for `close()` to surface the
run-level cumulative cost. With a `dsn` configured, every call now PUTs
the cumulative dict to `/api/v1/runs/{run_id}/costs` immediately so the
Augur viewer's Runs-list COST column tracks the producer's running total
in real time.

Fixes the non-monotonic UI value caused by 0.3.0's per-iteration step
PUTs overwriting a canonical step's `costs` field — sum-over-steps on
the viewer was no longer monotonic. Cumulative cost is the right surface
because the producer already maintains it (budget caps need it), cost
is monotonic by construction, and cumulative emissions survive dropped
events where deltas don't.

Paired with the server-side endpoint shipped in `mercurialsolo/augur#137`.

- **`StreamingSink.put_session_costs(costs)`** — new method. Routes
  through the shared `_request_with_retry` helper from 0.2.2 (#27),
  so the 429+`Retry-After` contract on the new endpoint is honoured
  for free.
- **`DebugSession.set_costs(...)`** — patches the in-memory dict as
  before, then PUTs the cumulative if any dimension was set. No PUT
  fires for `set_costs()` with no kwargs (defensive callers don't
  spam the ingest queue).
- **Server compatibility** — falls back to bundle-only behavior
  against pre-#137 servers (the PUT returns 404, logged at DEBUG by
  the existing `_post_json` error path; the local bundle still owns
  `session.costs` on close).
- **No schema change** — `debug_session.costs` already exists in
  `augur-schema 0.3.2`; the PUT body is just that sub-object.

### Tests

- `tests/test_live_session_costs.py` (8 tests) — wire format on the
  new route, empty-payload no-op, 429 retry, double-429 drop, the
  cumulative-not-delta contract across multiple `set_costs` calls,
  no-kwargs no-op, no-DSN local-only path, and a regression guard
  that `close()` still writes `session.costs` to trace.json. Full
  suite: 231 tests, all green.

## [0.3.0] — 2026-05-24

### Step-iteration semantics (closes #30, #31)

Brain-loop iterations under a canonical CUA step are now first-class.
Producers can emit `N` canonical steps with `M` total iterations and
consumers (Augur viewer runs-list, OTel export, CSV dumps) render
`"N (M)"` without crawling decision events.

- **Schema bump to `augur-schema 0.3.2`.** `step_trace.schema.json`
  gains an optional `step_iterations: int` field (minimum 1, default
  semantics when absent: 1). Additive; every prior 0.1.x / 0.2.x
  bundle continues to validate.
- **`EventRecorder` keyed by `step_id`** (closes #30). Multiple
  `record_step()` emissions sharing a `step_index` no longer collapse
  into one in-memory slot. The first `step_id` to land for a given
  `step_index` is the canonical step; subsequent emissions with new
  `step_id`s are iterations and live alongside it. Re-recording under
  an existing `step_id` is still last-write-wins (the common
  `running` → `succeeded` update path).
- **Bundle path layout follows the keying.** Single-emission steps
  keep the flat `steps/<NNNN>.json` path (byte-identical with
  pre-0.3.0 bundles). Steps with iterations move to
  `steps/<NNNN>/<short_id>.json` for each iteration including the
  canonical — `<short_id>` is the first 8 hex chars of
  `sha256(step_id)`, deterministic and filesystem-safe. The
  `scan steps/ → canonical-step-count` invariant the Augur server's
  live aggregator relies on is preserved (one entry per
  canonical step, file *or* directory).
- **`DebugSession.record_step_iteration(step_id_or_index, iteration)`**
  (closes #31). Producer-side helper that appends an iteration under
  an existing canonical step and atomically bumps the canonical's
  `step_iterations` counter. The canonical reference accepts either
  a `step_id` (for explicit linkage) or a `step_index` (for
  Mantis-style loops that always share the canonical slot). Each
  iteration MUST carry a distinct `step_id`.
- **`record_step()` for an existing `step_index` with a new `step_id`
  now emits a `DeprecationWarning`** pointing at
  `record_step_iteration()`. The call still succeeds and the
  iteration is recorded — preserves working-software for legacy
  producers while signaling the migration.
- **`validate_bundle()`** walks both layouts via `rglob("*.json")`
  so a bundle with iterations validates the same way as a flat one.
- **Streaming.** Each iteration fires a PUT to
  `/runs/{run_id}/steps/{idx}` with the iteration's payload AND a
  follow-up PUT of the canonical step (now carrying the updated
  `step_iterations` counter), so the live runs-list reflects the
  new count without waiting for `close()`.

### Tests

- `tests/test_step_iterations.py` (9 tests) — single-emission keeps
  flat layout, same-step_id update is idempotent, distinct
  step_ids emit two on-disk files under the canonical-step dir and
  warn, `record_step_iteration` bumps the counter, accepts
  canonical step_id, refuses without a canonical or on id
  collision, no warning for new step_index, and manifest
  signatures cover iteration paths. Full suite: 223 tests, all
  green.

### Downstream consumer status

The Augur server already reads `step_iterations` when present and
bubbles `iteration_count` to the runs-list API. Viewer renders `N`
when iterations == steps and `N (M)` when iterations > steps. Both
ship behind the absence-tolerant default, so this SDK change lands
without consumer coordination.

## [0.2.2] — 2026-05-23

### StreamingSink honours 429 + Retry-After (closes #27)

`augur#114` made the high-frequency ingest endpoints async on the server
side. The happy path now returns `202 Accepted` (already handled — any
2xx counted as success) and a saturated ingest queue returns
`429 Too Many Requests` with `Retry-After: <seconds>`. Before 0.2.2 the
SDK debug-logged the 429 and dropped the step — the producer thought the
write landed; the server never got it.

- **Shared `_request_with_retry` helper.** Every HTTP call site now
  routes through one place. On 429 it sleeps the parsed `Retry-After`
  value, reissues the request exactly once, and if the second attempt
  also 429s emits a `WARNING` (`"augur ingest dropped after retry: …"`)
  and returns. Single retry only — no unbounded loop, no SDK-side
  buffer. The local bundle on disk remains authoritative.
- **Endpoints covered.** `_post_json` (steps / trace / events /
  side-effects / reasoning / outcomes / eval-candidates /
  judge-decisions / logs), `_post_modelio_request`,
  `_post_multipart` (screenshots), and `_send_heartbeat` — all share
  the same retry behaviour. Modelio's existing 403-latch (tenant
  opt-in) is preserved across the retry path.
- **`_parse_retry_after` helper.** Parses augur's integer
  delta-seconds form, falls back to `1.0s` on HTTP-date / missing /
  garbage, and clamps the result to `[0, 30]` so a malformed or
  hostile header cannot park a background thread.
- **Idempotency.** Server endpoints are idempotent on
  `(run_id, step_index)` for steps, on `(run_id, manifest)` for
  trace, and heartbeats are at-most-once by nature, so a single retry
  after 429 never double-writes.

### Tests

- `tests/test_streaming_backpressure.py` (16 tests) — `_parse_retry_after`
  unit tests (integer / float / whitespace / missing / garbage /
  negative-clamp / huge-clamp), `_post_json` 202 pass-through, 429 →
  202 retry, double-429 drop + warn, sleep value verification,
  default-sleep when `Retry-After` is missing, plus parallel retry
  coverage for `_post_multipart`, `_send_heartbeat`, and modelio
  (including the modelio 403-latch interaction after a 429 retry).
  Full suite: 214 tests, all green.

## [0.2.1] — 2026-05-23

### Branching replay — producer-side execution (closes #25)

`DebugSession` already accepted a `branch_context` kwarg in 0.1.14
(per `augur-schema 0.3.1`), but no producer code path drove it.
0.2.1 adds the high-level constructor.

- **`DebugSession.branch_from(parent_run_id, branch_point_step_index,
  mutated_axis, mutation, ...)`** — classmethod that returns a child
  session pre-stamped with the parent linkage. Counterpart to platform
  `mercurialsolo/augur#91` (closed); operator surface declared the
  branch, this lets the SDK actually execute it.
- **Modes** (`mode=`):
  - `replay` — load steps `[0, branch_point_step_index)` from a
    parent bundle (`parent_bundle=<path>`) into the new session,
    copying pre/post screenshot bytes verbatim. The producer
    continues fresh from the branch point.
  - `sandbox` — stamp `branch_context` only; the producer executes
    from scratch against a live target.
  - `auto` (default) — picks `sandbox` when `mutated_axis="action"`
    (action changes break the deterministic-prefix assumption per
    SPEC §10), `replay` otherwise.
- **Refuses** `mode="replay"` when `mutated_axis="action"` — replay
  would lie about what the agent did since the parent's downstream
  observations no longer reflect what the new agent will see.
  Per-axis safety enforced at construction time, not at bundle write.
- **`branch_id` and child `run_id`** default to
  `f"{parent_run_id}:branch:<short-uuid>"` (per
  `branch_context.schema.json` convention) — callers can override
  either independently.
- **`session.branch_mode`** accessor exposes the resolved mode
  (`"replay"`, `"sandbox"`, or `None` for production runs).

### Tests

- `tests/test_branch_from.py` (18 tests) — sandbox / replay / auto
  resolution, prefix loading + screenshot copy from parent bundle,
  replay-refuses-action-mutation, axis enum validation, branch_id
  generation, **kwargs pass-through. Full suite: 198 tests, all green.

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

