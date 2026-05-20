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
```

## Version

```python
import augur_sdk
augur_sdk.__version__               # "0.1.0"
augur_sdk.SUPPORTED_SCHEMA_RANGE    # ("0.1", "0.1")
```
