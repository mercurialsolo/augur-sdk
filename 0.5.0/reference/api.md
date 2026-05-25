# API reference

Every public symbol the SDK exports. Importable from `augur_sdk`.

## `DebugSession`

The capture controller. Use as a context manager.

```python
class DebugSession:
    def __init__(
        self,
        *,
        run_id: str,
        client_name: str,
        out_dir: str | Path,
        client_version: str | None = None,
        client_git_sha: str | None = None,
        capture_mode: CaptureMode | str | None = None,
        debug_session_id: str | None = None,
        redaction_policy: RedactionPolicy | None = None,
        store: Store | None = None,
        tags: dict[str, str] | None = None,
        started_at: str | None = None,
        dsn: str | None = None,
        capture_logprobs: bool = False,
    ): ...

    def record_step(self, step: StepTrace) -> None: ...
    def record_step_iteration(
        self,
        step_id_or_index: str | int,
        iteration: StepTrace,
    ) -> None: ...
    def record_event(self, event: DecisionEvent) -> None: ...
    def attach_observation(
        self, *, step_index: int, kind: Literal["pre", "post"], png_bytes: bytes,
    ) -> str: ...
    def set_status(self, status: str) -> None: ...
    def add_tag(self, key: str, value: str) -> None: ...
    def set_live_endpoints(
        self, *, status_url: str | None = None,
        video_url: str | None = None, reasoning_url: str | None = None,
    ) -> None: ...
    def close(self, status: str | None = None) -> BundleManifest: ...
```

### Keyword arguments

| Argument            | Default                                | Purpose                                                                  |
|---------------------|----------------------------------------|--------------------------------------------------------------------------|
| `run_id`            | (required)                             | Adapter-supplied run id; appears in every record                         |
| `client_name`       | (required)                             | Your adapter / runtime name (`myagent`, `mantis`, …)                     |
| `out_dir`           | (required)                             | Where the bundle lands on disk                                           |
| `client_version`    | None                                   | Free-form; surfaces in the viewer's run header                           |
| `client_git_sha`    | None                                   | Used by diagnostics to attribute regressions                             |
| `capture_mode`      | `AUGUR_CAPTURE_MODE` env var, else `off` | See [concepts/capture-modes.md](../concepts/capture-modes.md)          |
| `debug_session_id`  | auto-generated `dbg_<uuid12>`          | Override only if you need a stable id (e.g. resume)                      |
| `redaction_policy`  | `DefaultRedactionPolicy()`             | See [concepts/redaction.md](../concepts/redaction.md)                    |
| `store`             | `LocalFSStore(out_dir)`                | Swap for `S3Store(...)` (stub today) or your own                         |
| `tags`              | `{}`                                   | Free-form key/value, surfaces in viewer filters                          |
| `started_at`        | now (UTC ISO-8601)                     | Override when bridging a post-hoc adapter                                |
| `dsn`               | `AUGUR_DSN` env var                    | When set, the SDK streams + heartbeats; bundle is still written locally  |
| `capture_logprobs`  | `False`                                | When `True`, populate `modelio.response.logprobs` with per-token data (since 0.5.0) |

### Lifecycle

- `with DebugSession(...) as s:` opens the session.
- On `__exit__` (or explicit `s.close()`), the bundle is written atomically.
- If an exception bubbles up through the `with` block, the run is marked
  `halted` automatically.

### Methods

