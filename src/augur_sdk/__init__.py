"""Augur SDK — public surface.

Spec §6. The capture controller, event recorder, redaction pipeline, and
bundle writer are exposed here. Adapter authors should import from
`augur_sdk.adapter` and `augur_sdk.models`.
"""

from augur_sdk._version import SUPPORTED_SCHEMA_RANGE, __version__
from augur_sdk.adapter import Adapter
from augur_sdk.capture import CaptureMode, resolve_capture_mode
from augur_sdk.model_api_adapter import ModelApiAdapterBase
from augur_sdk.models import (
    Action,
    BranchContext,
    BundleManifest,
    BundleTrace,
    CapturedVersions,
    DecisionEvent,
    DiagnosticFinding,
    EnvFingerprint,
    Grounding,
    JudgeDecision,
    Observation,
    RecoveryDecision,
    ReplayFixture,
    SideEffect,
    StepTrace,
    Verdict,
)
from augur_sdk.models import (
    DebugSession as DebugSessionRecord,
)
from augur_sdk.redaction import (
    DEFAULT_POLICY_ID,
    DefaultRedactionPolicy,
    RedactionPolicy,
)
from augur_sdk.session import DebugSession
from augur_sdk.storage import LocalFSStore, S3Store, Store

__all__ = [
    "Action",
    "Adapter",
    "BranchContext",
    "BundleManifest",
    "BundleTrace",
    "CaptureMode",
    "CapturedVersions",
    "DEFAULT_POLICY_ID",
    "DebugSession",
    "DebugSessionRecord",
    "DecisionEvent",
    "DefaultRedactionPolicy",
    "DiagnosticFinding",
    "EnvFingerprint",
    "Grounding",
    "JudgeDecision",
    "LocalFSStore",
    "ModelApiAdapterBase",
    "Observation",
    "RecoveryDecision",
    "RedactionPolicy",
    "ReplayFixture",
    "S3Store",
    "SideEffect",
    "StepTrace",
    "Store",
    "SUPPORTED_SCHEMA_RANGE",
    "Verdict",
    "__version__",
    "resolve_capture_mode",
]
