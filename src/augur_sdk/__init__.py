"""Augur SDK — public surface.

Spec §6. The capture controller, event recorder, redaction pipeline, and
bundle writer are exposed here. Adapter authors should import from
`augur_sdk.adapter` and `augur_sdk.models`.
"""

from augur_sdk._version import SUPPORTED_SCHEMA_RANGE, __version__
from augur_sdk.adapter import Adapter
from augur_sdk.capture import CaptureMode, resolve_capture_mode
from augur_sdk.models import (
    Action,
    BundleManifest,
    BundleTrace,
    DecisionEvent,
    DiagnosticFinding,
    Grounding,
    Observation,
    RecoveryDecision,
    ReplayFixture,
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
    "BundleManifest",
    "BundleTrace",
    "CaptureMode",
    "DEFAULT_POLICY_ID",
    "DebugSession",
    "DebugSessionRecord",
    "DecisionEvent",
    "DefaultRedactionPolicy",
    "DiagnosticFinding",
    "Grounding",
    "LocalFSStore",
    "Observation",
    "RecoveryDecision",
    "RedactionPolicy",
    "ReplayFixture",
    "S3Store",
    "StepTrace",
    "Store",
    "SUPPORTED_SCHEMA_RANGE",
    "Verdict",
    "__version__",
    "resolve_capture_mode",
]