```python
def attach_observation(*, step_index: int, kind: str, png_bytes: bytes) -> str: ...
def record_step(step: StepTrace) -> None: ...

# Append a brain-loop iteration under an existing canonical step (since 0.3.0).
# Bumps the canonical step's `step_iterations` counter. See
# concepts/bundle-layout.md#step-iterations.
def record_step_iteration(
    step_id_or_index: str | int,
    iteration: StepTrace,
) -> None: ...

def record_event(event: DecisionEvent) -> None: ...
def set_status(status: str) -> None: ...
def add_tag(key: str, value: str) -> None: ...

# Mid-run capture-mode override (since 0.1.3)
def set_capture_mode(mode: str | CaptureMode) -> None: ...

# Stream a runner-log chunk to the server (since 0.1.3)
def append_log(text: str, *, step_index: int | None = None, name: str = "run") -> None: ...

# Add a post-hoc verdict to a previously-recorded step (since 0.1.5)
def attach_verifier(
    step_index: int,
    *,
    status: str,
    reason: str | None = None,
    check: str | None = None,
    expected: Any = None,
    actual: Any = None,
    evidence_refs: list[str] | None = None,
) -> None: ...

# Producer-side training-data helpers (since 0.1.8)
def set_costs(
    *,
    total_usd: float | None = None,
    model_usd: float | None = None,
    gpu_usd: float | None = None,
    proxy_usd: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cache_hit_tokens: int | None = None,
) -> None: ...

def set_step_costs(
    step_index: int,
    *,
    total_usd: float | None = None,
    model_usd: float | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cache_hit_tokens: int | None = None,
) -> None: ...

def set_score(
    step_index: int,
    score: float,
    *,
    comparator: str | None = None,        # verifier|model-judge|exact-match|human
    components: dict[str, float] | None = None,
) -> None: ...

def record_modelio(
    record: dict,
    *,
    step_index: int | None = None,
    layer: str | None = None,
    validate: bool = True,
) -> str:  # returns bundle-relative path
    ...

# Sentry-for-CUA primitives (since 0.1.13)
def set_step_versions(
    step_index: int,
    *,
    model: str | None = None,
    prompt: str | None = None,
    prompt_hash: str | None = None,
    tool_descriptions_hash: str | None = None,
    code_git_sha: str | None = None,
    grounder: str | None = None,
    env_fingerprint_ref: str | None = None,
) -> None: ...

def attach_env_fingerprint(
    step_index: int,
    *,
    url_host: str | None = None,
    url_path_template: str | None = None,
    viewport_hash: str | None = None,
    dom_hash: str | None = None,
    api_shapes: dict[str, str] | None = None,
    extensions: list[str] | None = None,
) -> None: ...

def record_judge_decision(
    step_index: int,
    *,
    judge_id: str,
    judge_type: str,                       # rule|model|human|hybrid
    verdict: dict,                         # {"status": "passed"|…, ...}
    confidence: float | None = None,
    evidence_refs: list[str] | None = None,
    judged_at: str | None = None,
    promote: bool = True,
) -> None: ...

# Sentry-for-CUA primitives — round two (since 0.1.14)
def mark_for_eval(
    step_index: int,
    reason: str,
    *,
    candidate_cluster_id: str | None = None,
) -> None: ...

def finalize_outcome(
    *,
    scope: str = "session",                # "step" | "session"
    step_index: int | None = None,
    verdict: dict | None = None,
    task_class: str | None = None,
    cost_summary: dict[str, int | float] | None = None,
) -> dict: ...

def successful_task_cost_summary() -> dict | None: ...

def record_reasoning(
    step_index: int | None,
    text: str,
    *,
    tokens: int | None = None,
    format: str = "adapter_inferred",       # adapter_inferred|claude_extended_thinking|openai_reasoning_summary
    model: str | None = None,
    ts: str | None = None,
) -> dict: ...

def declare_side_effect(
    step_index: int,
    resource: str,
    action: str,
    *,
    idempotency_key: str | None = None,
    reversibility: str = "irreversible",    # irreversible|reversible|compensated
    compensation_handle: str | None = None,
    provenance: str = "sdk_declared",       # sdk_declared|adapter_inferred|human_declared
    side_effect_id: str | None = None,
) -> str: ...                                # returns side_effect_id

def commit_side_effect(
    side_effect_id: str,
    observed_result: Any = None,
) -> None: ...

def mark_side_effect_aborted(
    side_effect_id: str,
    reason: str,
) -> None: ...

def abort_pending_side_effects(reason: str) -> list[str]: ...

def bind_intervention(
    adapter: Adapter,
    *,
    poll_timeout: float = 25.0,
) -> InterventionChannel | None: ...

# DebugSession constructor kwarg
# branch_context: dict | None = None
# When set, labels the run as a replay branch; lands on the session
# record and propagates a lightweight slice (no mutation payload) to
# every step. See BranchContext model.

# Branching-replay constructor (since 0.2.1)
@classmethod
def branch_from(
    cls,
    *,
    parent_run_id: str,
    branch_point_step_index: int,
    mutated_axis: str,              # model|prompt|action|grounder|tool_description
    mutation: dict,
    client_name: str,
    out_dir: str | Path,
    mode: str = "auto",              # replay|sandbox|auto
    parent_bundle: str | Path | None = None,
    branch_id: str | None = None,
    run_id: str | None = None,
    **session_kwargs,
) -> DebugSession: ...

@property
def branch_mode(self) -> str | None: ...

# Fanout-orchestrator helper (since 0.4.0)
@classmethod
def open_orchestrator(
    cls,
    *,
    run_id: str,
    client_name: str,
    out_dir: str | Path,
    session_name: str | None = None,
    tenant_id: str | None = None,
    tags: dict[str, str] | None = None,
    **session_kwargs,
) -> DebugSession: ...

@property
def is_orchestrator(self) -> bool: ...
```

