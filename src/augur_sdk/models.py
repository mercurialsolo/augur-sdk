"""Augur data models (TypedDicts).

These mirror the canonical JSON Schemas under
`src/augur_sdk/_schema/json/`. We use TypedDicts (not dataclasses
or pydantic) so callers can construct records as plain dicts and the SDK can
serialize them directly to JSON without an intermediate copy.

Validation against the JSON Schemas is the authoritative check; the types
here are for editor ergonomics and adapter contract clarity.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

CoordinateSpace = Literal[
    "viewport_css_px", "device_px", "screenshot_px", "dom_client_rect"
]

Provenance = Literal[
    "screenshot", "dom", "human_override", "replay_candidate", "diagnostic"
]

RunStatus = Literal["running", "succeeded", "failed", "cancelled", "halted"]
StepStatus = Literal[
    "pending", "running", "succeeded", "failed", "skipped", "recovered"
]
VerdictStatus = Literal["passed", "failed", "recoverable", "skipped", "unknown"]
RecoveryType = Literal[
    "retry",
    "alternate_grounding",
    "skip",
    "halt",
    "replan",
    "human_handoff",
    "none",
]
DecisionLayer = Literal[
    "planner",
    "grounding",
    "model",
    "dispatch",
    "verifier",
    "step_recovery",
    "routing",
    "runner",
    "adapter",
]
DecisionKind = Literal["decision", "observation", "error", "info", "metric"]


class ClientInfo(TypedDict, total=False):
    name: str
    version: str
    git_sha: str


class Viewport(TypedDict, total=False):
    width: int
    height: int
    device_scale_factor: float


class Scroll(TypedDict):
    x: int
    y: int


class Hashes(TypedDict, total=False):
    sha256: str
    phash_64: str


class RedactionRegion(TypedDict, total=False):
    x1: int
    y1: int
    x2: int
    y2: int
    label: str


class ObservationRedaction(TypedDict, total=False):
    applied: bool
    policy_id: str
    regions: list[RedactionRegion]


class Observation(TypedDict, total=False):
    artifact: str
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    width: int
    height: int
    coordinate_space: CoordinateSpace
    viewport: Viewport
    url: str
    title: str
    scroll: Scroll
    hashes: Hashes
    redaction: ObservationRedaction
    missing: bool


class Action(TypedDict, total=False):
    type: str
    params: dict[str, Any]
    coordinate_space: CoordinateSpace
    dispatch_backend: str


class GroundingCoords(TypedDict):
    x: float
    y: float


class Grounding(TypedDict, total=False):
    provider: str
    target_label: str
    coordinates: GroundingCoords
    confidence: float
    evidence: str
    provenance: Provenance


class Verdict(TypedDict, total=False):
    status: VerdictStatus
    reason: str
    evidence_refs: list[str]


class RecoveryDecision(TypedDict, total=False):
    type: RecoveryType
    reason: str
    attempt: int


class StepTrace(TypedDict, total=False):
    step_id: str
    step_index: int
    intent: str
    step_type: str
    required: bool
    status: StepStatus
    failure_class: str
    started_at: str
    ended_at: str | None
    duration_ms: int | None
    observation_pre: str | None
    observation_post: str | None
    action: Action
    grounding: Grounding
    verdict: Verdict
    recovery_decision: RecoveryDecision | None
    events: list[str]
    logs: list[str]


class DecisionEvent(TypedDict, total=False):
    ts: str
    step_index: int
    layer: DecisionLayer
    kind: DecisionKind
    summary: str
    detail: dict[str, Any]


class LiveEndpoints(TypedDict, total=False):
    status_url: str
    video_url: str
    reasoning_url: str


class DebugSession(TypedDict, total=False):
    schema_version: str
    debug_session_id: str
    run_id: str
    client: ClientInfo
    capture_mode: str
    started_at: str
    ended_at: str | None
    status: RunStatus
    artifact_root: str
    trace_uri: str
    live: LiveEndpoints | None
    tags: dict[str, str]


class ReplayExpected(TypedDict, total=False):
    action_type: str
    acceptable_regions: list[dict[str, Any]]
    verdict_status: VerdictStatus


class CapturedVersions(TypedDict, total=False):
    model: str
    prompt: str
    code_git_sha: str
    grounder: str


class ReplayFixture(TypedDict, total=False):
    fixture_id: str
    step_id: str
    mode: Literal[
        "observation_replay",
        "handler_replay",
        "model_replay",
        "sandbox_replay",
        "shadow_replay",
    ]
    task: str
    observation: str
    prior_steps: str | None
    expected: ReplayExpected
    captured_versions: CapturedVersions


class DiagnosticEvidence(TypedDict):
    type: Literal["log", "step", "event", "screenshot", "diff", "crop", "trace"]
    ref: str


class DiagnosticFinding(TypedDict, total=False):
    rule_id: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    summary: str
    recommendation: str
    step_index: int
    evidence: list[DiagnosticEvidence]


class BundleTrace(TypedDict):
    session: DebugSession
    steps: list[StepTrace]


class BundleRedaction(TypedDict, total=False):
    policy_id: str
    applied: bool


class BundlePaths(TypedDict, total=False):
    steps: Literal["steps/"]
    screenshots: Literal["screenshots/"]
    crops: Literal["crops/"]
    diffs: Literal["diffs/"]
    events: Literal["events/"]
    logs: Literal["logs/"]
    replay: Literal["replay/"]
    diagnostics: Literal["diagnostics/"]


class BundleManifest(TypedDict, total=False):
    schema_version: str
    bundle_format: Literal["augur-bundle"]
    run_id: str
    debug_session_id: str
    client: ClientInfo
    capture_mode: str
    created_at: str
    redaction: BundleRedaction
    trace: Literal["trace.json"]
    step_count: int
    paths: BundlePaths
    signatures: NotRequired[dict[str, str]]
    missing: NotRequired[list[str]]
