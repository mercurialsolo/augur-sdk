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
    ): ...

    def record_step(self, step: StepTrace) -> None: ...
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

### Lifecycle

- `with DebugSession(...) as s:` opens the session.
- On `__exit__` (or explicit `s.close()`), the bundle is written atomically.
- If an exception bubbles up through the `with` block, the run is marked
  `halted` automatically.

### Methods

```python
def attach_observation(*, step_index: int, kind: str, png_bytes: bytes) -> str: ...
def record_step(step: StepTrace) -> None: ...
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
    def post_events(self, events: list[DecisionEvent], *, step_index: int | None) -> None: ...
    def post_screenshot(self, step_index: int, kind: str, png_bytes: bytes) -> None: ...
    def post_modelio(self, relpath: str, record: dict[str, Any]) -> None: ...
    def post_logs(self, *, text: str, name: str = "run", step_index: int | None = None) -> None: ...
```

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
augur_sdk.__version__               # "0.1.0"
augur_sdk.SUPPORTED_SCHEMA_RANGE    # ("0.1", "0.1")
```