`set_capture_mode(mode)` stamps `capture_mode` on every subsequent
`record_step` until cleared. The manifest's `capture_mode` remains the
default; an explicit `step["capture_mode"]` set by the caller always
wins over the override. Use it to upgrade from `metadata` to
`screenshots` after a failed verifier without restarting the session.

`append_log(text, ...)` POSTs to `/api/v1/runs/<run_id>/logs`. With
`step_index` set, the server routes the chunk to `logs/step-<idx>.log`;
without it, to `logs/<name>.log`. No-op when streaming is disabled —
local logs belong in the bundle's `logs/` directory written directly
via the configured `Store`.

### Training-data helpers (since 0.1.8)

`set_costs(...)` stamps a run-level cost rollup on the session. The
values appear on both the session record (`trace.json`) and the
manifest (`manifest.json#/costs`) so cost-aware consumers can read
either. Repeat calls are merge-on-call — unset dimensions are
preserved across calls.

`set_step_costs(step_index, ...)` patches the costs object on an
already-recorded step. Merge semantics; raises `ValueError` if no
step exists at `step_index`.

`set_score(step_index, score, ...)` adds a continuous reward signal
(0..1) to a recorded step's verdict. Merges into the existing
verdict — the categorical `status` is preserved. Score is clamped
to `[0.0, 1.0]`. `comparator`, when set, must be one of
`verifier | model-judge | exact-match | human`.

`record_modelio(record, *, step_index, layer, validate=True)` is the
producer-side helper for one model call's full input + output.
Validates the payload against `modelio.schema.json` (unless
`validate=False`), applies the session's redaction policy
(stamping `redaction_applied: true`), and writes to
`modelio/<step_index:04d>-<layer>-<seq>.json` (or
`modelio/run-<layer>-<seq>.json` for `step_index=None`). **Idempotent
on `prompt_hash`** — repeat calls with the same hash return the
existing path without staging a duplicate. Returns the bundle-relative
path. Step → modelio linkage is path-based; consumers find a step's
model calls by globbing `modelio/<step:04d>*.json`.

When streaming is enabled (DSN configured), the same call also
fires the redacted record live to
`POST /api/v1/runs/<run_id>/modelio/<relpath>` on a background
thread — producers don't need to wire anything extra; one
`record_modelio(...)` call covers both the bundle write and the
live ingest. If the server returns `403` (the tenant hasn't
enabled modelio capture), the sink latches off for the rest of
the session and subsequent records skip the network entirely;
they still land in the bundle on `close()`. All other errors are
logged at DEBUG and do not disable streaming.

### Per-token logprob capture (since 0.5.0)

For policy-gradient training (PPO, GRPO) and efficient DPO, consumers
need behavior-policy probabilities at the time of the model call.
0.5.0 wires the SDK to populate `modelio.response.logprobs` shipped
in `augur-schema 0.3.3`.

Opt in at the session level — off by default because logprobs roughly
double the OpenAI response payload size:

```python
session = DebugSession(
    run_id="...",
    client_name="...",
    out_dir="...",
    capture_logprobs=True,
)
```

Adapters read `session.capture_logprobs` to decide whether to pass
`top_logprobs=N` on outbound model calls. After the call returns, map
the vendor response to the canonical shape and stamp it on
`response.logprobs` before calling `record_modelio`:

```python
from augur_sdk import DebugSession, ModelApiAdapterBase

logprobs = ModelApiAdapterBase.extract_logprobs_from_response(api_response)
# Canonical: list[{"token", "token_id"?, "logprob", "top_alternatives"?[]}]
# or None when the vendor returned nothing recognisable.

session.record_modelio(
    {
        "layer": "model",
        "request": {...},
        "response": {
            "text": api_response["choices"][0]["message"]["content"],
            "logprobs": logprobs,
        },
    },
    step_index=step_index,
)
```

When `capture_logprobs=True` and the producer doesn't stamp anything
on the response, the SDK defaults `response.logprobs = []` so consumers
can tell "requested but vendor returned nothing" (empty array) from
"not requested" (field absent / null).

`extract_logprobs_from_response` recognises:

- **OpenAI** Chat Completions / Responses — `choices[].logprobs.content[]`
  with `{token, logprob, bytes?, top_logprobs?[]}`. `token_id` null
  unless the provider surfaces it (e.g. vLLM via OpenAI-compatible mode).
- **Anthropic** Messages — `content[].logprobs[]` with
  `{token, logprob, top_logprobs?[]}`. `token_id` always null on the
  public API.

Adapters with a non-standard shape SHOULD construct the canonical list
themselves and stamp it on `response.logprobs` directly — the helper
is a convenience, not a contract.

The default redaction policy is **context-aware** for logprob entries:
the generic `token`-key mask (intended for API / bearer tokens) is
skipped when the parent dict carries a numeric `logprob`, so the
decoded model-output tokens survive redaction. The generic rule still
defends every other surface.

### Sentry-for-CUA primitives (since 0.1.13)

`set_step_versions(step_index, ...)` stamps version axes onto
`step.captured_versions`. Used by the platform's causal-attribution
engine to disentangle which input changed when an outcome moves.
Partial updates merge; unset arguments are preserved. When
`record_modelio(step_index=...)` is called, the SDK auto-stamps
`model` (from `request.model`) and `prompt_hash` onto the same
block so adapters that already use `record_modelio` get the
linkage for free.

`attach_env_fingerprint(step_index, ...)` attaches a *structural*
environment fingerprint to a step: `url_host`, `url_path_template`,
`viewport_hash`, `dom_hash`, `api_shapes`, and `extensions`. Stored
side-by-side with the visual fingerprint
(`observation.hashes.phash_64`), not merged, so the platform's
determinism checker can attribute drift to agent / model / env
independently. The SDK never derives `dom_hash` itself — only
adapters that already probe DOM for diagnostics should populate it,
which preserves the screenshot-grounded core invariant.

`record_judge_decision(step_index, judge_id, judge_type, verdict, ...)`
makes rule, model, human, and hybrid judges first-class.
Decisions accumulate on `step.judge_decisions` (an ordered list)
and, by default, the supplied `verdict` is also promoted to the
operative `step.verdict` with `step.verdict_source` set to
`"<judge_type>:<judge_id>"` for provenance. Pass `promote=False`
to record the decision without changing the operative verdict.
`attach_verifier()` now also emits an implicit
`judge_type="rule"` decision alongside its verdict patch, so the
legacy entry point preserves provenance too. When streaming is
enabled, the decision is POSTed live to
`POST /api/v1/runs/<run_id>/steps/<step_index>/judge-decisions`
on a background thread.

`manifest.trajectory_fingerprint` is populated automatically at
session close — a deterministic digest over the
`(action.type, failure_class|verdict.status, normalized_target_label)`
sequence. Same shape → same fingerprint; one-step swap → small
Hamming distance on the bigram half. Algorithm is pluggable via
the `augur_sdk.fingerprints` entry point group (default = `cua_v1`).
See [concepts/trajectory-fingerprint.md](../concepts/trajectory-fingerprint.md).

### Eval, outcome, reasoning, branching, side-effects, intervention (since 0.1.14)

`mark_for_eval(step_index, reason, candidate_cluster_id=None)` tags a
step as a regression-fixture candidate. Idempotent on `step_index` —
last-write-wins. Tags land in `eval_candidates.json` at the bundle
root and on the live stream. The tag is value even at rest in the
bundle; CLI export can read it.

`finalize_outcome(scope=..., step_index=None, verdict=None, task_class=None, cost_summary=None)`
emits a single coupled record so the cost-per-outcome rollup
doesn't have to JOIN three independent fields. `scope="step"` records
one outcome per step; `scope="session"` rolls up per-step `step.costs`
across the run (session-level `set_costs()` wins ties) and emits a
session-level outcome. Records land in `outcomes.json` and on the
live stream. `successful_task_cost_summary()` returns the same
rolled-up summary in-process for budget asserts in tests.

`record_reasoning(step_index, text, tokens=None, format=..., model=None)`
captures explicit reasoning for models that emit it (Claude extended
thinking, OpenAI reasoning summaries). Records land in
`events/reasoning.jsonl` (one record per line) and on the live stream.
Reasoning text has its own redaction hook on `RedactionPolicy`:
`add_reasoning_redactor(fn)` registers a `str -> str` callable that
runs only over the `text` field of a reasoning record, in addition
to the regular redaction pipeline. `ModelApiAdapterBase` provides a
`extract_reasoning_from_response()` static method that pulls
reasoning blocks out of a Claude or OpenAI response — adapters can
forward the result straight to `record_reasoning()`.

`declare_side_effect(step_index, resource, action, ...)` declares an
irreversible action **before dispatch** so the ledger records the
agent's intent even if the run is killed mid-step. Returns a
`side_effect_id`. `commit_side_effect(side_effect_id, observed_result)`
lands the dispatcher's return payload (redacted) under
`side_effects/<step:04d>-<id>.json`. `mark_side_effect_aborted(sid,
reason)` is used by the intervention channel when a kill arrives
between declare and commit. `abort_pending_side_effects(reason)`
mass-aborts every declared-but-not-committed effect — used by the
kill handler. All four post live via `StreamingSink.post_side_effect()`.

The `branch_context=` constructor kwarg labels the session as a
replay-branch trajectory. Required fields:

```python
DebugSession(
    run_id="run_b",
    client_name="...",
    out_dir="...",
    branch_context={
        "parent_run_id": "run_a",
        "branch_point_step_index": 3,
        "mutated_axis": "model",                # model|prompt|action|grounder|tool_description
        "mutation": {"model": "claude-opus-4-7"},
        "branch_id": "branch_xyz",              # optional
    },
)
```

The full block lands on the session record (with `mutation` payload).
A lightweight slice (without `mutation`) propagates to every step so
server-side cohort filters can exclude branches by default without
joining back to the session. Production runs omit the field — no
regression.

### `DebugSession.branch_from(...)` (since 0.2.1)

The higher-level constructor for replay branches. Takes the parent
linkage explicitly, picks the right mode automatically, and
optionally loads the deterministic prefix from a parent bundle so
the branch's bundle includes every step from index 0 without
re-execution.

```python
# Mutate the model on a parent run; replay everything up to step 3,
# then run fresh against a sandbox.
with DebugSession.branch_from(
    parent_run_id="run_a",
    branch_point_step_index=3,
    mutated_axis="model",                       # model|prompt|action|grounder|tool_description
    mutation={"model": "claude-opus-4-7"},
    client_name="myadapter",
    out_dir="branch-bundle/",
    mode="auto",                                # replay|sandbox|auto
    parent_bundle="parent-bundle/",             # required when mode resolves to replay
) as branch:
    assert branch.branch_mode == "replay"
    # Steps 0–2 are already in `branch`'s recorder from the parent.
    # Producer continues from step 3 with the mutated model:
    branch.record_step({...step 3 with new behaviour...})
```

Modes:

- **`replay`** — load steps `[0, branch_point_step_index)` from
  `parent_bundle`'s `trace.json` into the new session, copying
  pre/post screenshot bytes verbatim. The producer continues fresh
  from `branch_point_step_index`. Refuses when
  `mutated_axis="action"` because the parent's downstream
  observations no longer reflect what the new agent will see
  (SPEC §10).
- **`sandbox`** — stamp `branch_context` only; the producer executes
  from step 0 against a live target. No prefix loading. The right
  mode when `mutated_axis="action"` or when the parent bundle isn't
  available.
- **`auto`** (default) — picks `sandbox` for `mutated_axis="action"`,
  `replay` for the four upstream axes.

`branch_id` and `run_id` default to
`f"{parent_run_id}:branch:<short-uuid>"` (per
`branch_context.schema.json`'s convention); pass either explicitly to
override. Any other `DebugSession` kwarg (`tags`, `client_version`,
`capture_mode`, `redaction_policy`, …) can be passed through.

The resolved mode is exposed on `session.branch_mode` for callers and
tests that want to introspect after construction.

### `DebugSession.open_orchestrator(...)` (since 0.4.0)

Opens a **parent-only "orchestrator" session** for fanout patterns.
When a producer fans out work across N child sessions (each carrying
`branch_context.parent_run_id=<orchestrator.run_id>`), the orchestrator
session is the row that surfaces aggregate metadata — phase counts,
fanout strategy, total budget — that no single child owns. It records
no steps of its own.

```python
with DebugSession.open_orchestrator(
    run_id="fanout-20b9a4786aa3-4e136449",
    client_name="myproducer",
    out_dir="parent-bundle/",
    session_name="boattrader-fanout (4 workers)",
    tenant_id="acme",
    tags={
        "phase1_workers": "4",
        "fanout_pattern": "phase1_collect_phase2_extract",
    },
) as parent:
    # Spawn N child sessions, each with
    # branch_context.parent_run_id=parent.run_id
    ...
    parent.set_costs(total_usd=sum(c.cost for c in completed_children))
```

Semantics:

- Marks `session.tags` with `augur.session_type=orchestrator`
  (exported as `augur_sdk.ORCHESTRATOR_TAG_KEY` /
  `ORCHESTRATOR_TAG_VALUE`) so the server / viewer can render it
  differently (aggregate stats, no step list).
- `record_step`, `record_step_iteration`, and `attach_observation`
  raise `RuntimeError` — record steps on the child sessions that share
  the `parent_run_id`.
- `set_costs`, `add_tag`, `set_live_endpoints`, `finalize_outcome` and
  the other session-level helpers work normally.
- `session_name` and `tenant_id` are conveniences that land in
  `session.tags` under those keys when provided; pass them directly via
  `tags=` if you prefer (explicit `tags={...}` entries win).

See [concepts/fanout-grouping.md](../concepts/fanout-grouping.md) for
the grouping contract this helper pairs with (augur-sdk#38).

`bind_intervention(adapter)` wires up a long-poll on
`GET <DSN-base>/runs/<run_id>/commands` and dispatches received
commands to the adapter:

| Command            | Adapter hook                                    |
|--------------------|-------------------------------------------------|
| `pause`            | `on_pause()`                                    |
| `resume`           | `on_resume()`                                   |
| `kill`             | `on_kill()` (after `abort_pending_side_effects`) |
| `inject_hint`      | `on_inject_hint(text)`                          |
| `override_action`  | `on_action_override(coords, provenance="human_override")` |

Returns `None` when streaming is disabled (no DSN). The SDK guarantees
`provenance="human_override"` on operator coordinates so the
trajectory preserves the SPEC §4 invariant that runtime action
selection is screenshot-grounded — never silently mixed with grounder
output. Adapters that don't implement a particular hook see the
channel degrade to a no-op for that command type. At-least-once
delivery; SDK dedupes on `command_id`. Every received command is
logged to the session's decision-event stream with the operator id.

`attach_verifier(step_index, status=..., ...)` lets an external harness
add a post-hoc verdict to a step the producer left as `unknown` (or
mis-classified). Useful for trace formats with no native verifier
signal (OpenAI / Anthropic Computer-Use, raw OSWorld): run an external
check against the step's post-state, then attach the result. Replaces
the step's `verdict` field in-place. When `check` / `expected` /
`actual` are given without an explicit `reason`, the SDK composes one:
`"<check>: expected=<expected> actual=<actual>"`. With streaming
enabled, the patched step is re-emitted to the live sink so viewers
see the update without waiting for `close()`. Raises `ValueError`
when no step exists at `step_index`. Precedence:
`native verdict > attach_verifier > inferred default`.

## `CaptureMode`

```python
class CaptureMode(StrEnum):
    OFF         = "off"
    METADATA    = "metadata"
    TRACE       = "trace"
    SCREENSHOTS = "screenshots"
    VIDEO       = "video"
    MODEL_IO    = "model_io"
    DISPATCH    = "dispatch"
    REPLAY      = "replay"
    FULL        = "full"
```

Modes are ordered: `CaptureMode.SCREENSHOTS >= CaptureMode.TRACE` etc.
See [concepts/capture-modes.md](../concepts/capture-modes.md).

```python
def resolve_capture_mode(
    explicit: CaptureMode | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> CaptureMode: ...
```

## Models (`augur_sdk.models`)

All TypedDicts. Pass dicts directly to the SDK — no construction step.

- `DebugSession` — top-level session record
- `StepTrace` — one step
- `Observation` — screenshot metadata
- `DecisionEvent` — planner/grounding/verifier/recovery event
- `ReplayFixture` — replay seed
- `DiagnosticFinding` — output of the rules engine
- `BundleManifest` — envelope returned by `session.close()`
- `BundleTrace` — `{ session, steps[] }`

Enum types:
- `CoordinateSpace = Literal["viewport_css_px", "device_px", "screenshot_px", "dom_client_rect"]`
- `Provenance     = Literal["screenshot", "dom", "human_override", "replay_candidate", "diagnostic"]`
- `StepStatus`, `VerdictStatus`, `RunStatus`, `RecoveryType`, `DecisionLayer`, `DecisionKind`

## Redaction (`augur_sdk.redaction`)

```python
DEFAULT_POLICY_ID = "default-pii-v1"

class RedactionPolicy:
    id: str
    drop_keys: frozenset[str]   # keys whose values are removed entirely
    mask_keys: frozenset[str]   # keys whose values are replaced with ***REDACTED:mask***
    redactors:  list[Callable[[str], str]]
    droppers:   list[Callable[[str, Any], bool]]
    def add_redactor(self, fn: Callable[[str], str]) -> None: ...
    def add_dropper(self, fn: Callable[[str, Any], bool]) -> None: ...
    def apply(self, value: Any, *, key: str | None = None) -> Any: ...

class DefaultRedactionPolicy(RedactionPolicy): ...
```

## Storage (`augur_sdk.storage`)

```python
class Store(Protocol):
    @property
    def root_uri(self) -> str: ...
    def signed_url(self, relpath: str, *, ttl_seconds: int = 3600) -> str: ...
    @contextmanager
    def open_write_binary(self, relpath: str) -> Iterator[IO[bytes]]: ...
    @contextmanager
    def open_write_text(self, relpath: str) -> Iterator[IO[str]]: ...
    def exists(self, relpath: str) -> bool: ...
    def read_text(self, relpath: str) -> str: ...
    def read_bytes(self, relpath: str) -> bytes: ...

class LocalFSStore: ...    # default; atomic write-and-rename
class S3Store:    ...      # stub; lands later
```

## Validation (`augur_sdk.validation`)

```python
@dataclass
class ValidationIssue:
    where: str
    message: str
    path: str

def validate_bundle(bundle_dir: str | Path) -> list[ValidationIssue]: ...
```

## Diagnostics (`augur_sdk.diagnostics`)

```python
class BundleContext:
    bundle_dir: Path
    @property
    def manifest(self) -> dict: ...
    @property
    def trace(self) -> dict: ...
    @property
    def session(self) -> dict: ...
    @property
    def steps(self) -> list[dict]: ...
    def events_for_step(self, step_index: int) -> list[dict]: ...
    def all_events(self) -> Iterator[dict]: ...
    def log_text(self, name: str = "runner.log") -> str | None: ...
    def log_paths(self) -> list[str]: ...

class RuleResult:
    findings: list[DiagnosticFinding]
    def emit(
        self, *,
        rule_id: str, severity: str, summary: str,
        evidence: Iterable[DiagnosticEvidence],
        step_index: int | None = None,
        recommendation: str | None = None,
    ) -> None: ...

class Rule(Protocol):
    rule_id: str
    severity: str
    def __call__(self, ctx: BundleContext, result: RuleResult) -> None: ...

def rule(rule_id: str, *, severity: str = "medium") -> Callable[[Callable], Rule]: ...

class RulesEngine:
    def __init__(self, rules: Iterable[Rule]) -> None: ...
    def evaluate(self, bundle_dir: Path | str) -> list[DiagnosticFinding]: ...

def load_pack(name: str) -> list[Rule]: ...
```

## Adapter base (`augur_sdk.adapter`)

```python
class Adapter(Protocol):
    name: ClassVar[str]
    SUPPORTED_SCHEMA_RANGE: ClassVar[tuple[str, str]]
    def on_run_start(self, *, run_id: str, client_version: str) -> dict[str, str] | None: ...
    def on_step(self, raw_step: Any) -> StepTrace | None: ...
    def on_action(self, raw_action: Any, step_index: int) -> dict[str, Any]: ...
    def on_decision(self, raw_event: Any, step_index: int | None) -> DecisionEvent: ...
    def on_observation(self, raw_obs: Any, step_index: int) -> Observation: ...
    def on_run_end(self, *, status: str) -> None: ...
```

See [reference/adapter-authoring.md](./adapter-authoring.md).

## Streaming (`augur_sdk.streaming`)

Internal — usually you set `AUGUR_DSN` and forget about it. But exposed
in case you want to drive the sink yourself:

```python
@dataclass
class DSN:
    base_url: str          # e.g. https://augur.example/api/v1
    token: str             # secret api_key
    tenant: str            # informational
    @classmethod
    def parse(cls, raw: str) -> "DSN": ...
    @classmethod
    def from_env(cls, explicit: str | None = None) -> "DSN | None": ...

class StreamingSink:
    def __init__(self, dsn: DSN, *, client_name: str, client_version: str | None) -> None: ...
    def begin(self, *, run_id: str, capture_mode: str) -> None: ...
    def end(self) -> None: ...
    def post_manifest(self, manifest: dict[str, Any]) -> None: ...
    def put_trace(self, trace: dict[str, Any]) -> None: ...
    def put_step(self, step: StepTrace) -> None: ...
    def put_session_costs(self, costs: dict[str, int | float]) -> None: ...
    def post_events(self, events: list[DecisionEvent], *, step_index: int | None) -> None: ...
    def post_screenshot(self, step_index: int, kind: str, png_bytes: bytes) -> None: ...
    def post_modelio(self, relpath: str, record: dict[str, Any]) -> None: ...
    def post_logs(self, *, text: str, name: str = "run", step_index: int | None = None) -> None: ...
```

`put_session_costs(costs)` is driven by `Session.set_costs(...)` since
0.3.1. PUTs the cumulative `debug_session.costs` dict to
`/api/v1/runs/<run_id>/costs` — server is idempotent last-write-wins,
so each call carries the running total (not the delta). Honours the
shared 429+`Retry-After` retry path. No PUT fires for `set_costs()`
with no kwargs set.

`post_modelio(relpath, record)` is driven by `Session.record_modelio()`
— `relpath` is the bundle-relative path returned by the recorder
(e.g. `modelio/0003-planner-0.json`), so the live URL is
`/api/v1/runs/<run_id>/<relpath>`. Fire-and-forget on a background
thread; a `403` from the server latches the sink off for the
session (the bundle still owns the record).

`post_logs(text, ...)` is driven by `Session.append_log()` and POSTs
the chunk to `/api/v1/runs/<run_id>/logs`; the server routes it to
`logs/<name>.log` or `logs/step-<idx>.log`.

## Version

```python
import augur_sdk
augur_sdk.__version__               # e.g. "0.3.0" — SDK release version

# Range of JSON Schema CONTENT versions this SDK can produce + read
# (the `$id` segment, not the `augur-schema` package version).
# Additive field updates in `augur-schema` (e.g. `step_iterations`
# in 0.3.2) do NOT bump this — they slot into the same content
# version. See SPEC §5.
augur_sdk.SUPPORTED_SCHEMA_RANGE    # ("0.1", "0.1")

from augur_schema import SCHEMA_VERSION
SCHEMA_VERSION                       # authoritative content version
```
